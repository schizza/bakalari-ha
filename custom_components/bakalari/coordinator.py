"""Coordinator for Bakalari API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from random import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt
import orjson

from .api import BakalariClient
from .const import (
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL_YEAR_START_DAY,
    CONF_SCHOOL_YEAR_START_MONTH,
    CONF_SERVER,
    CONF_USER_ID,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LIB_VERSION,
    ChildRecord,
    ChildrenMap,
)
from .utils import ensure_children_dict, make_child_key, school_year_bounds

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Child:
    """Normalized child descriptor used by the coordinator."""

    # Composite key, stable across servers: "<server>|<user_id>"
    key: str
    user_id: str
    server: str
    display_name: str  # e.g., "Jana Nováková (ZŠ X)"
    short_name: str


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
                        short_name=cr.get("name"),
                    )
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to normalize child record for id=%s: %s", cid, cr)

        self.child_list: list[Child] = child_list

        # Expose library/API version to entities
        self.api_version: str = f"API: {API_VERSION} Library: {LIB_VERSION}"

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
            "[BakalariCoordinator] Coordinator initialized for entry_id=%s with %s child(ren).",
            entry.entry_id,
            len(self.child_list),
        )

    def child_api(self, child_key: str) -> BakalariClient | None:
        """Get the BakalariClient for a child."""
        return self._clients.get(child_key, None)

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
        """Fetch and prepare marks, messages and timetable for all children."""
        try:
            start_year, end_year = school_year_bounds(
                dt.now().date(), CONF_SCHOOL_YEAR_START_MONTH, CONF_SCHOOL_YEAR_START_DAY
            )

            subjects_by_child: dict[str, dict[str, dict[str, Any]]] = {}
            marks_by_child_subject: dict[str, dict[str, list[dict[str, Any]]]] = {}
            marks_flat_by_child: dict[str, list[dict[str, Any]]] = {}
            summary: dict[str, dict[str, str]] = {}

            # removed: unused marks_by_child variable
            messages_by_child: dict[str, list[dict[str, Any]]] = {}
            timetable_by_child: dict[str, list[Any]] = {}

            # Sequential fetch (can be parallelized if needed)
            for ch in self.child_list:
                raw = await self._fetch_child(ch, start_year, end_year)

                snap = raw.get("snapshot") or {}
                subjects_by_child[ch.key] = snap.get("subjects", {})
                marks_by_child_subject[ch.key] = snap.get("marks_grouped", {})
                marks_flat_by_child[ch.key] = snap.get("marks_flat", [])
                summary[ch.key] = raw.get("summary", {})

                # Messages
                messages = self._parse_messages(ch, raw)
                messages_by_child[ch.key] = messages

                # Timetable - keep raw weeks list (as returned by client)
                timetable_by_child[ch.key] = raw.get("timetable") or []

        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        else:
            # Compute is_new per mark (before firing events) for backward compatibility
            annotated_marks_by_child: dict[str, list[dict[str, Any]]] = {}
            for ck, items in marks_flat_by_child.items():
                annotated: list[dict[str, Any]] = []
                for it in items or []:
                    mark_id = str(it.get("id") or "").strip()
                    is_new = bool(mark_id) and ((ck, mark_id) not in self._seen)
                    annotated.append({**it, "is_new": is_new})
                annotated_marks_by_child[ck] = annotated

            # Diff → fire events for new marks
            self._fire_new_events(marks_flat_by_child)

            return {
                "subjects_by_child": subjects_by_child,
                "marks_by_child_subject": marks_by_child_subject,
                # Backward-compatible flat marks list expected by existing sensors
                "marks_by_child": annotated_marks_by_child,
                "marks_flat_by_child": marks_flat_by_child,
                "school_year": {
                    "start": start_year.isoformat(),
                    "end_exclusive": end_year.isoformat(),
                },
                "messages_by_child": messages_by_child,
                "timetable_by_child": timetable_by_child,
                "last_sync_ok": True,
                "summary": summary,
            }

    async def _fetch_child(
        self, child: Child, date_from: datetime | date, date_to: datetime | date
    ) -> dict[str, Any]:
        """Fetch raw payloads (marks, messages, timetable) for a specific child via BakalariClient."""

        # Map composite key to original options key (usually user_id)
        opt_key = self._option_key_by_child_key.get(child.key, child.user_id)

        client = self._clients.get(child.key)
        if client is None:
            client = BakalariClient(self.hass, self.entry, opt_key)
            self._clients[child.key] = client  # cache per child

        # Marks snapshot (subjects, grouped, flat)
        dt_from = (
            datetime.combine(date_from, datetime.min.time())
            if isinstance(date_from, date)
            else date_from
        )
        dt_to = (
            datetime.combine(date_to, datetime.min.time()) if isinstance(date_to, date) else date_to
        )

        snapshot, all_marks_summary = await client.get_marks_snapshot(
            date_from=dt_from, date_to=dt_to, to_dict=True, order="desc"
        )
        _LOGGER.debug(
            "[Coordinator._fetch_child]: Snapshot: %s \n Summary: %s", snapshot, all_marks_summary
        )

        # Messages
        # messages = await client.async_get_messages()

        # Timetable: current, next and previous week
        today = dt.now().date()
        dates = [today, today + timedelta(weeks=1), today - timedelta(weeks=1)]
        weeks: list[Any] = []
        # for d in dates:
        #     w = await client.async_get_timetable_actual(d)
        #     weeks.append(w)

        return {
            "snapshot": snapshot,
            "summary": all_marks_summary,
            #  "messages": messages,
            # "timetable": weeks,
            "_range": (date_from, date_to),
        }

    def _parse_messages(self, child: Child, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize raw messages into a list of dicts."""
        data = raw.get("messages") or []
        items: list[dict[str, Any]] = []
        try:
            items = [orjson.loads(m.as_json()) for m in data]
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to parse messages for child_key=%s", child.key)
        return items

    def option_key_for_child(self, child_key: str) -> str | None:
        """Expose original options key (typically user_id) for a given composite child key."""
        return self._option_key_by_child_key.get(child_key)

    @property
    def option_key_by_child_key(self) -> dict[str, str]:
        """Expose a copy of the mapping 'composite child key' -> 'options key' for migrations."""
        return dict(self._option_key_by_child_key)

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
