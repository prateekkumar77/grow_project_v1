from datetime import datetime

from light_schedule import is_light_on


def test_within_on_window():
    assert is_light_on(datetime(2026, 1, 1, 5, 0), on_hours=18) is True


def test_at_boundary_still_on_just_before():
    assert is_light_on(datetime(2026, 1, 1, 17, 59, 59), on_hours=18) is True


def test_after_on_window_is_off():
    assert is_light_on(datetime(2026, 1, 1, 18, 0, 0), on_hours=18) is False


def test_late_night_is_off():
    assert is_light_on(datetime(2026, 1, 1, 23, 30), on_hours=18) is False


def test_always_on_when_on_hours_is_24():
    assert is_light_on(datetime(2026, 1, 1, 23, 59, 59), on_hours=24) is True


def test_minimal_one_hour_window():
    assert is_light_on(datetime(2026, 1, 1, 0, 30), on_hours=1) is True
    assert is_light_on(datetime(2026, 1, 1, 1, 30), on_hours=1) is False
