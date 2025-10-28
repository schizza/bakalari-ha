"""Coordinator for Bakalari API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from random import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BakalariClient
from .const import (
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SERVER,
    CONF_USER_ID,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LIB_VERSION,
    ChildRecord,
    ChildrenMap,
)
from .utils import ensure_children_dict, make_child_key

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Child:
    """Normalized child descriptor used by the coordinator."""

    # Composite key, stable across servers: "<server>|<user_id>"
    key: str
    user_id: str
    server: str
    display_name: str  # e.g., "Jana Nováková (ZŠ X)"


class BakalariCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Multi-child coordinator with per-child diff cache for new marks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""

        self.hass = hass
        self.entry = entry

        # Normalize children map from options and build composite-keyed map
        children_raw: ChildrenMap = ensure_children_dict(entry.options.get(CONF_CHILDREN, {}))
        self.children: ChildrenMap = {}
        self._option_key_by_child_key: dict[str, str] = {}
        child_list: list[Child] = []

        for cid, cr in children_raw.items():
            try:
                server = (cr.get(CONF_SERVER) or "").strip()
                user_id = (cr.get(CONF_USER_ID) or str(cid)).strip()
                if not server or not user_id:
                    _LOGGER.debug("Skipping child with missing server/user_id: %s", cr)
                    continue

                ck = make_child_key(server, user_id)
                self._option_key_by_child_key[ck] = str(cid)

                # Store by composite key to ensure uniqueness across servers
                tmp_cr: ChildRecord = ChildRecord(
                    user_id=user_id,
                    username=str(cr.get(CONF_USERNAME, "") or ""),
                    name=str(cr.get("name", "") or ""),
                    surname=str(cr.get("surname", "") or ""),
                    school=str(cr.get("school", "") or ""),
                    server=server,
                )
                at = cr.get(CONF_ACCESS_TOKEN)
                if at:
                    tmp_cr[CONF_ACCESS_TOKEN] = at
                rt = cr.get(CONF_REFRESH_TOKEN)
                if rt:
                    tmp_cr[CONF_REFRESH_TOKEN] = rt
                self.children[ck] = tmp_cr

                display_name = (
                    f"{cr.get('name', '')} {cr.get('surname', '')} ({cr.get('school', '')})".strip()
                )
                child_list.append(
                    Child(
                        key=ck,
                        user_id=user_id,
                        server=server,
                        display_name=display_name,
                    )
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to normalize child record for id=%s: %s", cid, cr)

        self.child_list: list[Child] = child_list

        # Expose library/API version to entities
        self.api_version: str = f"API: {API_VERSION} Library: ({LIB_VERSION})"

        # Diff cache per child: set of (child_key, mark_id)
        self._seen: set[tuple[str, str]] = set()

        # Update interval with jitter (avoid stampedes)
        base = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        jittered = int(base * (0.9 + 0.2 * random()))
        update_interval = timedelta(seconds=jittered)

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN} coordinator ({entry.entry_id})",
            update_interval=update_interval,
        )

        # Per-child clients cache (BakalariClient instances)
        self._clients: dict[str, BakalariClient] = {}

        _LOGGER.debug(
            "Coordinator initialized for entry_id=%s with %s child(ren).",
            entry.entry_id,
            len(self.child_list),
        )

    # ---------- Public API for services / WebSocket ----------

    async def async_mark_seen(self, mark_id: str, child_key: str | None) -> None:
        """Mark a specific mark_id as seen for a given child."""
        ck = child_key or (self.child_list[0].key if self.child_list else "")
        if ck and mark_id:
            self._seen.add((ck, mark_id))

    def select_marks(self, child_key: str | None, limit: int) -> list[dict[str, Any]]:
        """Return last N marks for a child (already parsed/flattened)."""
        ck = child_key or (self.child_list[0].key if self.child_list else "")
        items: list[dict[str, Any]] = self.data.get("marks_by_child", {}).get(ck, [])
        return items[: max(0, limit or 0)]

    # ---------- Update lifecycle ----------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and prepare marks for all children."""
        try:
            marks_by_child: dict[str, list[dict[str, Any]]] = {}

            # Sequential fetch (can be parallelized if needed)
            for ch in self.child_list:
                raw = await self._fetch_child(ch)
                items = self._parse_marks(ch, raw)
                marks_by_child[ch.key] = items

        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        else:
            # Diff → fire events for new marks
            self._fire_new_events(marks_by_child)

            return {
                "marks_by_child": marks_by_child,
                "last_sync_ok": True,
            }

    async def _fetch_child(self, child: Child) -> dict[str, Any]:
        """Fetch raw marks payload for a specific child via BakalariClient."""

        # Map composite key to original options key (usually user_id)
        opt_key = self._option_key_by_child_key.get(child.key, child.user_id)

        client = self._clients.get(child.key)
        if client is None:
            client = BakalariClient(self.hass, self.entry, opt_key)
            self._clients[child.key] = client  # cache per child

        subjects = await client.async_get_marks()
        return {"subjects": subjects}

    def _parse_marks(self, child: Child, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize raw marks into a flat list of dicts."""
        subjects = raw.get("subjects") or []
        items: list[dict[str, Any]] = []
        try:
            for subj in subjects:
                subj_id = getattr(subj, "id", None)
                subj_abbr = getattr(subj, "abbr", "") or ""
                subj_name = getattr(subj, "name", "") or ""

                # subjects.marks is a MarksRegistry (iterable)
                marks_iter = list(subj.marks) if hasattr(subj, "marks") else []
                for m in marks_iter:
                    mark_id = getattr(m, "id", None)
                    if not mark_id:
                        continue
                    marktext_obj = getattr(m, "marktext", None)
                    mark_text = getattr(marktext_obj, "text", None) if marktext_obj else None
                    points_text = getattr(m, "points_text", None)
                    max_points = getattr(m, "max_points", None)
                    is_points = bool(getattr(m, "is_points", False))
                    dt_val = getattr(m, "date", None)
                    date_iso = dt_val.isoformat() if getattr(dt_val, "isoformat", None) else None

                    items.append(
                        {
                            "id": str(mark_id),
                            "child_key": child.key,
                            "user_id": child.user_id,
                            "subject_id": str(getattr(m, "subject_id", subj_id) or ""),
                            "subject_abbr": str(subj_abbr),
                            "subject_name": str(subj_name),
                            "caption": getattr(m, "caption", None),
                            "mark_text": mark_text,
                            "points_text": points_text,
                            "max_points": max_points,
                            "is_points": is_points,
                            "date": date_iso,
                            "is_new": bool(getattr(m, "is_new", False)),
                            "teacher": getattr(m, "teacher", None),
                            "theme": getattr(m, "theme", None),
                        }
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to parse marks for child_key=%s", child.key)

        # Sort by date desc if available, keep stable otherwise
        try:
            items.sort(key=lambda it: it.get("date") or "", reverse=True)
        except Exception:
            _LOGGER.debug("Failed to sort marks for child_key=%s", child.key)
        return items

    def child_by_key(self, ck: str) -> Child:
        """Return Child object by composite key or raise KeyError."""
        for ch in self.child_list:
            if ch.key == ck:
                return ch
        raise KeyError(ck)

    # ---------- Event helpers ----------

    @callback
    def _fire_new_events(self, marks_by_child: dict[str, list[dict[str, Any]]]) -> None:
        """Emit HA events for newly observed marks."""
        if not marks_by_child:
            return

        bus = self.hass.bus
        for ck, items in marks_by_child.items():
            for it in items or []:
                mark_id = str(it.get("id") or "").strip()
                if not mark_id:
                    continue
                key = (ck, mark_id)
                if key in self._seen:
                    continue
                self._seen.add(key)
                bus.async_fire("bakalari_new_mark", {**it})
