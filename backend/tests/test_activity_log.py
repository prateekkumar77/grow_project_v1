from datetime import datetime
from types import SimpleNamespace

from activity_log import ActivityLog, RelayActivityTracker
from models import RelayState


def test_recent_returns_newest_first():
    log = ActivityLog()
    log.record("first", "admin")
    log.record("second", "admin")

    result = log.recent()

    assert [e.message for e in result] == ["second", "first"]


def test_caps_at_max_entries():
    log = ActivityLog(max_entries=3)
    for i in range(5):
        log.record(f"action {i}", "admin")

    result = log.recent()

    assert len(result) == 3
    assert [e.message for e in result] == ["action 4", "action 3", "action 2"]


def test_uses_provided_timestamp():
    log = ActivityLog()
    ts = datetime(2024, 1, 1, 12, 0, 0)
    log.record("test", "admin", timestamp=ts)

    assert log.recent()[0].timestamp == ts


def test_defaults_to_now():
    log = ActivityLog()
    before = datetime.utcnow()
    log.record("test", "admin")
    after = datetime.utcnow()

    entry_ts = log.recent()[0].timestamp
    assert before <= entry_ts <= after


def test_empty_log_returns_empty_list():
    log = ActivityLog()
    assert log.recent() == []


def test_record_stores_actor():
    log = ActivityLog()
    log.record("fan on", "admin")
    log.record("fan off", "auto")

    actors = [e.actor for e in log.recent()]
    assert actors == ["auto", "admin"]


def test_on_record_hook_fires_for_every_entry():
    log = ActivityLog(max_entries=1)
    seen = []
    log.on_record = seen.append

    log.record("first", "admin")
    log.record("second", "auto")

    # The ring buffer only kept the last one, but the hook must have seen
    # both - it's how the full-history DB table stays complete even though
    # the in-memory feed is capped.
    assert len(log.recent()) == 1
    assert [e.message for e in seen] == ["first", "second"]


def test_note_logs_only_on_actual_change():
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    tracker.note("fan", True, "admin")
    tracker.note("fan", True, "admin")  # no change - must not log again
    tracker.note("fan", False, "auto")

    entries = [(e.message, e.actor) for e in log.recent()]
    assert entries == [("fan off", "auto"), ("fan on", "admin")]


def test_update_only_logs_relays_that_changed():
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    tracker.update(SimpleNamespace(fan=True, ac=False, pump=False, light=False, exhaust=False), "admin")
    messages = [e.message for e in log.recent()]
    assert messages == ["fan on"]

    tracker.update(SimpleNamespace(fan=True, ac=True, pump=False, light=False, exhaust=False), "auto")
    entries = [(e.message, e.actor) for e in log.recent()]
    assert entries == [("ac on", "auto"), ("fan on", "admin")]


def test_survives_in_place_mutation_of_the_object_passed_to_update():
    """Regression test: main.py's /api/relay handler does
    setattr(app_state.commanded_relay_state, ...) on the very same
    RelayState instance previously handed to update() - the tracker must
    not hold a reference to that object, or the next diff would compare
    the mutated object to itself and silently stop logging anything."""
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    state = RelayState()
    tracker.update(state, "admin")  # baseline: everything False, nothing logged yet
    assert log.recent() == []

    setattr(state, "pump", True)
    tracker.update(state, "admin")
    assert [e.message for e in log.recent()] == ["pump on"]

    setattr(state, "pump", False)
    tracker.update(state, "admin")
    assert [e.message for e in log.recent()] == ["pump off", "pump on"]
