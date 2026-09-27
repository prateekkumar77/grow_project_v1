from decision_engine import Reading, decide_relay_state
from models import RelayState


def make_reading(temp_c, humidity, soil_moisture):
    return Reading(temp_c=temp_c, humidity=humidity, soil_moisture=soil_moisture)


def test_stable_readings_change_nothing():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result == RelayState(fan=False, ac=False, pump=False)


def test_moderate_temp_triggers_fan_before_ac():
    previous = RelayState(fan=False, ac=False, pump=False)
    # 26.5C: within the 26-28C "fan alone" band (default thresholds).
    reading = make_reading(temp_c=26.5, humidity=50, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result.fan is True
    assert result.ac is False


def test_high_temp_escalates_to_ac():
    previous = RelayState(fan=False, ac=False, pump=False)
    # 28C: at/above the AC threshold.
    reading = make_reading(temp_c=28.0, humidity=50, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result.ac is True


def test_low_temp_turns_ac_off_and_fan_on():
    previous = RelayState(fan=False, ac=True, pump=False)
    # 18C: at/below the low-temp threshold.
    reading = make_reading(temp_c=18.0, humidity=50, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result.ac is False
    assert result.fan is True


def test_low_soil_moisture_triggers_pump():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=20)

    result = decide_relay_state(reading, previous)

    assert result.pump is True


def test_soil_moisture_above_hysteresis_band_turns_pump_off():
    previous = RelayState(fan=False, ac=False, pump=True)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=80)

    result = decide_relay_state(reading, previous)

    assert result.pump is False


def test_low_humidity_turns_ac_off_and_fan_on():
    previous = RelayState(fan=False, ac=True, pump=False)
    reading = make_reading(temp_c=24.0, humidity=25, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result.ac is False
    assert result.fan is True


def test_high_humidity_turns_ac_on():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=70, soil_moisture=60)

    result = decide_relay_state(reading, previous)

    assert result.ac is True
