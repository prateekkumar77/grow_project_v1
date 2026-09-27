from decision_engine import Reading, decide_relay_state
from models import RelayState


def make_reading(temp_c, humidity, soil_moisture, baseline_temp_c=None, baseline_humidity=None):
    return Reading(
        temp_c=temp_c,
        humidity=humidity,
        soil_moisture=soil_moisture,
        baseline_temp_c=baseline_temp_c if baseline_temp_c is not None else temp_c,
        baseline_humidity=baseline_humidity if baseline_humidity is not None else humidity,
    )


def test_stable_readings_change_nothing():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=60, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result == RelayState(fan=False, ac=False, pump=False)


def test_moderate_temp_rise_triggers_fan_before_ac():
    previous = RelayState(fan=False, ac=False, pump=False)
    # 2.5C above baseline: within the 2-3C "fan alone" band.
    reading = make_reading(temp_c=26.5, humidity=50, soil_moisture=60, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.fan is True
    assert result.ac is False


def test_sustained_temp_rise_escalates_to_ac():
    previous = RelayState(fan=False, ac=False, pump=False)
    # 4C above baseline: beyond the fan-only band, should escalate to AC.
    reading = make_reading(temp_c=28.0, humidity=50, soil_moisture=60, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.ac is True


def test_low_soil_moisture_triggers_pump():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=20, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.pump is True


def test_soil_moisture_above_hysteresis_band_turns_pump_off():
    previous = RelayState(fan=False, ac=False, pump=True)
    reading = make_reading(temp_c=24.0, humidity=50, soil_moisture=80, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.pump is False


def test_low_humidity_turns_ac_off_and_fan_on():
    previous = RelayState(fan=False, ac=True, pump=False)
    reading = make_reading(temp_c=24.0, humidity=25, soil_moisture=60, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.ac is False
    assert result.fan is True


def test_rising_humidity_turns_ac_on():
    previous = RelayState(fan=False, ac=False, pump=False)
    reading = make_reading(temp_c=24.0, humidity=70, soil_moisture=60, baseline_temp_c=24.0)

    result = decide_relay_state(reading, previous)

    assert result.ac is True
