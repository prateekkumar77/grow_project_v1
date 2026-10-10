"""Home Assistant REST integration.

Every call is wrapped so a failure or timeout here never blocks or breaks
the /api/telemetry response - we log and move on. HA is a nice-to-have
automation channel, not a dependency of the control loop.

AC used to be driven through here (a Google Home device with no ESP32
relay) - it's now a direct ESP32 IR output instead (see
firmware/src/ir_ac.*), so this module is down to the one thing it still
does: report whether Home Assistant is reachable, for the dashboard's own
badge. Kept rather than removed in case this project uses HA for
something else later.
"""
import logging
import os

import httpx

logger = logging.getLogger("ha_client")

HA_URL = os.getenv("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("HA_REQUEST_TIMEOUT_SECONDS", "5"))

_headers = {"Content-Type": "application/json"}
if HA_TOKEN:
    # An empty token would otherwise produce "Bearer " (trailing space),
    # which httpx rejects as an invalid header value - fails every call
    # until a real token is configured, exactly the state during initial
    # setup.
    _headers["Authorization"] = f"Bearer {HA_TOKEN}"


def check_connection() -> bool:
    """Hits Home Assistant's own base API endpoint (GET /api/, returns
    {"message": "API running."} on success) to check it's actually
    reachable and the token is valid. Called on a schedule (see
    scheduler.py), never from a request path, so a slow/hanging HA never
    adds latency to anything a user is waiting on."""
    try:
        resp = httpx.get(f"{HA_URL}/api/", headers=_headers, timeout=HA_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Home Assistant connection check failed: %s", exc)
        return False
