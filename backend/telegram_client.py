"""Telegram Bot API integration for the high-temperature alert (see
alerting.py for the cooldown logic that decides when to call this).

Called from a FastAPI BackgroundTask, after the /api/telemetry response
has already been built, so a slow or unreachable Telegram never adds
latency to the ESP32's telemetry POST. Every failure is caught and
logged, never raised - a notification failing to send is never a reason
to disrupt the control loop.
"""
import logging
import os

import httpx

logger = logging.getLogger("telegram_client")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("TELEGRAM_REQUEST_TIMEOUT_SECONDS", "10"))


def send_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram alert skipped - TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=TELEGRAM_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram alert failed to send: %s", exc)
