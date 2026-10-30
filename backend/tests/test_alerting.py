from datetime import datetime, timedelta

from alerting import ac_power_check_failed, should_notify_all_alerts, should_send_temp_alert

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


def test_all_mode_skips_ac_check_entry_to_avoid_double_send():
    assert should_notify_all_alerts("all", "ac power check failed: off but 850W") is False


def test_ac_off_check_passes_below_threshold():
    assert ac_power_check_failed(False, 199.0, off_max_w=200, on_min_w=30) is False


def test_ac_off_check_fails_at_or_above_threshold():
    assert ac_power_check_failed(False, 200.0, off_max_w=200, on_min_w=30) is True
    assert ac_power_check_failed(False, 850.0, off_max_w=200, on_min_w=30) is True


def test_ac_on_check_passes_at_or_above_threshold():
    assert ac_power_check_failed(True, 30.0, off_max_w=200, on_min_w=30) is False
    assert ac_power_check_failed(True, 900.0, off_max_w=200, on_min_w=30) is False


def test_ac_on_check_fails_below_threshold():
    assert ac_power_check_failed(True, 5.0, off_max_w=200, on_min_w=30) is True
