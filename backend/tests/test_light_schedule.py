from datetime import datetime, time

from light_schedule import is_light_on, on_hours

DAY = (time(6, 0), time(22, 0))
NIGHT = (time(18, 0), time(6, 0))


def at(hour, minute=0, second=0):
    return datetime(2026, 1, 1, hour, minute, second)


def test_same_day_window_inside():
    assert is_light_on(at(12), *DAY) is True


def test_same_day_window_on_at_start_off_at_end():
    assert is_light_on(at(6, 0), *DAY) is True
    assert is_light_on(at(21, 59, 59), *DAY) is True
    assert is_light_on(at(22, 0), *DAY) is False


def test_same_day_window_outside():
    assert is_light_on(at(5, 59), *DAY) is False
    assert is_light_on(at(23, 30), *DAY) is False


def test_window_wrapping_past_midnight():
    assert is_light_on(at(18, 0), *NIGHT) is True
    assert is_light_on(at(23, 59), *NIGHT) is True
    assert is_light_on(at(0, 0), *NIGHT) is True
    assert is_light_on(at(5, 59, 59), *NIGHT) is True
    assert is_light_on(at(6, 0), *NIGHT) is False
    assert is_light_on(at(12, 0), *NIGHT) is False


def test_off_at_midnight():
    assert is_light_on(at(23, 59, 59), time(6, 0), time(0, 0)) is True
    assert is_light_on(at(0, 0), time(6, 0), time(0, 0)) is False


def test_on_hours():
    assert on_hours(*DAY) == 16
    assert on_hours(*NIGHT) == 12
    assert on_hours(time(6, 0), time(0, 0)) == 18
    assert on_hours(time(6, 30), time(7, 0)) == 0.5
