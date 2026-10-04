"""Pure decision logic: sensor reading -> relay command.

No I/O happens in decide_relay_state itself - every threshold it compares
against comes from a `GrowProfile` passed in by the caller, never computed
from history. When mode == "manual" the caller should not call this
function at all - it should just keep using the last dashboard-commanded
state, per the brief ("this function is not consulted for relay state").
"""
import os
from dataclasses import dataclass

from models import RelayState


@dataclass
class GrowProfile:
    """Grow-profile thresholds consumed by decide_relay_state(). `from_env()`
    gives the historical env-var defaults; the backend overlays any
    dashboard-saved values on top at runtime (see main.py's AppState)."""

    humidity_high_threshold: float
    humidity_low_threshold: float
    temp_fan_threshold_c: float
    temp_ac_threshold_c: float
    temp_low_threshold_c: float
    soil_moisture_low_threshold: float
    # Pump switches back off only once soil moisture clears the low
    # threshold by this margin, to avoid rapidly flapping on/off right at
    # the boundary.
    soil_moisture_hysteresis: float

    @classmethod
    def from_env(cls) -> "GrowProfile":
        return cls(
            humidity_high_threshold=float(os.getenv("HUMIDITY_HIGH_THRESHOLD", "65")),
            humidity_low_threshold=float(os.getenv("HUMIDITY_LOW_THRESHOLD", "40")),
            temp_fan_threshold_c=float(os.getenv("TEMP_FAN_THRESHOLD_C", "26.0")),
            temp_ac_threshold_c=float(os.getenv("TEMP_AC_THRESHOLD_C", "28.0")),
            temp_low_threshold_c=float(os.getenv("TEMP_LOW_THRESHOLD_C", "18.0")),
            soil_moisture_low_threshold=float(os.getenv("SOIL_MOISTURE_LOW_THRESHOLD", "35")),
            soil_moisture_hysteresis=float(os.getenv("SOIL_MOISTURE_HYSTERESIS", "5")),
        )


@dataclass
class Reading:
    temp_c: float
    humidity: float
    soil_moisture: float


def decide_relay_state(reading: Reading, previous_state: RelayState, profile: GrowProfile) -> RelayState:
    fan = previous_state.fan
    ac = previous_state.ac
    pump = previous_state.pump

    # --- humidity ------------------------------------------------------------
    if reading.humidity >= profile.humidity_high_threshold:
        # High humidity -> AC brings it down.
        ac = True
    elif reading.humidity <= profile.humidity_low_threshold:
        # Unusually low humidity (rare) -> AC off, fan pulls in (more humid)
        # room air instead.
        ac = False
        fan = True

    # --- temperature -----------------------------------------------------------
    if reading.temp_c >= profile.temp_ac_threshold_c:
        # Hot enough to need active cooling -> AC (lowers temp and humidity
        # together).
        ac = True
    elif reading.temp_c >= profile.temp_fan_threshold_c:
        # Moderately warm -> fan alone first, not AC.
        fan = True
    elif reading.temp_c <= profile.temp_low_threshold_c:
        # Unusually cold -> AC off (no point cooling further), fan pulls in
        # comparatively warmer room air instead.
        ac = False
        fan = True

    # --- soil moisture / pump ---------------------------------------------------
    if reading.soil_moisture <= profile.soil_moisture_low_threshold:
        pump = True
    elif reading.soil_moisture >= profile.soil_moisture_low_threshold + profile.soil_moisture_hysteresis:
        pump = False
    # else: within the hysteresis band - hold whatever the pump was doing.

    # Exhaust is never touched here - it's driven entirely by its own
    # run/interval duty-cycle schedule (see exhaust_schedule.py), same as
    # light is driven by its own schedule. The caller overwrites it after
    # this call, same pattern as light.
    return RelayState(fan=fan, ac=ac, pump=pump)
