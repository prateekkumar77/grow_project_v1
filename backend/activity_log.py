"""In-memory ring buffer of the last N notable actions, for the dashboard's
activity feed (mode switches, relay on/off transitions, schedule changes).
Not persisted - resets on backend restart, same as every other piece of
AppState (mode, schedule config, etc.) not surviving one either.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, List, Optional

MAX_ENTRIES = 20


@dataclass
class ActivityEntry:
    timestamp: datetime
    message: str


class ActivityLog:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: Deque[ActivityEntry] = deque(maxlen=max_entries)

    def record(self, message: str, timestamp: Optional[datetime] = None) -> None:
        self._entries.appendleft(ActivityEntry(timestamp=timestamp or datetime.utcnow(), message=message))

    def recent(self) -> List[ActivityEntry]:
        """Newest first. Oldest entries are silently dropped once
        max_entries is exceeded - there's no archive beyond this list."""
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

    def note(self, relay: str, value: bool) -> None:
        """Logs `relay`'s on/off transition only if `value` differs from
        the last known value for it."""
        if self._last[relay] != value:
            self._log.record(f"{relay} {'on' if value else 'off'}")
        self._last[relay] = value

    def update(self, new_state) -> None:
        """Checks all relays at once against anything with fan/ac/pump/
        light/exhaust boolean attributes (e.g. models.RelayState) - duck
        typed so this module doesn't need to depend on models.py."""
        for relay in self.RELAYS:
            self.note(relay, getattr(new_state, relay))
