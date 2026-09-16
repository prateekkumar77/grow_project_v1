"""SQLModel tables and shared pydantic schemas used across the backend."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class RelayState(BaseModel):
    fan: bool = False
    ac: bool = False
    pump: bool = False


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


class StatusOut(BaseModel):
    mode: Literal["auto", "manual"]
    commanded_relay_state: RelayState
    reported_relay_state: Optional[RelayState]
    last_seen: Optional[datetime]
    latest_reading: Optional[SensorReading]
    offline: bool


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
    reported_relay_state: str  # JSON: {"fan": bool, "ac": bool, "pump": bool}
    commanded_relay_state: str  # JSON: same shape
    mode: str
