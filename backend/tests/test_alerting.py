from datetime import datetime, timedelta

from alerting import should_notify_all_alerts, should_send_temp_alert

NOW = datetime(2026, 1, 1, 12, 0, 0)


def test_below_threshold_never_sends():
    assert should_send_temp_alert(30.0, 32.0, None, NOW, 15) is False


def test_below_threshold_ignores_cooldown():
    last_sent = NOW - timedelta(minutes=1)
    assert should_send_temp_alert(30.0, 32.0, last_sent, NOW, 15) is False


def test_first_crossing_sends_immediately():
    assert should_send_temp_alert(32.0, 32.0, None, NOW, 15) is True


def test_exactly_at_threshold_counts_as_crossed():
    assert should_send_temp_alert(32.0, 32.0, None, NOW, 15) is True


def test_within_cooldown_does_not_resend():
    last_sent = NOW - timedelta(minutes=10)
    assert should_send_temp_alert(33.0, 32.0, last_sent, NOW, 15) is False


def test_cooldown_elapsed_exactly_at_boundary_resends():
    last_sent = NOW - timedelta(minutes=15)
    assert should_send_temp_alert(33.0, 32.0, last_sent, NOW, 15) is True


def test_main_mode_never_notifies():
    assert should_notify_all_alerts("main", "fan on") is False


def test_main_mode_never_notifies_even_for_temp_alert():
    assert should_notify_all_alerts("main", "temperature alert sent: 33.0C") is False


def test_all_mode_notifies_ordinary_entries():
    assert should_notify_all_alerts("all", "fan on") is True
    assert should_notify_all_alerts("all", "auto mode on") is True
    assert should_notify_all_alerts("all", "grow profile updated: alert_temp_c 32->30") is True


def test_all_mode_skips_temp_alert_entry_to_avoid_double_send():
    assert should_notify_all_alerts("all", "temperature alert sent: 33.0C") is False
