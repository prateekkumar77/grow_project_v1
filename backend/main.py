import base64
import binascii
import json
import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import Session, SQLModel, create_engine, select

import auth
from activity_log import AUTO_ACTOR, ActivityLog, RelayActivityTracker
from chart_data import bucket_by_step
from decision_engine import GrowProfile
from decision_engine import Reading as DecisionReading
from decision_engine import decide_relay_state
from exhaust_schedule import is_exhaust_on
from excel_export import (
    ACTIVITY_EXPORT_PATH,
    EXPORT_PATH,
    export_activity_log_to_excel,
    export_readings_to_excel,
)
from light_schedule import is_light_on
from models import (
    ActivityEntryOut,
    ActivityLogRow,
    ExhaustManualIn,
    ExhaustScheduleIn,
    ExhaustStatus,
    GrowProfileIn,
    GrowProfileOut,
    GrowProfileRow,
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
ALERT_TEMP_C = float(os.getenv("ALERT_TEMP_C", "32.0"))
HISTORY_DEFAULT_LIMIT = int(os.getenv("HISTORY_DEFAULT_LIMIT", "100"))
HISTORY_MAX_LIMIT = int(os.getenv("HISTORY_MAX_LIMIT", "1000"))

# Purely descriptive - identifies what's actually in the tent for the
# dashboard header. Not consulted by any control logic; change it freely
# per grow without touching code.
GROW_PROFILE_NAME = os.getenv("GROW_PROFILE_NAME", "Custom grow profile")
TENT_SIZE_M2 = os.getenv("TENT_SIZE_M2", "")
# Optional - the dashboard derives a "day N" counter from this, but it's
# otherwise as cosmetic as the two above. Blank by default; YYYY-MM-DD.
GROW_START_DATE = os.getenv("GROW_START_DATE", "")

# Light schedule defaults. Starts with the schedule OFF (light under
# manual control, off) so a fresh deploy never starts cycling a light
# based on an unreviewed default photoperiod - the grower opts in via the
# dashboard once they've picked an on_hours value that's actually right
# for what's in the tent.
LIGHT_DEFAULT_ON_HOURS = int(os.getenv("LIGHT_DEFAULT_ON_HOURS", "18"))
LIGHT_SCHEDULE_ENABLED_DEFAULT = os.getenv("LIGHT_SCHEDULE_ENABLED_DEFAULT", "false").lower() == "true"

# Exhaust schedule defaults - same "starts off" rationale as the light
# schedule: a fresh deploy shouldn't start cycling a relay on an
# unreviewed default run/interval before the grower has confirmed it.
EXHAUST_DEFAULT_RUN_MINUTES = int(os.getenv("EXHAUST_DEFAULT_RUN_MINUTES", "1"))
EXHAUST_DEFAULT_INTERVAL_MINUTES = int(os.getenv("EXHAUST_DEFAULT_INTERVAL_MINUTES", "5"))
EXHAUST_SCHEDULE_ENABLED_DEFAULT = os.getenv("EXHAUST_SCHEDULE_ENABLED_DEFAULT", "false").lower() == "true"

connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def _default_grow_profile() -> GrowProfileOut:
    """The grow profile before any dashboard save has ever happened - the
    same .env values decide_relay_state() used to read as module-level
    constants. Once a user saves via POST /api/profile, the DB-backed
    value in AppState.grow_profile takes over permanently and this is
    never consulted again until a fresh, profile-less database."""
    thresholds = GrowProfile.from_env()
    return GrowProfileOut(
        humidity_high_threshold=thresholds.humidity_high_threshold,
        humidity_low_threshold=thresholds.humidity_low_threshold,
        temp_fan_threshold_c=thresholds.temp_fan_threshold_c,
        temp_ac_threshold_c=thresholds.temp_ac_threshold_c,
        temp_low_threshold_c=thresholds.temp_low_threshold_c,
        soil_moisture_low_threshold=thresholds.soil_moisture_low_threshold,
        soil_moisture_hysteresis=thresholds.soil_moisture_hysteresis,
        alert_temp_c=ALERT_TEMP_C,
        grow_profile_name=GROW_PROFILE_NAME,
        tent_size_m2=TENT_SIZE_M2 or None,
        start_date=date.fromisoformat(GROW_START_DATE) if GROW_START_DATE else None,
    )


class AppState:
    """In-memory, single-process runtime state. Guarded by `lock` since
    APScheduler jobs and request handlers run on different threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode: str = "auto"
        # Overridden from the DB on startup if a dashboard save has ever
        # happened (see on_startup) - otherwise this .env-derived default
        # stands until the first POST /api/profile.
        self.grow_profile: GrowProfileOut = _default_grow_profile()
        self.commanded_relay_state = RelayState()
        self.reported_relay_state: Optional[RelayState] = None
        self.last_seen: Optional[datetime] = None
        self.latest_reading: Optional[SensorReading] = None
        self.last_manual_activity: Optional[datetime] = None
        # 0 unless the firmware is currently refusing a commanded pump-on
        # due to its own post-cap cooldown - see post_telemetry.
        self.pump_cooldown_remaining_s: float = 0.0
        # Light: independent of `mode` entirely. Either the schedule
        # decides (is_light_on, recomputed fresh every time - no stored
        # "next toggle" state) or, when the schedule is off, this manual
        # value holds until the dashboard changes it.
        self.light_schedule_enabled: bool = LIGHT_SCHEDULE_ENABLED_DEFAULT
        self.light_on_hours: int = LIGHT_DEFAULT_ON_HOURS
        self.light_commanded: bool = False
        self.light_reported: Optional[bool] = None
        # Exhaust: same independent-of-`mode` pattern as light, but a
        # repeating run/interval duty cycle (is_exhaust_on) instead of a
        # once-a-day on/off window. Never touched by decide_relay_state()
        # or any sensor reading.
        self.exhaust_schedule_enabled: bool = EXHAUST_SCHEDULE_ENABLED_DEFAULT
        self.exhaust_run_minutes: int = EXHAUST_DEFAULT_RUN_MINUTES
        self.exhaust_interval_minutes: int = EXHAUST_DEFAULT_INTERVAL_MINUTES
        self.exhaust_commanded: bool = False
        self.exhaust_reported: Optional[bool] = None
        # Home Assistant reachability, refreshed on its own schedule (see
        # scheduler._check_ha_connection) rather than per-request. None
        # until the first check completes.
        self.ha_reachable: Optional[bool] = None
        self.ha_last_checked: Optional[datetime] = None
        # Last 20 notable actions, for the dashboard's activity feed.
        self.activity_log = ActivityLog()
        # Tracks each relay's last-logged value so only actual on/off
        # transitions get recorded (auto-mode decision-engine changes,
        # manual /api/relay commands, or a light/exhaust schedule crossing
        # its on/off boundary) - never every telemetry cycle regardless of
        # whether anything changed.
        self.relay_activity = RelayActivityTracker(self.activity_log)


def _persist_activity_entry(entry) -> None:
    """Wired to app_state.activity_log.on_record below. The in-memory
    ActivityLog only ever keeps the last 20 entries for the dashboard feed;
    every entry it records - even ones it will later evict - is durably
    written here to the activity_log table, which is the complete history
    behind the "export activity log" button. Opens its own short-lived
    session rather than threading one through every call site, since this
    fires from deep inside activity_log.record() (itself often called
    while app_state.lock is held), not from a request's own DB session."""
    try:
        with Session(engine) as session:
            session.add(ActivityLogRow(timestamp=entry.timestamp, message=entry.message, actor=entry.actor))
            session.commit()
    except Exception:  # noqa: BLE001 - a failed write must never crash a request
        logger.exception("Failed to persist activity log entry")


app_state = AppState()
app_state.activity_log.on_record = _persist_activity_entry
app = FastAPI(title="Grow Tent Controller")

# Paths the ESP32 firmware itself calls - it sends no Authorization header
# at all, so these must stay reachable with no credentials.
PUBLIC_PATHS = {"/api/telemetry"}
# Safe/read-only HTTP methods a viewer role is allowed to use anywhere else.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _unauthorized(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": message},
        headers={"WWW-Authenticate": 'Basic realm="grow-tent-dashboard"'},
    )


