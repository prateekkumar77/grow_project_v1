"""Dashboard authentication: HTTP Basic Auth, two fixed roles.

Users live in the DASHBOARD_USERS env var as a JSON array, e.g.:

    DASHBOARD_USERS=[{"username":"admin","password":"changeme","role":"admin"},
                      {"username":"viewer","password":"changeme","role":"viewer"}]

No password hashing, no sessions, no new dependency - just base64 Basic Auth
compared with secrets.compare_digest(), matching the project's minimal-
dependency stance (same reasoning as the single-file no-build-step
dashboard). Fail closed: if DASHBOARD_USERS is missing, empty, or malformed,
every request is rejected rather than falling back to a shipped default
credential.
"""
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("grow.auth")

VALID_ROLES = {"admin", "viewer"}


@dataclass
class DashboardUser:
    username: str
    password: str
    role: str


def parse_users(raw: str) -> dict[str, DashboardUser]:
    """Parse the DASHBOARD_USERS env value into a username -> user map.

    Invalid entries (missing fields, bad role, duplicate username, or
    unparseable JSON) are dropped with a logged warning rather than raising -
    a typo in one user's role shouldn't take the whole dashboard offline, but
    it also shouldn't silently grant admin.
    """
    users: dict[str, DashboardUser] = {}
    if not raw or not raw.strip():
        return users

    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("DASHBOARD_USERS is not valid JSON - no dashboard logins will work")
        return users

    if not isinstance(entries, list):
        logger.warning("DASHBOARD_USERS must be a JSON array - no dashboard logins will work")
        return users

    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("Skipping DASHBOARD_USERS entry that is not an object: %r", entry)
            continue
        username = entry.get("username")
        password = entry.get("password")
        role = entry.get("role")
        if not username or not password or role not in VALID_ROLES:
            logger.warning("Skipping invalid DASHBOARD_USERS entry for username=%r", username)
            continue
        if username in users:
            logger.warning("Duplicate DASHBOARD_USERS username %r - keeping first entry", username)
            continue
        users[username] = DashboardUser(username=username, password=password, role=role)

    return users


def authenticate(users: dict[str, DashboardUser], username: str, password: str) -> Optional[DashboardUser]:
    """Return the matching user if username+password are both correct, else None.

    Always runs a compare_digest call even for an unknown username (against
    a dummy value) so a wrong username and a wrong password take the same
    amount of time - an unknown username shouldn't be distinguishable from a
    known one with a bad password via response timing.
    """
    user = users.get(username)
    real_password = user.password if user is not None else ""
    password_ok = secrets.compare_digest(password, real_password)
    if user is not None and password_ok:
        return user
    return None


DASHBOARD_USERS = parse_users(os.getenv("DASHBOARD_USERS", ""))
if not DASHBOARD_USERS:
    logger.warning("DASHBOARD_USERS is empty or invalid - the dashboard will reject every request")
