import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, SQLModel, create_engine, select

import ha_client
from chart_data import bucket_by_step
from decision_engine import Reading as DecisionReading
from decision_engine import decide_relay_state
from excel_export import EXPORT_PATH, export_readings_to_excel
from light_schedule import is_light_on
from models import (
    HaStatus,
    LightManualIn,
    LightScheduleIn,
    LightStatus,
    ModeIn,
    ReadingRow,
    RelayIn,
    RelayState,
    SensorReading,
    StatusOut,
    TelemetryIn,
    TelemetryOut,
)
from scheduler import start_scheduler

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("main")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/grow.db")
OFFLINE_THRESHOLD_SECONDS = float(os.getenv("OFFLINE_THRESHOLD_SECONDS", "90"))
BASELINE_WINDOW_MINUTES = float(os.getenv("BASELINE_WINDOW_MINUTES", "30"))
ALERT_TEMP_C = float(os.getenv("ALERT_TEMP_C", "32.0"))
HISTORY_DEFAULT_LIMIT = int(os.getenv("HISTORY_DEFAULT_LIMIT", "100"))
HISTORY_MAX_LIMIT = int(os.getenv("HISTORY_MAX_LIMIT", "1000"))

# Purely descriptive - identifies what's actually in the tent for the
# dashboard header. Not consulted by any control logic; change it freely
# per grow without touching code.
GROW_PROFILE_NAME = os.getenv("GROW_PROFILE_NAME", "Custom grow profile")
TENT_SIZE_M2 = os.getenv("TENT_SIZE_M2", "")

# Light schedule defaults. Starts with the schedule OFF (light under
# manual control, off) so a fresh deploy never starts cycling a light
# based on an unreviewed default photoperiod - the grower opts in via the
# dashboard once they've picked an on_hours value that's actually right
# for what's in the tent.
LIGHT_DEFAULT_ON_HOURS = int(os.getenv("LIGHT_DEFAULT_ON_HOURS", "18"))
LIGHT_SCHEDULE_ENABLED_DEFAULT = os.getenv("LIGHT_SCHEDULE_ENABLED_DEFAULT", "false").lower() == "true"

connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


class AppState:
    """In-memory, single-process runtime state. Guarded by `lock` since
    APScheduler jobs and request handlers run on different threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode: str = "auto"
        self.commanded_relay_state = RelayState()
        self.reported_relay_state: Optional[RelayState] = None
        self.last_seen: Optional[datetime] = None
        self.latest_reading: Optional[SensorReading] = None
        self.last_manual_activity: Optional[datetime] = None
        # The AC has no physical relay - it's controlled entirely through
        # Home Assistant. This tracks the last state we successfully
        # confirmed HA applied, so /api/status can report real AC state
        # instead of the ESP32's now-unused "ac" relay pin, and so we only
        # call HA when the desired state actually changes.
        self.last_ha_ac_state: Optional[bool] = None
        # Light: independent of `mode` entirely. Either the schedule
        # decides (is_light_on, recomputed fresh every time - no stored
        # "next toggle" state) or, when the schedule is off, this manual
        # value holds until the dashboard changes it.
        self.light_schedule_enabled: bool = LIGHT_SCHEDULE_ENABLED_DEFAULT
        self.light_on_hours: int = LIGHT_DEFAULT_ON_HOURS
        self.light_commanded: bool = False
        self.light_reported: Optional[bool] = None
        # Home Assistant reachability, refreshed on its own schedule (see
        # scheduler._check_ha_connection) rather than per-request. None
        # until the first check completes.
        self.ha_reachable: Optional[bool] = None
        self.ha_last_checked: Optional[datetime] = None


app_state = AppState()
app = FastAPI(title="Grow Tent Controller")


def get_session():
    with Session(engine) as session:
        yield session


@app.on_event("startup")
def on_startup():
    os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")) or ".", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    app.state.scheduler = start_scheduler(app_state, engine)


@app.on_event("shutdown")
def on_shutdown():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)


def _compute_baseline(session: Session, now: datetime) -> tuple[float, float, float]:
    """Rolling average temp/humidity over the last BASELINE_WINDOW_MINUTES,
    used by the decision engine to detect a *rise* rather than react to
    absolute temperature. Falls back to the current reading (delta=0) when
    there's no history yet."""
    window_start = now - timedelta(minutes=BASELINE_WINDOW_MINUTES)
    rows = session.exec(
        select(ReadingRow).where(ReadingRow.timestamp >= window_start)
    ).all()
    if not rows:
        return None, None, 0  # type: ignore[return-value]
    avg_temp = sum(r.temp_c for r in rows) / len(rows)
    avg_humidity = sum(r.humidity for r in rows) / len(rows)
    return avg_temp, avg_humidity, len(rows)