@app.middleware("http")
async def require_auth(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return _unauthorized("Missing credentials")

    try:
        decoded = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return _unauthorized("Malformed credentials")

    user = auth.authenticate(auth.DASHBOARD_USERS, username, password)
    if user is None:
        return _unauthorized("Invalid username or password")

    if request.method not in SAFE_METHODS and user.role != "admin":
        return JSONResponse(status_code=403, content={"detail": "Viewer role cannot perform this action"})

    request.state.user = user
    return await call_next(request)


def get_session():
    with Session(engine) as session:
        yield session


def _ensure_grow_profile_start_date_column() -> None:
    """SQLModel.metadata.create_all() only creates missing tables - it never
    adds a column to one that already exists. grow_profile shipped before
    start_date existed, so an already-deployed database's table is missing
    it; without this, loading or saving the profile there would fail with
    "no such column: start_date". A fresh deploy's create_all() above
    already creates the table with every current column, so this is a
    no-op for it (PRAGMA table_info on a table that doesn't exist yet
    returns nothing)."""
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(grow_profile)")}
        if columns and "start_date" not in columns:
            conn.exec_driver_sql("ALTER TABLE grow_profile ADD COLUMN start_date DATE")
            conn.commit()


@app.on_event("startup")
def on_startup():
    os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")) or ".", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _ensure_grow_profile_start_date_column()
    # No row yet means no dashboard save has ever happened - leave
    # app_state.grow_profile at its .env-derived default rather than
    # writing one now; a DB row should only ever appear from an explicit
    # POST /api/profile.
    with Session(engine) as session:
        row = session.get(GrowProfileRow, 1)
        if row is not None:
            app_state.grow_profile = GrowProfileOut(**row.model_dump(exclude={"id"}))
    app.state.scheduler = start_scheduler(app_state, engine)


@app.on_event("shutdown")
def on_shutdown():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)


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


