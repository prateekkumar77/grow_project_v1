from datetime import datetime

from exhaust_schedule import is_exhaust_on


def test_within_run_window():
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 0, 30), run_minutes=1, interval_minutes=5) is True


def test_at_boundary_still_on_just_before():
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 0, 59), run_minutes=1, interval_minutes=5) is True


def test_after_run_window_is_off():
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 1, 0), run_minutes=1, interval_minutes=5) is False


def test_cycle_restarts_at_next_interval():
    # 5 minutes in: start of the second cycle -> on again.
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 5, 0), run_minutes=1, interval_minutes=5) is True
    # 6 minutes in: 1 minute into the second cycle, past its run window -> off.
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 6, 0), run_minutes=1, interval_minutes=5) is False


def test_always_on_when_run_equals_interval():
    assert is_exhaust_on(datetime(2026, 1, 1, 12, 34, 56), run_minutes=10, interval_minutes=10) is True


def test_minimal_one_minute_cycle_is_always_on():
    assert is_exhaust_on(datetime(2026, 1, 1, 0, 0, 30), run_minutes=1, interval_minutes=1) is True