def _maybe_send_alerts(reading: SensorReading, reported: RelayState) -> None:
    """Best-effort HA notifications. Must never raise into the caller."""
    try:
        if reading.temp_c >= ALERT_TEMP_C:
            ha_client.send_alert(
                "high_temp",
                f"Grow tent temperature is {reading.temp_c:.1f} degrees, above the {ALERT_TEMP_C:.0f} degree alert threshold.",
            )
            ha_client.toggle_grow_tent_switch(True)
    except Exception:  # noqa: BLE001
        logger.exception("Alert dispatch failed")


def _light_status(now: datetime) -> LightStatus:
    """Must be called with app_state.lock held. Single source of truth for
    "what should the light be doing right now" - used by /api/telemetry,
    /api/status, and both light control endpoints, so they can never
    disagree with each other."""
    commanded = is_light_on(now, app_state.light_on_hours) if app_state.light_schedule_enabled else app_state.light_commanded
    return LightStatus(
        schedule_enabled=app_state.light_schedule_enabled,
        on_hours=app_state.light_on_hours,
        off_hours=24 - app_state.light_on_hours,
        commanded=commanded,
        reported=app_state.light_reported,
    )


def _sync_ac_to_ha(ac_on: bool) -> None:
    """Pushes the AC's desired state to Home Assistant - this is the only
    path that actually controls it, since it has no ESP32 relay. Skips the
    call if we already believe HA is in that state, and only marks it
    confirmed on success, so a failed call gets retried on the next cycle
    instead of silently getting stuck out of sync."""
    with app_state.lock:
        if app_state.last_ha_ac_state == ac_on:
            return
    try:
        if ha_client.set_ac(ac_on):
            with app_state.lock:
                app_state.last_ha_ac_state = ac_on
    except Exception:  # noqa: BLE001
        logger.exception("AC sync to Home Assistant failed")


@app.post("/api/telemetry", response_model=TelemetryOut)
def post_telemetry(
    payload: TelemetryIn, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
):
    now = datetime.utcnow()
    reading = SensorReading(
        temp_c=payload.temp_c, humidity=payload.humidity, soil_moisture=payload.soil_moisture
    )

    with app_state.lock:
        app_state.last_seen = now
        app_state.reported_relay_state = payload.relay_state
        app_state.light_reported = payload.relay_state.light
        app_state.latest_reading = reading

        if app_state.mode == "manual":
            commanded = app_state.commanded_relay_state
        else:
            baseline_temp, baseline_humidity, _n = _compute_baseline(session, now)
            de_reading = DecisionReading(
                temp_c=reading.temp_c,
                humidity=reading.humidity,
                soil_moisture=reading.soil_moisture,
                baseline_temp_c=baseline_temp if baseline_temp is not None else reading.temp_c,
                baseline_humidity=baseline_humidity if baseline_humidity is not None else reading.humidity,
            )
            commanded = decide_relay_state(de_reading, app_state.commanded_relay_state)

        # Light is never touched by decide_relay_state() or the
        # auto/manual mode above - it's driven entirely by its own
        # schedule/manual switch, computed fresh every cycle.
        commanded = commanded.model_copy(update={"light": _light_status(now).commanded})
        app_state.commanded_relay_state = commanded

        mode = app_state.mode

        row = ReadingRow(
            timestamp=now,
            temp_c=reading.temp_c,
            humidity=reading.humidity,
            soil_moisture=reading.soil_moisture,
            light_state=payload.relay_state.light,
            reported_relay_state=payload.relay_state.model_dump_json(),
            commanded_relay_state=commanded.model_dump_json(),
            mode=mode,
        )
        session.add(row)
        session.commit()

    # Backgrounded so a slow/unreachable Home Assistant never delays the
    # response the ESP32 is waiting on (it has its own ~5s HTTP timeout,
    # the same order of magnitude as HA_REQUEST_TIMEOUT_SECONDS).
    background_tasks.add_task(_maybe_send_alerts, reading, payload.relay_state)
    background_tasks.add_task(_sync_ac_to_ha, commanded.ac)

    return TelemetryOut(mode=mode, relay_state=commanded)