def _exhaust_status(now: datetime) -> ExhaustStatus:
    """Must be called with app_state.lock held. Single source of truth for
    "what should exhaust be doing right now" - mirrors _light_status()
    exactly, just with a run/interval duty cycle instead of an on_hours
    window."""
    commanded = (
        is_exhaust_on(now, app_state.exhaust_run_minutes, app_state.exhaust_interval_minutes)
        if app_state.exhaust_schedule_enabled
        else app_state.exhaust_commanded
    )
    return ExhaustStatus(
        schedule_enabled=app_state.exhaust_schedule_enabled,
        run_minutes=app_state.exhaust_run_minutes,
        interval_minutes=app_state.exhaust_interval_minutes,
        off_minutes=app_state.exhaust_interval_minutes - app_state.exhaust_run_minutes,
        commanded=commanded,
        reported=app_state.exhaust_reported,
    )


@app.post("/api/telemetry", response_model=TelemetryOut)
def post_telemetry(payload: TelemetryIn, session: Session = Depends(get_session)):
    now = datetime.utcnow()
    reading = SensorReading(
        temp_c=payload.temp_c, humidity=payload.humidity, soil_moisture=payload.soil_moisture
    )

    with app_state.lock:
        app_state.last_seen = now
        app_state.reported_relay_state = payload.relay_state
        app_state.light_reported = payload.relay_state.light
        app_state.exhaust_reported = payload.relay_state.exhaust
        app_state.latest_reading = reading
        app_state.pump_cooldown_remaining_s = payload.pump_cooldown_remaining_s

        if app_state.mode == "manual":
            commanded = app_state.commanded_relay_state
            # Manual mode's pump command is a single static value with no
            # concept of automatic re-arming - unlike auto mode's decision
            # engine, which actively re-evaluates it from soil moisture
            # every cycle, nothing here ever revisits it. If the firmware's
            # own 30s/60s safety cap just cut the pump, cancel the standing
            # "on" command rather than silently leaving it in place -
            # otherwise the firmware would honor that same stale command
            # the moment the cooldown clears, and the pump would restart on
            # its own, repeating indefinitely until someone notices and
            # turns it off. Requiring a fresh POST /api/relay to run it
            # again matches what "manual" means: nothing runs unless a
            # person asks for it right now. Auto mode is never touched by
            # this - its own re-evaluation below is unaffected.
            if payload.pump_cooldown_remaining_s > 0 and commanded.pump:
                commanded.pump = False
        else:
            de_reading = DecisionReading(
                temp_c=reading.temp_c,
                humidity=reading.humidity,
                soil_moisture=reading.soil_moisture,
            )
            commanded = decide_relay_state(
                de_reading, app_state.commanded_relay_state, app_state.grow_profile
            )

        # Light and exhaust are never touched by decide_relay_state() or
        # the auto/manual mode above - each is driven entirely by its own
        # schedule/manual switch, computed fresh every cycle.
        commanded = commanded.model_copy(
            update={
                "light": _light_status(now).commanded,
                "exhaust": _exhaust_status(now).commanded,
            }
        )

        # No Home Assistant alert/switch here - no media/speaker device is
        # connected. Instead, crossing ALERT_TEMP_C forces fan and AC on
        # directly, overriding auto/manual mode, as an early-warning
        # cooling response. Not one-way: once the reading drops back below
        # the threshold, normal mode/decision-engine logic resumes control
        # on the next cycle.
        if reading.temp_c >= app_state.grow_profile.alert_temp_c:
            commanded = commanded.model_copy(update={"fan": True, "ac": True})

        app_state.commanded_relay_state = commanded
        app_state.relay_activity.update(commanded, AUTO_ACTOR)

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

    return TelemetryOut(mode=mode, relay_state=commanded)


