"""Utilities for the Bakalari integration."""

from __future__ import annotations

from datetime import date
from typing import Any, cast
import uuid

import voluptuous as vol

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SCHOOL,
    CONF_SERVER,
    CONF_SURNAME,
    CONF_USER_ID,
    CONF_USERNAME,
    DOMAIN,
    ChildRecord,
    ChildrenMap,
)

CHILD_STORAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_ID): str,
        vol.Optional(CONF_NAME, default=""): str,
        vol.Optional(CONF_SURNAME, default=""): str,
        vol.Optional(CONF_SCHOOL, default=""): str,
        vol.Optional(CONF_SERVER, default=""): str,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_ACCESS_TOKEN): str,
        vol.Optional(CONF_REFRESH_TOKEN): str,
    },
    extra=vol.ALLOW_EXTRA,
)

CHILDREN_MAP_SCHEMA = vol.Schema({str: CHILD_STORAGE_SCHEMA})


# Child helpers
def child_from_raw(raw: dict[str, Any] | None) -> tuple[str, ChildRecord]:
    """Convert RAW data to ChildRecord."""

    creds: dict[str, Any] = (raw or {}).get("credentials") or {}
    if hasattr(creds, "__dict__"):
        # child_id: str = creds.get(CONF_USER_ID) or raw.get(CONF_USER_ID)
        child_id = raw.get(CONF_USER_ID) or getattr(creds, CONF_USER_ID, None)
        access_token = getattr(creds, CONF_ACCESS_TOKEN, None)
        refresh_token = getattr(creds, CONF_REFRESH_TOKEN, None)
    else:
        child_id = creds.get(CONF_USER_ID) or raw.get(CONF_USER_ID)
        access_token = creds.get(CONF_ACCESS_TOKEN)
        refresh_token = creds.get(CONF_REFRESH_TOKEN)

    if not child_id:
        # fallback – should not happen
        child_id = f"child_{uuid.uuid4().hex[:8]}"

    child: ChildRecord = {
        CONF_USER_ID: child_id,
        CONF_NAME: raw.get(CONF_NAME, ""),
        CONF_SURNAME: raw.get(CONF_SURNAME, ""),
        CONF_SCHOOL: raw.get(CONF_SCHOOL, ""),
        CONF_USERNAME: str(raw.get(CONF_USERNAME, "") or ""),
        CONF_SERVER: raw.get(CONF_SERVER, ""),
    }
    if access_token:
        child[CONF_ACCESS_TOKEN] = access_token
    if refresh_token:
        child[CONF_REFRESH_TOKEN] = refresh_token

    # validace & normalizace
    child = CHILD_STORAGE_SCHEMA(child)
    return child_id, child


def children_list_to_dict(raw_list: list[dict[str, Any]] | None) -> ChildrenMap:
    """Convert RAW dict to dict {child_id: ChildRecord}."""

    out: ChildrenMap = {}
    for item in raw_list or []:
        cid, child = child_from_raw(item)
        out[cid] = child
    return out


def ensure_child_record(obj: Any, child_id: str) -> ChildRecord:
    """Return a normalized ChildRecord for the given child_id.

    Accepts:
    - raw child record (dict)
    - children map dict {child_id: child_record}
    - list of raw child records
    """

    raw: dict[str, Any] | None = None

    # Case 1: children map dict
    if isinstance(obj, dict) and child_id in obj and isinstance(obj[child_id], dict):
        raw = obj.get(child_id)

    # Case 2: raw child dict
    elif isinstance(obj, dict) and (
        CONF_USER_ID in obj
        or CONF_SERVER in obj
        or CONF_NAME in obj
        or "credentials" in obj
    ):
        raw = obj

    # Case 3: list of raw child dicts
    elif isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                continue
            creds = item.get("credentials") or {}
            uid = item.get(CONF_USER_ID) or (
                creds.get(CONF_USER_ID) if isinstance(creds, dict) else None
            )
            if str(uid) == str(child_id):
                raw = item
                break

    # Fallback: build minimal raw record with given child_id
    if raw is None:
        raw = {CONF_USER_ID: str(child_id)}

    _, child = child_from_raw(raw)
    if child_id:
        child[CONF_USER_ID] = str(child_id)
        child = CHILD_STORAGE_SCHEMA(child)
    return child


def ensure_children_dict(obj: Any) -> ChildrenMap:
    """Accept any object and return a ChildrenMap.

    - If it's a dict: normalizes/validates each child.
    - If it's a list: converts to dict by user_id.
    - Otherwise returns an empty dict.
    """

    if isinstance(obj, dict):
        out: ChildrenMap = {}
        for cid, raw_child in obj.items():
            if raw_child is None:
                continue
            try:
                out[str(cid)] = cast(ChildRecord, CHILD_STORAGE_SCHEMA(dict(raw_child)))
            except vol.Invalid:
                out[str(cid)] = cast(ChildRecord, dict(raw_child or {}))
        return out

    if isinstance(obj, list):
        return children_list_to_dict(obj)
    return {}


def redact_child_info(child_info: ChildRecord) -> ChildRecord:
    """Redact sensitive information from child info."""

    # Do not mutate the original dict; return a shallow copy with redacted fields
    redacted: ChildRecord = cast(ChildRecord, dict(child_info))

    if CONF_ACCESS_TOKEN in redacted:
        redacted[CONF_ACCESS_TOKEN] = "***" if redacted[CONF_ACCESS_TOKEN] else "EMPTY!"
    if CONF_REFRESH_TOKEN in redacted:
        redacted[CONF_REFRESH_TOKEN] = (
            "***" if redacted[CONF_REFRESH_TOKEN] else "EMPTY!"
        )
    return redacted


def make_child_key(server: str, user_id: str) -> str:
    """Create a file-system safe and readable composite key for a child.

    The server must not contain the '|' character.
    """
    return f"{server}|{user_id}"


def device_ident(entry_id: str, child_key: str) -> tuple[str, str]:
    """Create a device identification tuple for Home Assistant device registry.

    The entry_id and child_key must not contain the ':' character.
    """
    # identification tuple for HA device registry
    return (DOMAIN, f"{entry_id}:{child_key}")


def school_year_bounds(
    ref_day: date, start_month: int = 9, start_day: int = 1
) -> tuple[date, date]:
    """Calculate the start and end dates of the school year for reference day.

    The start date is the first day of the school year, which is the first day of the month specified by start_month.
    Default: 1.9. XXXX - 31.8. XXXX+1
    """
    start = date(ref_day.year, start_month, start_day)

    if ref_day < start:
        start = date(ref_day.year - 1, start_month, start_day)
    end = date(start.year + 1, start_month, start_day)
    return start, end
