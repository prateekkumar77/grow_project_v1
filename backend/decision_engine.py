"""Pure decision logic: sensor reading -> relay command.

No I/O happens in decide_relay_state itself. The caller (main.py) is
responsible for computing a rolling baseline temp/humidity from history and
handing it in as part of `Reading`, and for persisting/transmitting the
result. When mode == "manual" the caller should not call this function at
all - it should just keep using the last dashboard-commanded state, per the
brief ("this function is not consulted for relay state").
"""
import os
from dataclasses import dataclass

from models import RelayState

# --- thresholds (env-configurable, never inline magic numbers below) --------------

HUMIDITY_HIGH_THRESHOLD = float(os.getenv("HUMIDITY_HIGH_THRESHOLD", "65"))
HUMIDITY_LOW_THRESHOLD = float(os.getenv("HUMIDITY_LOW_THRESHOLD", "40"))

TEMP_RISE_FAN_THRESHOLD_C = float(os.getenv("TEMP_RISE_FAN_THRESHOLD_C", "2.0"))
TEMP_RISE_AC_THRESHOLD_C = float(os.getenv("TEMP_RISE_AC_THRESHOLD_C", "3.0"))

SOIL_MOISTURE_LOW_THRESHOLD = float(os.getenv("SOIL_MOISTURE_LOW_THRESHOLD", "35"))
# Pump switches back off only once soil moisture clears the low threshold by
# this margin, to avoid rapidly flapping on/off right at the boundary.
SOIL_MOISTURE_HYSTERESIS = float(os.getenv("SOIL_MOISTURE_HYSTERESIS", "5"))


@dataclass
class Reading:
    temp_c: float
    humidity: float
    soil_moisture: float
    baseline_temp_c: float
    baseline_humidity: float


def decide_relay_state(reading: Reading, previous_state: RelayState) -> RelayState:
    fan = previous_state.fan
    ac = previous_state.ac
    pump = previous_state.pump

    temp_delta = reading.temp_c - reading.baseline_temp_c

    # --- humidity ------------------------------------------------------------
    if reading.humidity >= HUMIDITY_HIGH_THRESHOLD:
        # Rising humidity -> AC brings it down.
        ac = True
    elif reading.humidity <= HUMIDITY_LOW_THRESHOLD:
        # Unusually low humidity (rare) -> AC off, fan pulls in (more humid)
        # room air instead.
        ac = False
        fan = True

    # --- temperature -----------------------------------------------------------
    if temp_delta >= TEMP_RISE_AC_THRESHOLD_C:
        # Larger/sustained rise -> escalate to AC (lowers temp and humidity
        # together).
        ac = True
    elif temp_delta >= TEMP_RISE_FAN_THRESHOLD_C:
        # Moderate rise -> fan alone first, not AC.
        fan = True

    # --- soil moisture / pump ---------------------------------------------------
    if reading.soil_moisture <= SOIL_MOISTURE_LOW_THRESHOLD:
        pump = True
    elif reading.soil_moisture >= SOIL_MOISTURE_LOW_THRESHOLD + SOIL_MOISTURE_HYSTERESIS:
        pump = False
    # else: within the hysteresis band - hold whatever the pump was doing.

    return RelayState(fan=fan, ac=ac, pump=pump)