@app.get("/api/status", response_model=StatusOut)
def get_status():
    with app_state.lock:
        now = datetime.utcnow()
        offline = (
            app_state.last_seen is None
            or (now - app_state.last_seen).total_seconds() > OFFLINE_THRESHOLD_SECONDS
        )
        reported = app_state.reported_relay_state

        # Commanded light/exhaust state is recomputed fresh here (not read
        # from commanded_relay_state, which only updates on the ESP32's
        # own ~20s telemetry cadence) so the dashboard reflects a schedule
        # boundary the moment it's crossed, not up to a cycle late.
        commanded = app_state.commanded_relay_state.model_copy(
            update={
                "light": _light_status(now).commanded,
                "exhaust": _exhaust_status(now).commanded,
            }
        )

        return StatusOut(
            mode=app_state.mode,
            commanded_relay_state=commanded,
            reported_relay_state=reported,
            last_seen=app_state.last_seen,
            latest_reading=app_state.latest_reading,
            offline=offline,
            light=_light_status(now),
            exhaust=_exhaust_status(now),
            ha=HaStatus(reachable=app_state.ha_reachable, checked_at=app_state.ha_last_checked),
            activity=[
                ActivityEntryOut(timestamp=e.timestamp, message=e.message, actor=e.actor)
                for e in app_state.activity_log.recent()
            ],
            pump_cooldown_remaining_s=app_state.pump_cooldown_remaining_s,
        )


@app.get("/api/me")
def get_me(request: Request):
    """Who the dashboard is currently talking to - lets the frontend show a
    role badge and lock down admin-only controls for a viewer without
    guessing from response codes."""
    user = request.state.user
    return {"username": user.username, "role": user.role}


def _fmt_profile_value(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:g}"
    return str(value)


def _describe_profile_changes(old: GrowProfileOut, new: GrowProfileOut) -> str:
    """One activity-log line listing every field that actually changed,
    old->new, so a save's effect is visible without diffing two /api/profile
    responses by hand. Field order follows GrowProfileOut's declaration."""
    changes = [
        f"{field} {_fmt_profile_value(getattr(old, field))}->{_fmt_profile_value(getattr(new, field))}"
        for field in GrowProfileOut.model_fields
        if getattr(old, field) != getattr(new, field)
    ]
    return "grow profile updated: " + ", ".join(changes)


@app.get("/api/profile", response_model=GrowProfileOut)
def get_profile():
    """The active grow profile: every decide_relay_state() threshold, plus
    the purely cosmetic name/tent-size fields. .env values are only the
    first-run default - once anyone saves via POST below, the DB-backed
    value here takes over permanently, surviving a backend restart."""
    with app_state.lock:
        return app_state.grow_profile


@app.post("/api/profile", response_model=GrowProfileOut)
def set_profile(payload: GrowProfileIn, request: Request, session: Session = Depends(get_session)):
    """Admin-only, enforced by the same auth middleware as every other
    mutating route - no extra check needed here. Upserts the single
    settings row so the edit survives a restart (unlike every other piece
    of runtime state, which simply resets to its .env default), and logs
    one consolidated activity-log entry - with an old->new value for every
    field that actually changed - regardless of how many of the 10 fields
    that is, rather than one entry per field, so a single save can't flood
    the 20-entry live feed."""
    with app_state.lock:
        new_profile = GrowProfileOut(**payload.model_dump())
        if new_profile != app_state.grow_profile:
            message = _describe_profile_changes(app_state.grow_profile, new_profile)
            app_state.activity_log.record(message, request.state.user.username)
        app_state.grow_profile = new_profile

        row = session.get(GrowProfileRow, 1)
        if row is None:
            row = GrowProfileRow(id=1, **payload.model_dump())
        else:
            for field, value in payload.model_dump().items():
                setattr(row, field, value)
        session.add(row)
        session.commit()

        return app_state.grow_profile


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
def set_mode(payload: ModeIn, request: Request):
    with app_state.lock:
        if payload.mode != app_state.mode:
            app_state.activity_log.record(f"{payload.mode} mode on", request.state.user.username)
        app_state.mode = payload.mode
        app_state.last_manual_activity = datetime.utcnow()
        return {"mode": app_state.mode, "relay_state": app_state.commanded_relay_state.model_dump()}


