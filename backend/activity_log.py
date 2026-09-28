"""In-memory ring buffer of the last N notable actions, for the dashboard's
activity feed (mode switches, relay on/off transitions, schedule changes).
This ring buffer itself is not persisted - it resets on backend restart,
same as every other piece of AppState (mode, schedule config, etc.). The
complete, unbounded history lives in the `activity_log` DB table
(models.ActivityLogRow) instead; main.py persists every entry there via
ActivityLog.on_record, so this module stays free of any DB dependency.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Deque, List, Optional

MAX_ENTRIES = 20

# Actor recorded for anything the decision engine or a schedule did on its
# own, as opposed to a username for a manual dashboard action.
AUTO_ACTOR = "auto"


@dataclass
class ActivityEntry:
    timestamp: datetime
    message: str
    actor: str


class ActivityLog:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: Deque[ActivityEntry] = deque(maxlen=max_entries)
        # Optional hook, set by main.py, invoked with every new entry
        # (even ones the ring buffer itself later evicts) so the DB table
        # can keep the complete history the ring buffer doesn't.
        self.on_record: Optional[Callable[[ActivityEntry], None]] = None

    def record(self, message: str, actor: str, timestamp: Optional[datetime] = None) -> None:
        entry = ActivityEntry(timestamp=timestamp or datetime.utcnow(), message=message, actor=actor)
        self._entries.appendleft(entry)
        if self.on_record is not None:
            self.on_record(entry)

    def recent(self) -> List[ActivityEntry]:
        """Newest first. Oldest entries are silently dropped from this
        in-memory list once max_entries is exceeded - the DB table is
        where the full history lives."""
        return list(self._entries)


class RelayActivityTracker:
    """Records an activity-log entry only when a relay's commanded value
    actually changes, never once per telemetry cycle regardless of
    whether anything changed. Deliberately keeps only plain booleans, not
    a reference to a mutable RelayState - holding the object itself would
    risk aliasing it with whatever the caller mutates in place next (e.g.
    main.py's `setattr(app_state.commanded_relay_state, ...)`), which would
    silently update this tracker's own baseline right along with it and
    make every future diff compare the object to itself.
    """

    RELAYS = ("fan", "ac", "pump", "light", "exhaust")

    def __init__(self, log: ActivityLog) -> None:
        self._log = log
        self._last = {relay: False for relay in self.RELAYS}

    def note(self, relay: str, value: bool, actor: str) -> None:
        """Logs `relay`'s on/off transition only if `value` differs from
        the last known value for it."""
        if self._last[relay] != value:
            self._log.record(f"{relay} {'on' if value else 'off'}", actor)
        self._last[relay] = value

    def update(self, new_state, actor: str) -> None:
        """Checks all relays at once against anything with fan/ac/pump/
        light/exhaust boolean attributes (e.g. models.RelayState) - duck
        typed so this module doesn't need to depend on models.py."""
        for relay in self.RELAYS:
            self.note(relay, getattr(new_state, relay), actor)