@app.get("/api/status", response_model=StatusOut)
def get_status():
    with app_state.lock:
        now = datetime.utcnow()
        offline = (
            app_state.last_seen is None
            or (now - app_state.last_seen).total_seconds() > OFFLINE_THRESHOLD_SECONDS
        )
        # The ESP32's "ac" relay pin is unwired (AC is HA-only) and its
        # reported value is meaningless, so report our own last-confirmed
        # Home Assistant state for ac instead - that's the only place the
        # real AC state actually lives.
        reported = app_state.reported_relay_state
        if reported is not None and app_state.last_ha_ac_state is not None:
            reported = reported.model_copy(update={"ac": app_state.last_ha_ac_state})

        # Commanded light state is recomputed fresh here (not read from
        # commanded_relay_state, which only updates on the ESP32's own
        # ~20s telemetry cadence) so the dashboard reflects a schedule
        # boundary the moment it's crossed, not up to a cycle late.
        commanded = app_state.commanded_relay_state.model_copy(
            update={"light": _light_status(now).commanded}
        )

        return StatusOut(
            mode=app_state.mode,
            commanded_relay_state=commanded,
            reported_relay_state=reported,
            last_seen=app_state.last_seen,
            latest_reading=app_state.latest_reading,
            offline=offline,
            light=_light_status(now),
            ha=HaStatus(reachable=app_state.ha_reachable, checked_at=app_state.ha_last_checked),
        )


@app.get("/api/profile")
def get_profile():
    """Purely descriptive metadata for the dashboard header - what's
    actually in the tent right now. Sourced from env vars, not the
    decision engine's thresholds, so it's safe to change per grow without
    touching any control logic."""
    return {"profile_name": GROW_PROFILE_NAME, "tent_size_m2": TENT_SIZE_M2 or None}


@app.get("/api/history")
def get_history(
    limit: int = Query(HISTORY_DEFAULT_LIMIT, gt=0, le=HISTORY_MAX_LIMIT),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    session: Session = Depends(get_session),
):
    stmt = select(ReadingRow)
    if since is not None:
        stmt = stmt.where(ReadingRow.timestamp >= since)
    if until is not None:
        stmt = stmt.where(ReadingRow.timestamp <= until)
    stmt = stmt.order_by(ReadingRow.timestamp.desc()).limit(limit)
    rows = session.exec(stmt).all()
    return [
        {
            "timestamp": row.timestamp,
            "temp_c": row.temp_c,
            "humidity": row.humidity,
            "soil_moisture": row.soil_moisture,
            "light_state": row.light_state,
            "reported_relay_state": json.loads(row.reported_relay_state),
            "commanded_relay_state": json.loads(row.commanded_relay_state),
            "mode": row.mode,
        }
        for row in rows
    ]


