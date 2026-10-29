"""Pure pump-schedule logic: current time -> which run slot we're in.

The pump is never part of the environmental auto/manual mode. It's either
on this schedule (a short run every `interval_hours`) or manual (one-off
runs from the dashboard). Runs are timed by the firmware itself - see the
pump_run request in main.py's post_telemetry - so this module only decides
*when* a run is due, not how long it lasts.
"""
from datetime import datetime, timedelta

# Every allowed interval divides 24, so slots line up with midnight every day.
INTERVAL_HOURS_OPTIONS = (1, 2, 3, 4, 6, 8, 12, 24)


def slot_start(now_local: datetime, interval_hours: int) -> datetime:
    """Start of the interval window `now_local` falls in, anchored to
    midnight in the schedule timezone - e.g. every 12h gives slots at 00:00
    and 12:00. A run is due once per slot: when the slot changes from the
    last one a run was requested for."""
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(hours=(now_local.hour // interval_hours) * interval_hours)


def next_run_at(now_local: datetime, interval_hours: int) -> datetime:
    """When the next scheduled run is due (start of the next slot)."""
    return slot_start(now_local, interval_hours) + timedelta(hours=interval_hours)
