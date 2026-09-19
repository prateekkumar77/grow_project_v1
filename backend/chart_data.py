"""Pure aggregation logic for the dashboard's history charts.

Deliberately decoupled from SQLModel/the database - takes plain
(timestamp, temp_c, humidity, soil_moisture) tuples so it's testable
without a DB. A single fixed-step bucketing function serves both the day
view (24h window, 30/60min buckets) and the week view (7-day window,
6-hour buckets - 4 points/day), since they're the same operation at a
different window/step size.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

Reading = Tuple[datetime, float, float, float]


@dataclass
class ChartPoint:
    temp_c: Optional[float]
    humidity: Optional[float]
    soil_moisture: Optional[float]


def _average_buckets(
    readings: Sequence[Reading],
    bucket_count: int,
    bucket_index_fn,
) -> List[ChartPoint]:
    sums = [[0.0, 0.0, 0.0, 0] for _ in range(bucket_count)]

    for ts, temp_c, humidity, soil_moisture in readings:
        idx = bucket_index_fn(ts)
        if 0 <= idx < bucket_count:
            s = sums[idx]
            s[0] += temp_c
            s[1] += humidity
            s[2] += soil_moisture
            s[3] += 1

    points = []
    for t_sum, h_sum, s_sum, n in sums:
        if n:
            points.append(ChartPoint(temp_c=t_sum / n, humidity=h_sum / n, soil_moisture=s_sum / n))
        else:
            # No readings in this bucket - a genuine gap, not zero. Averaging
            # in a zero would silently fabricate a reading that never
            # happened (e.g. a dropped-offline stretch showing as 0°C).
            points.append(ChartPoint(temp_c=None, humidity=None, soil_moisture=None))
    return points


def bucket_by_step(
    readings: Sequence[Reading],
    window_start: datetime,
    step_minutes: int,
    window_minutes: int = 24 * 60,
) -> List[Tuple[datetime, ChartPoint]]:
    """Averages readings in [window_start, window_start + window_minutes)
    into fixed step_minutes-wide buckets.

    Used for both:
    - the "daily readings" chart: window_minutes=1440 (default, 24h),
      step_minutes=30 or 60.
    - the "weekly averages" chart: window_minutes=10080 (7 days),
      step_minutes=360 (6h) - 4 buckets/day, aligned to day boundaries
      since 1440 is an exact multiple of 360.
    """
    bucket_count = window_minutes // step_minutes

    def bucket_index(ts: datetime) -> int:
        minutes = (ts - window_start).total_seconds() / 60
        return int(minutes // step_minutes)

    points = _average_buckets(readings, bucket_count, bucket_index)
    return [(window_start + timedelta(minutes=i * step_minutes), p) for i, p in enumerate(points)]
