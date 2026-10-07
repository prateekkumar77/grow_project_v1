"""SQLModel tables and shared pydantic schemas used across the backend."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field as PydanticField, model_validator
from sqlmodel import Field, SQLModel


class RelayState(BaseModel):
    fan: bool = False
    # Has its own ESP32 relay like fan/pump, but is never touched by
    # decide_relay_state() or any sensor reading - it's driven entirely by
    # its own run/interval duty-cycle schedule (or manual control when
    # that schedule is off). See ExhaustStatus below.
    exhaust: bool = False
    # AC has no physical ESP32 relay - it's a Google Home device driven
    # entirely through Home Assistant (see ha_client.set_ac()). Unlike
    # exhaust, it IS part of decide_relay_state()'s humidity/temperature
    # escalation. The ESP32 never reports a real value for this field (no
    # pin to read), so `reported_relay_state.ac` is overridden with the
    # last Home-Assistant-confirmed state instead.
    ac: bool = False
    pump: bool = False
    # Grow light. Has its own ESP32 relay like fan/pump, but is never
    # touched by decide_relay_state() or the auto/manual environmental
    # mode - it's driven entirely by the light schedule (or manual light
    # control when that schedule is off). See LightStatus below.
    light: bool = False


class SensorReading(BaseModel):
    temp_c: float
    humidity: float
    soil_moisture: float


# --- API request/response schemas -------------------------------------------------


class TelemetryIn(BaseModel):
    temp_c: float
    humidity: float
    soil_moisture: float
    relay_state: RelayState
    # Seconds left before the firmware will honor a commanded pump-on
    # again, or 0 if no cooldown is active. Defaults to 0 so older
    # firmware that doesn't send this field still validates.
    pump_cooldown_remaining_s: float = 0.0


class TelemetryOut(BaseModel):
    mode: Literal["auto", "manual"]
    relay_state: RelayState


class ModeIn(BaseModel):
    mode: Literal["auto", "manual"]


class RelayIn(BaseModel):
    relay: Literal["fan", "ac", "pump"]
    state: bool


class LightScheduleIn(BaseModel):
    enabled: bool
    on_hours: int = PydanticField(ge=1, le=24)


class LightManualIn(BaseModel):
    state: bool


class LightStatus(BaseModel):
    schedule_enabled: bool
    on_hours: int
    off_hours: int
    commanded: bool
    reported: Optional[bool] = None


class ExhaustScheduleIn(BaseModel):
    enabled: bool
    run_minutes: int = PydanticField(ge=1, le=60)
    interval_minutes: int = PydanticField(ge=1, le=60)

    @model_validator(mode="after")
    def _run_within_interval(self) -> "ExhaustScheduleIn":
        if self.run_minutes > self.interval_minutes:
            raise ValueError("run_minutes cannot be greater than interval_minutes")
        return self


class ExhaustManualIn(BaseModel):
    state: bool


class ExhaustStatus(BaseModel):
    schedule_enabled: bool
    run_minutes: int
    interval_minutes: int
    off_minutes: int
    commanded: bool
    reported: Optional[bool] = None


class GrowProfileIn(BaseModel):
    humidity_high_threshold: float = PydanticField(ge=0, le=100)
    humidity_low_threshold: float = PydanticField(ge=0, le=100)
    temp_fan_threshold_c: float = PydanticField(ge=-10, le=50)
    temp_ac_threshold_c: float = PydanticField(ge=-10, le=50)
    temp_low_threshold_c: float = PydanticField(ge=-10, le=50)
    soil_moisture_low_threshold: float = PydanticField(ge=0, le=100)
    soil_moisture_hysteresis: float = PydanticField(gt=0, le=50)
    alert_temp_c: float = PydanticField(ge=-10, le=60)
    grow_profile_name: str = PydanticField(min_length=1, max_length=100)
    tent_size_m2: Optional[str] = PydanticField(default=None, max_length=50)
    # Purely cosmetic, like grow_profile_name/tent_size_m2 - the dashboard
    # derives a "day N" counter from it, but it's never read by the
    # decision engine.
    start_date: Optional[date] = None

    @model_validator(mode="after")
    def _thresholds_make_sense(self) -> "GrowProfileIn":
        if self.humidity_low_threshold >= self.humidity_high_threshold:
            raise ValueError("humidity_low_threshold must be less than humidity_high_threshold")
        if not (self.temp_low_threshold_c < self.temp_fan_threshold_c <= self.temp_ac_threshold_c):
            raise ValueError("temp_low_threshold_c must be less than temp_fan_threshold_c, which must be <= temp_ac_threshold_c")
        if self.alert_temp_c < self.temp_ac_threshold_c:
            raise ValueError("alert_temp_c must be >= temp_ac_threshold_c")
        return self


class GrowProfileOut(GrowProfileIn):
    pass


class HaStatus(BaseModel):
    # None = not checked yet (e.g. right after backend startup, before the
    # first scheduled health check completes) - distinct from a known-bad
    # False, so the dashboard can show "checking..." rather than a false
    # "unreachable".
    reachable: Optional[bool] = None
    checked_at: Optional[datetime] = None


class ActivityEntryOut(BaseModel):
    timestamp: datetime
    message: str
    # Username of whoever triggered a manual dashboard action, or "auto"
    # for anything the decision engine or a schedule did on its own.
    actor: str


class StatusOut(BaseModel):
    mode: Literal["auto", "manual"]
    commanded_relay_state: RelayState
    reported_relay_state: Optional[RelayState]
    last_seen: Optional[datetime]
    latest_reading: Optional[SensorReading]
    offline: bool
    light: LightStatus
    exhaust: ExhaustStatus
    ha: HaStatus
    # Newest first, capped at activity_log.MAX_ENTRIES - piggybacks on the
    # same 5s status poll rather than its own endpoint, same as everything
    # else the dashboard shows.
    activity: list[ActivityEntryOut]
    # 0 unless the firmware is currently refusing a commanded pump-on due to
    # its own post-cap cooldown - lets the dashboard show "cooldown" instead
    # of a generic, indefinitely-stuck-looking "pending" for the pump.
    pump_cooldown_remaining_s: float = 0.0


# --- persistence --------------------------------------------------------------------


class ReadingRow(SQLModel, table=True):
    """One row per telemetry POST. SQLite is the source of truth; the Excel
    export is a derived artifact regenerated from this table on a schedule."""

    __tablename__ = "readings"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    temp_c: float
    humidity: float
    soil_moisture: float
    # Pulled out of reported_relay_state as its own column so it can be
    # queried/exported without parsing JSON. This is the ESP32's actual
    # reported state (physical truth), not the commanded one - matches
    # how the dashboard treats "reported" as ground truth elsewhere.
    light_state: bool
    reported_relay_state: str  # JSON: {"fan": bool, "exhaust": bool, "ac": bool, "pump": bool, "light": bool}
    commanded_relay_state: str  # JSON: same shape
    mode: str


class ActivityLogRow(SQLModel, table=True):
    """Durable, unbounded history of every activity-log entry - the
    in-memory ActivityLog (activity_log.py) only ever keeps the most
    recent 20 for the dashboard feed; this table is the complete record
    behind the "export activity log" button."""

    __tablename__ = "activity_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    message: str
    actor: str


class GrowProfileRow(SQLModel, table=True):
    """Singleton settings row: the dashboard-saved grow profile, overriding
    the .env defaults once a user has saved any edit. Always upserted at a
    fixed id=1 - there is exactly one active profile, never a history of
    them. No row exists until the first POST /api/profile; until then,
    AppState.grow_profile just holds the in-memory .env-derived default."""

    __tablename__ = "grow_profile"

    id: int = Field(default=1, primary_key=True)
    humidity_high_threshold: float
    humidity_low_threshold: float
    temp_fan_threshold_c: float
    temp_ac_threshold_c: float
    temp_low_threshold_c: float
    soil_moisture_low_threshold: float
    soil_moisture_hysteresis: float
    alert_temp_c: float
    grow_profile_name: str
    tent_size_m2: Optional[str] = None
    start_date: Optional[date] = None
