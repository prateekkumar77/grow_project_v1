from datetime import datetime

from pump_schedule import next_run_at, slot_start


def test_twelve_hour_slots():
    assert slot_start(datetime(2026, 1, 1, 0, 0), 12) == datetime(2026, 1, 1, 0, 0)
    assert slot_start(datetime(2026, 1, 1, 11, 59, 59), 12) == datetime(2026, 1, 1, 0, 0)
    assert slot_start(datetime(2026, 1, 1, 12, 0), 12) == datetime(2026, 1, 1, 12, 0)
    assert slot_start(datetime(2026, 1, 1, 23, 30), 12) == datetime(2026, 1, 1, 12, 0)


def test_daily_slot():
    assert slot_start(datetime(2026, 1, 1, 17, 45), 24) == datetime(2026, 1, 1, 0, 0)


def test_hourly_slot():
    assert slot_start(datetime(2026, 1, 1, 7, 59), 1) == datetime(2026, 1, 1, 7, 0)


def test_next_run_crosses_midnight():
    assert next_run_at(datetime(2026, 1, 1, 13, 0), 12) == datetime(2026, 1, 2, 0, 0)
    assert next_run_at(datetime(2026, 1, 1, 1, 0), 24) == datetime(2026, 1, 2, 0, 0)


def test_next_run_same_day():
    assert next_run_at(datetime(2026, 1, 1, 5, 0), 8) == datetime(2026, 1, 1, 8, 0)