@app.post("/api/relay")
def set_relay(payload: RelayIn, request: Request):
    with app_state.lock:
        if app_state.mode != "manual":
            raise HTTPException(status_code=409, detail="mode is not manual")
        setattr(app_state.commanded_relay_state, payload.relay, payload.state)
        app_state.relay_activity.update(app_state.commanded_relay_state, request.state.user.username)
        app_state.last_manual_activity = datetime.utcnow()
        # ac picks this up the same way fan/pump do - on the ESP32's next
        # telemetry poll (~20s) - now that it's IR-driven by the ESP32
        # itself rather than needing an immediate separate push to Home
        # Assistant (which had no poll cycle of its own to piggyback on).
        return {
            "relay": payload.relay,
            "state": payload.state,
            "commanded_relay_state": app_state.commanded_relay_state.model_dump(),
        }


@app.post("/api/light/schedule", response_model=LightStatus)
def set_light_schedule(payload: LightScheduleIn, request: Request):
    """Master switch for the light: enabling the schedule hands control to
    is_light_on() (independent of the environmental auto/manual `mode`);
    disabling it falls back to whatever was last set via
    /api/light/manual. on_hours is always saved even when the schedule is
    currently off, so it's ready as soon as it's turned on."""
    with app_state.lock:
        actor = request.state.user.username
        if payload.enabled != app_state.light_schedule_enabled:
            app_state.activity_log.record(f"light schedule {'on' if payload.enabled else 'off'}", actor)
        if payload.on_hours != app_state.light_on_hours:
            app_state.activity_log.record(f"light schedule set: {payload.on_hours}h on/day", actor)
        app_state.light_schedule_enabled = payload.enabled
        app_state.light_on_hours = payload.on_hours
        return _light_status(datetime.utcnow())


@app.post("/api/light/manual", response_model=LightStatus)
def set_light_manual(payload: LightManualIn, request: Request):
    with app_state.lock:
        if app_state.light_schedule_enabled:
            raise HTTPException(status_code=409, detail="light schedule is enabled")
        app_state.relay_activity.note("light", payload.state, request.state.user.username)
        app_state.light_commanded = payload.state
        return _light_status(datetime.utcnow())


@app.post("/api/exhaust/schedule", response_model=ExhaustStatus)
def set_exhaust_schedule(payload: ExhaustScheduleIn, request: Request):
    """Master switch for exhaust: enabling the schedule hands control to
    is_exhaust_on() (independent of the environmental auto/manual `mode`
    and of any sensor reading); disabling it falls back to whatever was
    last set via /api/exhaust/manual. run_minutes/interval_minutes are
    always saved even when the schedule is currently off, so they're
    ready as soon as it's turned on. Mirrors /api/light/schedule exactly."""
    with app_state.lock:
        actor = request.state.user.username
        if payload.enabled != app_state.exhaust_schedule_enabled:
            app_state.activity_log.record(f"exhaust schedule {'on' if payload.enabled else 'off'}", actor)
        if (
            payload.run_minutes != app_state.exhaust_run_minutes
            or payload.interval_minutes != app_state.exhaust_interval_minutes
        ):
            app_state.activity_log.record(
                f"exhaust schedule set: run {payload.run_minutes}m every {payload.interval_minutes}m", actor
            )
        app_state.exhaust_schedule_enabled = payload.enabled
        app_state.exhaust_run_minutes = payload.run_minutes
        app_state.exhaust_interval_minutes = payload.interval_minutes
        return _exhaust_status(datetime.utcnow())


@app.post("/api/exhaust/manual", response_model=ExhaustStatus)
def set_exhaust_manual(payload: ExhaustManualIn, request: Request):
    with app_state.lock:
        if app_state.exhaust_schedule_enabled:
            raise HTTPException(status_code=409, detail="exhaust schedule is enabled")
        app_state.relay_activity.note("exhaust", payload.state, request.state.user.username)
        app_state.exhaust_commanded = payload.state
        return _exhaust_status(datetime.utcnow())


@app.post("/api/export")
def trigger_export(request: Request, session: Session = Depends(get_session)):
    export_readings_to_excel(session)
    app_state.activity_log.record("data exported", request.state.user.username)
    return FileResponse(
        EXPORT_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="readings_export.xlsx",
    )


@app.post("/api/activity/export")
def trigger_activity_export(request: Request, session: Session = Depends(get_session)):
    """Exports the complete activity_log table - every entry ever recorded,
    not just the last 20 the dashboard feed shows."""
    export_activity_log_to_excel(session)
    app_state.activity_log.record("activity log exported", request.state.user.username)
    return FileResponse(
        ACTIVITY_EXPORT_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="activity_log_export.xlsx",
    )


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
