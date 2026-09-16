"""Background jobs: auto-revert manual mode, periodic Excel export."""
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session

from excel_export import export_readings_to_excel

logger = logging.getLogger("scheduler")

AUTO_REVERT_MINUTES = float(os.getenv("AUTO_REVERT_MINUTES", "30"))
EXPORT_INTERVAL_MINUTES = float(os.getenv("EXPORT_INTERVAL_MINUTES", "60"))
AUTO_REVERT_CHECK_INTERVAL_SECONDS = float(os.getenv("AUTO_REVERT_CHECK_INTERVAL_SECONDS", "60"))


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
    scheduler.start()
    return scheduler
