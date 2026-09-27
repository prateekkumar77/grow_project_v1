"""Pure decision logic: sensor reading -> relay command.

No I/O happens in decide_relay_state itself - every threshold it compares
against is a fixed, env-configurable "grow profile" value, never computed
from history. When mode == "manual" the caller should not call this
function at all - it should just keep using the last dashboard-commanded
state, per the brief ("this function is not consulted for relay state").
"""
import os
from dataclasses import dataclass

from models import RelayState

# --- thresholds (env-configurable, never inline magic numbers below) --------------

HUMIDITY_HIGH_THRESHOLD = float(os.getenv("HUMIDITY_HIGH_THRESHOLD", "65"))
HUMIDITY_LOW_THRESHOLD = float(os.getenv("HUMIDITY_LOW_THRESHOLD", "40"))

TEMP_FAN_THRESHOLD_C = float(os.getenv("TEMP_FAN_THRESHOLD_C", "26.0"))
TEMP_AC_THRESHOLD_C = float(os.getenv("TEMP_AC_THRESHOLD_C", "28.0"))
TEMP_LOW_THRESHOLD_C = float(os.getenv("TEMP_LOW_THRESHOLD_C", "18.0"))

SOIL_MOISTURE_LOW_THRESHOLD = float(os.getenv("SOIL_MOISTURE_LOW_THRESHOLD", "35"))
# Pump switches back off only once soil moisture clears the low threshold by
# this margin, to avoid rapidly flapping on/off right at the boundary.
SOIL_MOISTURE_HYSTERESIS = float(os.getenv("SOIL_MOISTURE_HYSTERESIS", "5"))


@dataclass
class Reading:
    temp_c: float
    humidity: float
    soil_moisture: float


def decide_relay_state(reading: Reading, previous_state: RelayState) -> RelayState:
    fan = previous_state.fan
    ac = previous_state.ac
    pump = previous_state.pump

    # --- humidity ------------------------------------------------------------
    if reading.humidity >= HUMIDITY_HIGH_THRESHOLD:
        # High humidity -> AC brings it down.
        ac = True
    elif reading.humidity <= HUMIDITY_LOW_THRESHOLD:
        # Unusually low humidity (rare) -> AC off, fan pulls in (more humid)
        # room air instead.
        ac = False
        fan = True

    # --- temperature -----------------------------------------------------------
    if reading.temp_c >= TEMP_AC_THRESHOLD_C:
        # Hot enough to need active cooling -> AC (lowers temp and humidity
        # together).
        ac = True
    elif reading.temp_c >= TEMP_FAN_THRESHOLD_C:
        # Moderately warm -> fan alone first, not AC.
        fan = True
    elif reading.temp_c <= TEMP_LOW_THRESHOLD_C:
        # Unusually cold -> AC off (no point cooling further), fan pulls in
        # comparatively warmer room air instead.
        ac = False
        fan = True

    # --- soil moisture / pump ---------------------------------------------------
    if reading.soil_moisture <= SOIL_MOISTURE_LOW_THRESHOLD:
        pump = True
    elif reading.soil_moisture >= SOIL_MOISTURE_LOW_THRESHOLD + SOIL_MOISTURE_HYSTERESIS:
        pump = False
    # else: within the hysteresis band - hold whatever the pump was doing.

    # Exhaust is never touched here - it's driven entirely by its own
    # run/interval duty-cycle schedule (see exhaust_schedule.py), same as
    # light is driven by its own schedule. The caller overwrites it after
    # this call, same pattern as light.
    return RelayState(fan=fan, ac=ac, pump=pump)
