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
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("ha_client")

HA_URL = os.getenv("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_REQUEST_TIMEOUT_SECONDS = float(os.getenv("HA_REQUEST_TIMEOUT_SECONDS", "5"))

# Blank by default - these name a specific device's entities in a specific
# HA instance, not something safe to default to for every deployment of
# this project. Leaving any of them blank just means that one field is
# always None (see _fetch_entity_state), not an error.
HA_CURRENT_ENTITY = os.getenv("HA_CURRENT_ENTITY", "")
HA_VOLTAGE_ENTITY = os.getenv("HA_VOLTAGE_ENTITY", "")
HA_POWER_ENTITY = os.getenv("HA_POWER_ENTITY", "")

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


@dataclass
class PowerReading:
    """A smart plug's live electrical readings, read from three separate
    HA entities (not a dedicated power-monitoring API this project has any
    other use for). Plain dataclass, not a pydantic model, like
    decision_engine.Reading - the pydantic shape (models.HaPowerStatus)
    only exists for the actual API response."""

    current_a: Optional[float] = None
    voltage_v: Optional[float] = None
    power_w: Optional[float] = None


def _fetch_entity_state(entity_id: str) -> Optional[float]:
    """GET /api/states/<entity_id>, parses the "state" field as a float.
    None on any failure - blank entity_id (not configured), unreachable
    HA, a missing/renamed entity, or a non-numeric state (HA reports
    "unavailable"/"unknown" as plain strings, not errors)."""
    if not entity_id:
        return None
    try:
        resp = httpx.get(
            f"{HA_URL}/api/states/{entity_id}", headers=_headers, timeout=HA_REQUEST_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return float(resp.json()["state"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Home Assistant entity %s fetch failed: %s", entity_id, exc)
        return None


def fetch_power_reading() -> PowerReading:
    """Called on its own schedule (see scheduler.py), same reasoning as
    check_connection() - never from a request path. Three independent
    fetches rather than one combined call, so one misconfigured or
    temporarily unavailable entity doesn't blank out the other two."""
    return PowerReading(
        current_a=_fetch_entity_state(HA_CURRENT_ENTITY),
        voltage_v=_fetch_entity_state(HA_VOLTAGE_ENTITY),
        power_w=_fetch_entity_state(HA_POWER_ENTITY),
    )
