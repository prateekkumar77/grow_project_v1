"""Pure exhaust logic: current time -> on/off, and which source drives it.

Deliberately separate from decision_engine.py - the exhaust is never part
of a sensor-driven decision itself. Its commanded state comes from one of
three sources, in priority order (the caller in main.py applies them):

1. "schedule" enabled: is_exhaust_on() decides, a repeating run/pause duty
   cycle, regardless of auto/manual mode.
2. Schedule off, auto mode: exhaust mirrors the final commanded AC state -
   on whenever AC is on, off whenever AC is off (see exhaust_follows_ac()).
3. Schedule off, manual mode: whatever was last commanded from the
   dashboard's exhaust switch holds.
"""
from datetime import datetime


def is_exhaust_on(now_local: datetime, run_minutes: int, interval_minutes: int) -> bool:
    """True if `now_local` falls within the exhaust's ON portion of its duty
    cycle: on for the first `run_minutes` of every `interval_minutes`
    window, off for the rest, repeating continuously.

    Anchored to midnight in the schedule timezone (`now_local` is
    main.py's _schedule_now()), not to whenever the schedule was enabled -
    a pure function of wall-clock time (not stored "next toggle" state),
    so it's correct immediately after a backend restart with no recovery
    logic needed, and needs no scheduler job of its own: every
    /api/telemetry cycle just recomputes it.
    """
    minutes_since_midnight = now_local.hour * 60 + now_local.minute + now_local.second / 60
    phase = minutes_since_midnight % interval_minutes
    return phase < run_minutes


def exhaust_follows_ac(schedule_enabled: bool, mode: str) -> bool:
    """True when the exhaust should mirror the AC: only in auto mode, and
    only while its own schedule is off - an enabled schedule always wins."""
    return not schedule_enabled and mode == "auto"
