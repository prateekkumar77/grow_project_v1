"""Background jobs: auto-revert manual mode, periodic Excel export, Home
Assistant reachability check."""
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session

import ha_client
from excel_export import export_readings_to_excel

logger = logging.getLogger("scheduler")

AUTO_REVERT_MINUTES = float(os.getenv("AUTO_REVERT_MINUTES", "30"))
EXPORT_INTERVAL_MINUTES = float(os.getenv("EXPORT_INTERVAL_MINUTES", "60"))
AUTO_REVERT_CHECK_INTERVAL_SECONDS = float(os.getenv("AUTO_REVERT_CHECK_INTERVAL_SECONDS", "60"))
HA_HEALTH_CHECK_INTERVAL_SECONDS = float(os.getenv("HA_HEALTH_CHECK_INTERVAL_SECONDS", "30"))


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
    scheduler.start()
    return scheduler
