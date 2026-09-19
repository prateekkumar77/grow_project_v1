from datetime import datetime

from chart_data import bucket_by_step

WEEK_MINUTES = 7 * 24 * 60


def test_step_buckets_average_readings_within_window():
    day_start = datetime(2026, 1, 1)
    readings = [
        (datetime(2026, 1, 1, 0, 10), 20.0, 50.0, 40.0),
        (datetime(2026, 1, 1, 0, 40), 22.0, 52.0, 42.0),
    ]
    result = bucket_by_step(readings, day_start, step_minutes=60)

    assert len(result) == 24
    ts, point = result[0]
    assert ts == day_start
    assert point.temp_c == 21.0
    assert point.humidity == 51.0
    assert point.soil_moisture == 41.0


def test_step_buckets_empty_bucket_is_none_not_zero():
    day_start = datetime(2026, 1, 1)
    readings = [(datetime(2026, 1, 1, 0, 10), 20.0, 50.0, 40.0)]
    result = bucket_by_step(readings, day_start, step_minutes=60)

    _, hour0 = result[0]
    _, hour1 = result[1]
    assert hour0.temp_c == 20.0
    assert hour1.temp_c is None
    assert hour1.humidity is None
    assert hour1.soil_moisture is None


def test_step_buckets_30min_gives_48_buckets():
    day_start = datetime(2026, 1, 1)
    result = bucket_by_step([], day_start, step_minutes=30)
    assert len(result) == 48
    assert result[1][0] == datetime(2026, 1, 1, 0, 30)


def test_step_buckets_ignore_readings_outside_window():
    day_start = datetime(2026, 1, 1)
    readings = [
        (datetime(2025, 12, 31, 23, 0), 99.0, 99.0, 99.0),  # before window
        (datetime(2026, 1, 2, 0, 0), 99.0, 99.0, 99.0),  # after window
        (datetime(2026, 1, 1, 12, 0), 25.0, 60.0, 45.0),
    ]
    result = bucket_by_step(readings, day_start, step_minutes=60)
    noon = result[12][1]
    assert noon.temp_c == 25.0
    # nothing else should have picked up the out-of-window readings
    others = [p for i, (_, p) in enumerate(result) if i != 12]
    assert all(o.temp_c is None for o in others)


def test_week_buckets_give_28_points_4_per_day():
    week_start = datetime(2026, 1, 5)  # a Monday
    result = bucket_by_step([], week_start, step_minutes=360, window_minutes=WEEK_MINUTES)
    assert len(result) == 28
    # aligned to day boundaries: index 4 is the start of day 2 (Tuesday 00:00)
    assert result[0][0] == datetime(2026, 1, 5, 0, 0)
    assert result[1][0] == datetime(2026, 1, 5, 6, 0)
    assert result[4][0] == datetime(2026, 1, 6, 0, 0)


def test_week_buckets_average_within_each_6h_quarter():
    week_start = datetime(2026, 1, 5)
    readings = [
        (datetime(2026, 1, 5, 1, 0), 20.0, 50.0, 40.0),  # Monday, quarter 0 (00-06)
        (datetime(2026, 1, 5, 3, 0), 24.0, 54.0, 44.0),  # Monday, quarter 0 (00-06)
        (datetime(2026, 1, 5, 7, 0), 30.0, 70.0, 60.0),  # Monday, quarter 1 (06-12)
        (datetime(2026, 1, 6, 1, 0), 18.0, 40.0, 30.0),  # Tuesday, quarter 0
    ]
    result = bucket_by_step(readings, week_start, step_minutes=360, window_minutes=WEEK_MINUTES)

    mon_q0 = result[0][1]
    mon_q1 = result[1][1]
    tue_q0 = result[4][1]
    assert mon_q0.temp_c == 22.0
    assert mon_q0.humidity == 52.0
    assert mon_q1.temp_c == 30.0
    assert tue_q0.temp_c == 18.0


def test_week_buckets_no_data_quarter_is_none():
    week_start = datetime(2026, 1, 5)
    result = bucket_by_step([], week_start, step_minutes=360, window_minutes=WEEK_MINUTES)
    assert all(p.temp_c is None for _, p in result)


def test_week_buckets_ignore_readings_outside_window():
    week_start = datetime(2026, 1, 5)
    readings = [
        (datetime(2026, 1, 4, 23, 0), 99.0, 99.0, 99.0),  # before the week
        (datetime(2026, 1, 12, 0, 0), 99.0, 99.0, 99.0),  # after the week
        (datetime(2026, 1, 5, 13, 0), 25.0, 60.0, 45.0),  # Monday, quarter 2 (12-18)
    ]
    result = bucket_by_step(readings, week_start, step_minutes=360, window_minutes=WEEK_MINUTES)
    q2 = result[2][1]
    assert q2.temp_c == 25.0
    others = [p for i, (_, p) in enumerate(result) if i != 2]
    assert all(o.temp_c is None for o in others)
