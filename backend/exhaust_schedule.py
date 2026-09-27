"""Pure exhaust-schedule logic: current time -> on/off.

Deliberately separate from decision_engine.py - the exhaust fan is never
part of the environmental auto/manual mode or any sensor-driven decision.
It has exactly two states of its own: "schedule" (this function decides,
a repeating run/pause duty cycle) or "manual" (whatever was last
commanded from the dashboard holds). The caller in main.py picks which
one applies; this module only computes the schedule side.
"""
from datetime import datetime


def is_exhaust_on(now_utc: datetime, run_minutes: int, interval_minutes: int) -> bool:
    """True if `now_utc` falls within the exhaust's ON portion of its duty
    cycle: on for the first `run_minutes` of every `interval_minutes`
    window, off for the rest, repeating continuously.

    Anchored to UTC midnight, not to whenever the schedule was enabled -
    a pure function of wall-clock time (not stored "next toggle" state),
    so it's correct immediately after a backend restart with no recovery
    logic needed, and needs no scheduler job of its own: every
    /api/telemetry cycle just recomputes it.
    """
    minutes_since_midnight = now_utc.hour * 60 + now_utc.minute + now_utc.second / 60
    phase = minutes_since_midnight % interval_minutes
    return phase < run_minutes
