"""Home Assistant REST integration.

Every call is wrapped so a failure or timeout here never blocks or breaks
the /api/telemetry response - we log and move on. HA is a nice-to-have
notification/automation channel, not a dependency of the control loop.
"""
import logging
import os
import time
from typing import Dict

import httpx

logger = logging.getLogger("ha_client")

HA_URL = os.getenv("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_SWITCH_ENTITY = os.getenv("HA_SWITCH_ENTITY", "switch.grow_tent_exhaust")
HA_SPEAKER_ENTITY = os.getenv("HA_SPEAKER_ENTITY", "media_player.google_home_speaker")
HA_ALERT_DEBOUNCE_SECONDS = float(os.getenv("HA_ALERT_DEBOUNCE_SECONDS", "600"))
HA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("HA_REQUEST_TIMEOUT_SECONDS", "5"))

_headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

# alert_type -> unix timestamp of last time it was actually sent
_last_alert_sent: Dict[str, float] = {}


def _call_service(domain: str, service: str, payload: dict) -> bool:
    url = f"{HA_URL}/api/services/{domain}/{service}"
    try:
        resp = httpx.post(url, headers=_headers, json=payload, timeout=HA_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - HA being unreachable must never break telemetry
        logger.warning("Home Assistant call %s.%s failed: %s", domain, service, exc)
        return False


def toggle_switch(entity_id: str, on: bool) -> bool:
    service = "turn_on" if on else "turn_off"
    return _call_service("switch", service, {"entity_id": entity_id})


def toggle_grow_tent_switch(on: bool) -> bool:
    return toggle_switch(HA_SWITCH_ENTITY, on)


def speak(message: str, entity_id: str = HA_SPEAKER_ENTITY) -> bool:
    # tts.speak's exact payload shape has changed across HA versions - the
    # media_player_entity_id + cache field combo below matches the current
    # (2024+) tts.speak action. Confirm this once against your own HA
    # instance via Developer Tools -> Actions before relying on it, per the
    # build brief.
    payload = {
        "entity_id": "tts.google_translate_en_com",
        "media_player_entity_id": entity_id,
        "message": message,
        "cache": False,
    }
    return _call_service("tts", "speak", payload)


def send_alert(alert_type: str, message: str) -> None:
    """Debounced alert: speaks on the Google Home speaker, at most once per
    HA_ALERT_DEBOUNCE_SECONDS for a given alert_type. Never raises."""
    try:
        now = time.time()
        last = _last_alert_sent.get(alert_type, 0)
        if now - last < HA_ALERT_DEBOUNCE_SECONDS:
            return
        _last_alert_sent[alert_type] = now
        speak(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_alert(%s) failed: %s", alert_type, exc)
