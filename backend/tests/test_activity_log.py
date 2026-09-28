from datetime import datetime
from types import SimpleNamespace

from activity_log import ActivityLog, RelayActivityTracker
from models import RelayState


def test_recent_returns_newest_first():
    log = ActivityLog()
    log.record("first")
    log.record("second")

    result = log.recent()

    assert [e.message for e in result] == ["second", "first"]


def test_caps_at_max_entries():
    log = ActivityLog(max_entries=3)
    for i in range(5):
        log.record(f"action {i}")

    result = log.recent()

    assert len(result) == 3
    assert [e.message for e in result] == ["action 4", "action 3", "action 2"]


def test_uses_provided_timestamp():
    log = ActivityLog()
    ts = datetime(2024, 1, 1, 12, 0, 0)
    log.record("test", timestamp=ts)

    assert log.recent()[0].timestamp == ts


def test_defaults_to_now():
    log = ActivityLog()
    before = datetime.utcnow()
    log.record("test")
    after = datetime.utcnow()

    entry_ts = log.recent()[0].timestamp
    assert before <= entry_ts <= after


def test_empty_log_returns_empty_list():
    log = ActivityLog()
    assert log.recent() == []


def test_note_logs_only_on_actual_change():
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    tracker.note("fan", True)
    tracker.note("fan", True)  # no change - must not log again
    tracker.note("fan", False)

    messages = [e.message for e in log.recent()]
    assert messages == ["fan off", "fan on"]


def test_update_only_logs_relays_that_changed():
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    tracker.update(SimpleNamespace(fan=True, ac=False, pump=False, light=False, exhaust=False))
    messages = [e.message for e in log.recent()]
    assert messages == ["fan on"]

    tracker.update(SimpleNamespace(fan=True, ac=True, pump=False, light=False, exhaust=False))
    messages = [e.message for e in log.recent()]
    assert messages == ["ac on", "fan on"]


def test_survives_in_place_mutation_of_the_object_passed_to_update():
    """Regression test: main.py's /api/relay handler does
    setattr(app_state.commanded_relay_state, ...) on the very same
    RelayState instance previously handed to update() - the tracker must
    not hold a reference to that object, or the next diff would compare
    the mutated object to itself and silently stop logging anything."""
    log = ActivityLog()
    tracker = RelayActivityTracker(log)

    state = RelayState()
    tracker.update(state)  # baseline: everything False, nothing logged yet
    assert log.recent() == []

    setattr(state, "pump", True)
    tracker.update(state)
    assert [e.message for e in log.recent()] == ["pump on"]

    setattr(state, "pump", False)
    tracker.update(state)
    assert [e.message for e in log.recent()] == ["pump off", "pump on"]
