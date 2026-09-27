"""Home Assistant REST integration.

Every call is wrapped so a failure or timeout here never blocks or breaks
the /api/telemetry response - we log and move on. HA is a nice-to-have
automation channel, not a dependency of the control loop.
"""
import logging
import os

import httpx

logger = logging.getLogger("ha_client")

HA_URL = os.getenv("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("HA_REQUEST_TIMEOUT_SECONDS", "5"))

# The AC has no physical relay - it's a Google Home device reached only
# through Home Assistant. Domain is configurable because "AC on a Google
# Home smart plug" (switch.turn_on/off) and "native smart AC" (usually a
# climate.* entity) use different HA service calls; switch covers the
# common smart-plug case.
HA_AC_ENTITY = os.getenv("HA_AC_ENTITY", "switch.grow_tent_ac")
HA_AC_DOMAIN = os.getenv("HA_AC_DOMAIN", "switch")

_headers = {"Content-Type": "application/json"}
if HA_TOKEN:
    # An empty token would otherwise produce "Bearer " (trailing space),
    # which httpx rejects as an invalid header value - fails every call
    # until a real token is configured, exactly the state during initial
    # setup.
    _headers["Authorization"] = f"Bearer {HA_TOKEN}"


def _call_service(domain: str, service: str, payload: dict) -> bool:
    url = f"{HA_URL}/api/services/{domain}/{service}"
    try:
        resp = httpx.post(url, headers=_headers, json=payload, timeout=HA_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - HA being unreachable must never break telemetry
        logger.warning("Home Assistant call %s.%s failed: %s", domain, service, exc)
        return False


def check_connection() -> bool:
    """Hits Home Assistant's own base API endpoint (GET /api/, returns
    {"message": "API running."} on success) to check it's actually
    reachable and the token is valid - not tied to any specific entity or
    domain, so it works even before HA_AC_ENTITY is configured. Called on
    a schedule (see scheduler.py), never from a request path, so a
    slow/hanging HA never adds latency to anything a user is waiting on."""
    try:
        resp = httpx.get(f"{HA_URL}/api/", headers=_headers, timeout=HA_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Home Assistant connection check failed: %s", exc)
        return False


def set_ac(on: bool) -> bool:
    """Drives the AC via Home Assistant. Returns whether the call
    succeeded, so the caller can retry on the next cycle instead of
    silently losing the command if HA was briefly unreachable."""
    service = "turn_on" if on else "turn_off"
    return _call_service(HA_AC_DOMAIN, service, {"entity_id": HA_AC_ENTITY})
