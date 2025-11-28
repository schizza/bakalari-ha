"""Timetable-specific coordinator for Bakalari API with an independent, longer update interval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from random import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as ha_dt

from .api import BakalariClient
from .children import Child, ChildrenIndex
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Custom option key for timetable polling. If not set, falls back to a safe default.
CONF_SCAN_INTERVAL_TIMETABLE = "scan_interval_timetable"
# Default to 6 hours for timetable polling
TIMETABLE_DEFAULT_SCAN_INTERVAL = 6 * 60 * 60  # 6h


@dataclass(slots=True, frozen=True)
class _ChildOptMap:
    """Helper structure to bind a normalized Child with its original options key."""

    child: Child
    opt_key: str  # original options key (usually the child id in options)


class BakalariTimetableCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator fetching timetable per child at an independent (longer) interval."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, children_index: ChildrenIndex
    ) -> None:
        """Initialize the timetable coordinator."""
        self.hass = hass
        self.entry = entry

        # Prepare children from shared index
        self.children_index = children_index
        self._children: list[_ChildOptMap] = []

        for ch in self.children_index.children:
            opt_key = self.children_index.option_key_for_child(ch.key) or ch.user_id
            self._children.append(_ChildOptMap(child=ch, opt_key=opt_key))

        # Clients cache
        self._clients: dict[str, BakalariClient] = {}

        # Interval with jitter so we don't stampede servers
        base = int(
            entry.options.get(
                CONF_SCAN_INTERVAL_TIMETABLE, TIMETABLE_DEFAULT_SCAN_INTERVAL
            )
            or DEFAULT_SCAN_INTERVAL
        )
        jittered = int(base * (0.9 + 0.2 * random()))
        update_interval = timedelta(seconds=jittered)

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN} timetable coordinator ({entry.entry_id})",
            update_interval=update_interval,
        )

        _LOGGER.debug(
            "[class=%s module=%s] Timetable coordinator initialized for entry_id=%s with %d child(ren). Interval=%ss",
            self.__class__.__name__,
            __name__,
            entry.entry_id,
            len(self._children),
            jittered,
        )

    # -------- Public API --------

    def child_api(self, child_key: str) -> BakalariClient | None:
        """Return BakalariClient for a child if already created."""
        return self._clients.get(child_key, None)

    def select_timetable(
        self, child_key: str | None, limit: int | None = None
    ) -> list[Any]:
        """Return cached timetable (weeks) for a child."""
        ck = child_key or (self._children[0].child.key if self._children else "")
        items: list[Any] = (self.data or {}).get("timetable_by_child", {}).get(
            ck, []
        ) or []
        if limit is not None and limit >= 0:
            return items[:limit]
        return items

    # -------- Update lifecycle --------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch timetable for each configured child."""
        try:
            timetable_by_child: dict[str, list[Any]] = {}
            permanent_by_child: dict[str, Any] = {}
            window_dates_by_child: dict[str, list[str]] = {}

            today = ha_dt.now().date()
            dates = [today, today + timedelta(weeks=1), today - timedelta(weeks=1)]

            for cm in self._children:
                weeks, permanent = await self._fetch_child_timetable(cm, dates)
                timetable_by_child[cm.child.key] = weeks
                permanent_by_child[cm.child.key] = permanent
                window_dates_by_child[cm.child.key] = [d.isoformat() for d in dates]
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        else:
            return {
                "timetable_by_child": timetable_by_child,
                "permanent_timetable_by_child": permanent_by_child,
                "timetable_window_dates": window_dates_by_child,
                "last_sync_ok": True,
            }

    async def _fetch_child_timetable(
        self, cm: _ChildOptMap, dates: list[Any]
    ) -> tuple[list[Any], Any]:
        """Fetch and return (weeks, permanent) timetable for a single child."""
        client = self._clients.get(cm.child.key)
        if client is None:
            # Map to the original options key for client state/tokens
            opt_key = cm.opt_key
            client = BakalariClient(self.hass, self.entry, opt_key)
            self._clients[cm.child.key] = client

        # Actual weeks for an observation window
        weeks: list[Any] = []
        for d in dates:
            w = await client.async_get_timetable_actual(d)
            weeks.append(w)

        # Permanent timetable (if available)
        permanent = await client.async_get_timetable_permanent()

        return weeks, permanent
