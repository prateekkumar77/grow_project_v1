"""Pure light-schedule logic: current time -> on/off.

Deliberately separate from decision_engine.py - the light is never part of
the environmental auto/manual mode. It has exactly two states of its own:
"schedule" (this function decides) or "manual" (whatever was last
commanded from the dashboard holds). The caller in main.py picks which one
applies; this module only computes the schedule side.
"""
from datetime import datetime, time


def is_light_on(now_local: datetime, on_time: time, off_time: time) -> bool:
    """True if `now_local` falls within the daily on window [on_time,
    off_time). `now_local` is wall-clock time in the schedule timezone
    (main.py's _schedule_now()). If off_time is earlier than on_time the
    window wraps past midnight (e.g. on 18:00, off 06:00). on_time ==
    off_time is rejected by LightScheduleIn, since it's ambiguous between
    always-on and always-off.

    A pure function of wall-clock time (no stored "next toggle" state), so
    it's correct immediately after a backend restart and needs no scheduler
    job - every /api/telemetry cycle just recomputes it.
    """
    now = now_local.time()
    if on_time < off_time:
        return on_time <= now < off_time
    return now >= on_time or now < off_time


def on_hours(on_time: time, off_time: time) -> float:
    """Length of the daily on window in hours (for the history tab's pie
    chart), accounting for a window that wraps past midnight."""
    on_min = on_time.hour * 60 + on_time.minute
    off_min = off_time.hour * 60 + off_time.minute
    return ((off_min - on_min) % (24 * 60)) / 60