def _parse_date(value: str, param_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{param_name} must be YYYY-MM-DD")


@app.get("/api/charts/day")
def get_day_chart(
    date: str = Query(..., description="YYYY-MM-DD, interpreted as a UTC day"),
    step_minutes: int = Query(60, description="Bucket width: 30 or 60"),
    session: Session = Depends(get_session),
):
    """Averaged temp/humidity/soil-moisture in fixed-width buckets across
    one UTC day - aggregated server-side so the browser never has to fetch
    (and the chart never has to render) thousands of raw rows for a single
    day's view."""
    if step_minutes not in (30, 60):
        raise HTTPException(status_code=400, detail="step_minutes must be 30 or 60")
    day_start = _parse_date(date, "date")
    day_end = day_start + timedelta(days=1)

    rows = session.exec(
        select(ReadingRow)
        .where(ReadingRow.timestamp >= day_start, ReadingRow.timestamp < day_end)
        .order_by(ReadingRow.timestamp)
    ).all()
    readings = [(r.timestamp, r.temp_c, r.humidity, r.soil_moisture) for r in rows]

    buckets = bucket_by_step(readings, day_start, step_minutes)
    return [
        {
            "timestamp": ts.isoformat(),
            "temp_c": point.temp_c,
            "humidity": point.humidity,
            "soil_moisture": point.soil_moisture,
        }
        for ts, point in buckets
    ]


@app.get("/api/charts/week")
def get_week_chart(
    week_start: str = Query(..., description="YYYY-MM-DD of the first day, interpreted as UTC"),
    session: Session = Depends(get_session),
):
    """4 points per UTC day (6-hour averages) for the 7 days starting at
    week_start - a coarser cousin of the day chart's 30/60min buckets,
    same underlying bucket_by_step()."""
    start = _parse_date(week_start, "week_start")
    end = start + timedelta(days=7)

    rows = session.exec(
        select(ReadingRow)
        .where(ReadingRow.timestamp >= start, ReadingRow.timestamp < end)
        .order_by(ReadingRow.timestamp)
    ).all()
    readings = [(r.timestamp, r.temp_c, r.humidity, r.soil_moisture) for r in rows]

    buckets = bucket_by_step(readings, start, step_minutes=360, window_minutes=7 * 24 * 60)
    return [
        {
            "timestamp": ts.isoformat(),
            "temp_c": point.temp_c,
            "humidity": point.humidity,
            "soil_moisture": point.soil_moisture,
        }
        for ts, point in buckets
    ]


@app.post("/api/mode")
def set_mode(payload: ModeIn):
    with app_state.lock:
        app_state.mode = payload.mode
        app_state.last_manual_activity = datetime.utcnow()
        return {"mode": app_state.mode, "relay_state": app_state.commanded_relay_state.model_dump()}


@app.post("/api/relay")
def set_relay(payload: RelayIn, background_tasks: BackgroundTasks):
    with app_state.lock:
        if app_state.mode != "manual":
            raise HTTPException(status_code=409, detail="mode is not manual")
        setattr(app_state.commanded_relay_state, payload.relay, payload.state)
        app_state.last_manual_activity = datetime.utcnow()
        result = {
            "relay": payload.relay,
            "state": payload.state,
            "commanded_relay_state": app_state.commanded_relay_state.model_dump(),
        }

    if payload.relay == "ac":
        # Unlike fan/pump, the ESP32 never picks this up on its own poll -
        # there's no relay for it to poll. Push it now rather than waiting
        # for the next telemetry cycle to (indirectly) trigger the sync.
        background_tasks.add_task(_sync_ac_to_ha, payload.state)

    return result


@app.post("/api/light/schedule", response_model=LightStatus)
def set_light_schedule(payload: LightScheduleIn):
    """Master switch for the light: enabling the schedule hands control to
    is_light_on() (independent of the environmental auto/manual `mode`);
    disabling it falls back to whatever was last set via
    /api/light/manual. on_hours is always saved even when the schedule is
    currently off, so it's ready as soon as it's turned on."""
    with app_state.lock:
        app_state.light_schedule_enabled = payload.enabled
        app_state.light_on_hours = payload.on_hours
        return _light_status(datetime.utcnow())


@app.post("/api/light/manual", response_model=LightStatus)
def set_light_manual(payload: LightManualIn):
    with app_state.lock:
        if app_state.light_schedule_enabled:
            raise HTTPException(status_code=409, detail="light schedule is enabled")
        app_state.light_commanded = payload.state
        return _light_status(datetime.utcnow())


@app.post("/api/export")
def trigger_export(session: Session = Depends(get_session)):
    export_readings_to_excel(session)
    return FileResponse(
        EXPORT_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="readings_export.xlsx",
    )


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
