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
from decision_engine import Reading as DecisionReading
from decision_engine import decide_relay_state
from excel_export import export_readings_to_excel
from models import (
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
            app_state.commanded_relay_state = commanded

        mode = app_state.mode

        row = ReadingRow(
            timestamp=now,
            temp_c=reading.temp_c,
            humidity=reading.humidity,
            soil_moisture=reading.soil_moisture,
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
        offline = (
            app_state.last_seen is None
            or (datetime.utcnow() - app_state.last_seen).total_seconds() > OFFLINE_THRESHOLD_SECONDS
        )
        # The ESP32's "ac" relay pin is unwired (AC is HA-only) and its
        # reported value is meaningless, so report our own last-confirmed
        # Home Assistant state for ac instead - that's the only place the
        # real AC state actually lives.
        reported = app_state.reported_relay_state
        if reported is not None and app_state.last_ha_ac_state is not None:
            reported = reported.model_copy(update={"ac": app_state.last_ha_ac_state})

        return StatusOut(
            mode=app_state.mode,
            commanded_relay_state=app_state.commanded_relay_state,
            reported_relay_state=reported,
            last_seen=app_state.last_seen,
            latest_reading=app_state.latest_reading,
            offline=offline,
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
            "reported_relay_state": json.loads(row.reported_relay_state),
            "commanded_relay_state": json.loads(row.commanded_relay_state),
            "mode": row.mode,
        }
        for row in rows
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


@app.post("/api/export")
def trigger_export(session: Session = Depends(get_session)):
    count = export_readings_to_excel(session)
    return {"exported_rows": count}


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
