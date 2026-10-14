"""Pure decide-whether-to-notify logic for the high-temperature Telegram
alert (see telegram_client.py for the actual I/O), kept separate so it's
testable without mocking network calls or wall-clock time."""
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


# Prefix of the one activity-log entry the emergency-temperature alert itself
# records (see post_telemetry's should_send_temp_alert() call site) - it
# already gets its own, more detailed Telegram message unconditionally, so
# "all alerts" mode must not also send a second, redundant one for it.
TEMP_ALERT_ACTIVITY_PREFIX = "temperature alert sent:"


def should_notify_all_alerts(telegram_alert_mode: str, message: str) -> bool:
    """"all alerts" mode notifies on every activity-log entry except the
    emergency-temperature one, which the dedicated alert path already
    covers - "main alerts" mode never notifies here at all."""
    return telegram_alert_mode == "all" and not message.startswith(TEMP_ALERT_ACTIVITY_PREFIX)
