"""Background jobs: auto-revert manual mode, periodic Excel export, Home
Assistant reachability check, HA power poll (and the AC power check that
rides on it)."""
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session

import ha_client
import telegram_client
from activity_log import AUTO_ACTOR
from alerting import AC_CHECK_ACTIVITY_PREFIX, ac_power_check_failed
from excel_export import export_readings_to_excel

logger = logging.getLogger("scheduler")

AUTO_REVERT_MINUTES = float(os.getenv("AUTO_REVERT_MINUTES", "30"))
EXPORT_INTERVAL_MINUTES = float(os.getenv("EXPORT_INTERVAL_MINUTES", "60"))
AUTO_REVERT_CHECK_INTERVAL_SECONDS = float(os.getenv("AUTO_REVERT_CHECK_INTERVAL_SECONDS", "60"))
HA_HEALTH_CHECK_INTERVAL_SECONDS = float(os.getenv("HA_HEALTH_CHECK_INTERVAL_SECONDS", "30"))
# Faster than the connectivity check above - this is meant to feel "live"
# next to the dashboard's own 5s poll, not just a periodic health signal.
HA_POWER_POLL_INTERVAL_SECONDS = float(os.getenv("HA_POWER_POLL_INTERVAL_SECONDS", "10"))
# AC power check (a "main" Telegram alert): this long after an AC on/off
# command reaches the ESP32, the HA smart plug's power draw should match -
# under AC_OFF_MAX_POWER_W once off, at least AC_ON_MIN_POWER_W once on.
AC_POWER_CHECK_DELAY_SECONDS = float(os.getenv("AC_POWER_CHECK_DELAY_SECONDS", "60"))
AC_OFF_MAX_POWER_W = float(os.getenv("AC_OFF_MAX_POWER_W", "200"))
AC_ON_MIN_POWER_W = float(os.getenv("AC_ON_MIN_POWER_W", "30"))


def _check_auto_revert(app_state):
    with app_state.lock:
        if app_state.mode != "manual":
            return
        if app_state.last_manual_activity is None:
            return
        idle_for = datetime.utcnow() - app_state.last_manual_activity
        if idle_for >= timedelta(minutes=AUTO_REVERT_MINUTES):
            app_state.mode = "auto"
            logger.info("Auto-reverted from manual to auto after %s idle", idle_for)


def _run_export(engine):
    try:
        with Session(engine) as session:
            export_readings_to_excel(session)
    except Exception:  # noqa: BLE001 - a failed export must never crash the app
        logger.exception("Scheduled Excel export failed")


def _check_ha_connection(app_state):
    # Runs on its own schedule rather than per-request, so a slow or
    # hanging Home Assistant never adds latency to /api/status (polled
    # every 5s by the dashboard) or /api/telemetry.
    reachable = ha_client.check_connection()
    with app_state.lock:
        app_state.ha_reachable = reachable
        app_state.ha_last_checked = datetime.utcnow()


def _check_ha_power(app_state):
    # Same "own schedule, never per-request" reasoning as
    # _check_ha_connection above - fetch_power_reading() makes up to three
    # HTTP calls, never something /api/status should block on.
    reading = ha_client.fetch_power_reading()
    with app_state.lock:
        app_state.ha_power = reading
        app_state.ha_power_checked_at = datetime.utcnow()
    _check_ac_power(app_state, reading.power_w)


def _check_ac_power(app_state, power_w):
    """Runs after every power poll, so the reading it judges is at most
    HA_POWER_POLL_INTERVAL_SECONDS old. Fires once per queued check (see
    post_telemetry), and only once AC_POWER_CHECK_DELAY_SECONDS have
    passed - enough for the AC to respond, including the firmware's own
    30s backup resend of the IR signal."""
    now = datetime.utcnow()
    with app_state.lock:
        pending = app_state.ac_power_check
        if pending is None:
            return
        ac_on, sent_at = pending
        if (now - sent_at).total_seconds() < AC_POWER_CHECK_DELAY_SECONDS:
            return
        app_state.ac_power_check = None
        if power_w is None:
            logger.warning("AC power check skipped - no power reading from Home Assistant")
            return
        if not ac_power_check_failed(ac_on, power_w, AC_OFF_MAX_POWER_W, AC_ON_MIN_POWER_W):
            return
        state = "on" if ac_on else "off"
        app_state.activity_log.record(f"{AC_CHECK_ACTIVITY_PREFIX} {state} but {power_w:.0f}W", AUTO_ACTOR)

    if ac_on:
        expected = f"at least {AC_ON_MIN_POWER_W:.0f}W"
    else:
        expected = f"under {AC_OFF_MAX_POWER_W:.0f}W"
    telegram_client.send_message(
        f"Check AC: it was turned {state.upper()} {AC_POWER_CHECK_DELAY_SECONDS:.0f}s ago, "
        f"but the smart plug reads {power_w:.0f}W (expected {expected}). "
        "It may have missed the IR signal."
    )


def start_scheduler(app_state, engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _check_auto_revert,
        "interval",
        seconds=AUTO_REVERT_CHECK_INTERVAL_SECONDS,
        args=[app_state],
        id="auto_revert_mode",
    )
    scheduler.add_job(
        _run_export,
        "interval",
        minutes=EXPORT_INTERVAL_MINUTES,
        args=[engine],
        id="excel_export",
    )
    scheduler.add_job(
        _check_ha_connection,
        "interval",
        seconds=HA_HEALTH_CHECK_INTERVAL_SECONDS,
        args=[app_state],
        id="ha_connection_check",
        next_run_time=datetime.now(),  # check immediately at startup, not after the first interval
    )
    scheduler.add_job(
        _check_ha_power,
        "interval",
        seconds=HA_POWER_POLL_INTERVAL_SECONDS,
        args=[app_state],
        id="ha_power_poll",
        next_run_time=datetime.now(),  # check immediately at startup, not after the first interval
    )
    scheduler.start()
    return scheduler
