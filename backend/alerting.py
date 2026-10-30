"""Pure decide-whether-to-notify logic for the Telegram alerts (see
telegram_client.py for the actual I/O), kept separate so it's testable
without mocking network calls or wall-clock time."""
from datetime import datetime, timedelta
from typing import Optional


def should_send_temp_alert(
    temp_c: float,
    threshold_c: float,
    last_sent: Optional[datetime],
    now: datetime,
    cooldown_minutes: float,
) -> bool:
    """True once when temp first crosses threshold_c, then again every
    cooldown_minutes for as long as it stays at or above it - a single
    emergency shouldn't go silent for hours, but it also shouldn't fire a
    Telegram message every ~20s telemetry cycle while the tent is hot."""
    if temp_c < threshold_c:
        return False
    if last_sent is None:
        return True
    return now - last_sent >= timedelta(minutes=cooldown_minutes)


def ac_power_check_failed(ac_on: bool, power_w: float, off_max_w: float, on_min_w: float) -> bool:
    """After an AC on/off command has had time to take effect, the smart
    plug's power draw should match it: under off_max_w once turned off,
    at least on_min_w once turned on. True means it doesn't - the AC
    likely missed the IR signal."""
    if ac_on:
        return power_w < on_min_w
    return power_w >= off_max_w


# Prefixes of the activity-log entries that the "main" alerts (emergency
# temperature, AC power check) record - each already gets its own, more
# detailed Telegram message unconditionally, so "all alerts" mode must not
# also send a second, redundant one for them.
TEMP_ALERT_ACTIVITY_PREFIX = "temperature alert sent:"
AC_CHECK_ACTIVITY_PREFIX = "ac power check failed:"
MAIN_ALERT_ACTIVITY_PREFIXES = (TEMP_ALERT_ACTIVITY_PREFIX, AC_CHECK_ACTIVITY_PREFIX)


def should_notify_all_alerts(telegram_alert_mode: str, message: str) -> bool:
    """"all alerts" mode notifies on every activity-log entry except the
    main alerts' own entries, which their dedicated alert paths already
    cover - "main alerts" mode never notifies here at all."""
    return telegram_alert_mode == "all" and not message.startswith(MAIN_ALERT_ACTIVITY_PREFIXES)
