"""Pure light-schedule logic: current time -> on/off.

Deliberately separate from decision_engine.py - the light is never part of
the environmental auto/manual mode. It has exactly two states of its own:
"schedule" (this function decides) or "manual" (whatever was last
commanded from the dashboard holds). The caller in main.py picks which one
applies; this module only computes the schedule side.
"""
from datetime import datetime


def is_light_on(now_utc: datetime, on_hours: int) -> bool:
    """True if `now_utc` falls within the light's ON window.

    The cycle is anchored to UTC midnight every day, not to whenever the
    schedule was enabled: light is ON from 00:00 UTC for `on_hours` hours,
    then OFF for the rest of the day. Being a pure function of wall-clock
    time (not stored "next toggle" state) it's correct immediately after a
    backend restart with no recovery logic needed, and needs no scheduler
    job - every /api/telemetry cycle just recomputes it.

    `on_hours` of 24 means always on; there's no "off_hours" input because
    off_hours is always `24 - on_hours` by construction.
    """
    hour_of_day = now_utc.hour + now_utc.minute / 60 + now_utc.second / 3600
    return hour_of_day < on_hours
