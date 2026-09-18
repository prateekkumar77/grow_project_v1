"""SQLModel tables and shared pydantic schemas used across the backend."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Field, SQLModel


class RelayState(BaseModel):
    fan: bool = False
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


class HaStatus(BaseModel):
    # None = not checked yet (e.g. right after backend startup, before the
    # first scheduled health check completes) - distinct from a known-bad
    # False, so the dashboard can show "checking..." rather than a false
    # "unreachable".
    reachable: Optional[bool] = None
    checked_at: Optional[datetime] = None


class StatusOut(BaseModel):
    mode: Literal["auto", "manual"]
    commanded_relay_state: RelayState
    reported_relay_state: Optional[RelayState]
    last_seen: Optional[datetime]
    latest_reading: Optional[SensorReading]
    offline: bool
    light: LightStatus
    ha: HaStatus


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
    reported_relay_state: str  # JSON: {"fan": bool, "ac": bool, "pump": bool, "light": bool}
    commanded_relay_state: str  # JSON: same shape
    mode: str
