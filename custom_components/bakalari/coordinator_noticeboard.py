"""Noticeboard coordinator."""

from __future__ import annotations

from datetime import timedelta
import logging
from random import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import orjson

from .api import BakalariClient
from .children import ChildrenIndex
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Optional options key for messages polling. If not provided, falls back to DEFAULT_SCAN_INTERVAL.
CONF_SCAN_INTERVAL_NOTICEBOARD = "scan_interval_noticeboard"
NOTICEBOARD_DEFAULT_SCAN_INTERVAL = 1800  # 1 hour default for messages


class BakalariNoticeboardCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator fetching Noticeboard messages."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        children: ChildrenIndex,
        clients: dict[str, BakalariClient],
    ) -> None:
        """Initialize the noticeboard coordinator."""
        self.hass = hass
        self.entry = entry

        # Get children index
        self.children_index: ChildrenIndex = children
        # Clients cache
        self._clients: dict[str, BakalariClient] = clients

        # Diff cache: remember seen messages per (child_key, message_id)
        self._seen_notice_msgs: set[tuple[str, str]] = set()

        # Interval with jitter so we don't stampede servers
        base = int(
            entry.options.get(
                CONF_SCAN_INTERVAL_NOTICEBOARD, NOTICEBOARD_DEFAULT_SCAN_INTERVAL
            )
            or DEFAULT_SCAN_INTERVAL
        )
        jittered = int(base * (0.9 + 0.2 * random()))
        update_interval = timedelta(seconds=jittered)

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN} noticeboard coordinator ({entry.entry_id})",
            update_interval=update_interval,
        )

        _LOGGER.debug(
            "[class=%s module=%s] Noticeboard coordinator initialized for entry_id=%s with %d child(ren). Interval=%ss",
            self.__class__.__name__,
            __name__,
            entry.entry_id,
            len(self.children_index.children),
            jittered,
        )

    # -------- Public API --------

    def get_client(self, child_key: str) -> BakalariClient | None:
        """Return a client for a given child."""

        client = self._clients[child_key] or None
        if not client:
            _LOGGER.error(
                "[class=%s module=%s] Failed to get client for child %s",
                self.__class__.__name__,
                __name__,
                child_key,
                stacklevel=2,
            )
            return None
        return client

    def select_messages(
        self, child_key: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return messages for a child (already parsed/flattened)."""

        items: list[dict[str, Any]] = (self.data or {}).get(
            "messages_by_child", {}
        ).get(child_key, []) or []
        if limit is not None and limit >= 0:
            return items[:limit]
        return items

    async def async_mark_message_seen(self, message_id: str, child_key: str) -> None:
        """Mark a message as seen to suppress 'new message' events."""

        if child_key and message_id:
            self._seen_notice_msgs.add((child_key, message_id))

    # -------- Update lifecycle --------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch messages for each configured child."""
        try:
            messages_by_child: dict[str, list[dict[str, Any]]] = {}

            for child in self.children_index.children:
                parsed = await self._fetch_child_messages(child.key)
                # annotate new/seen
                annotated: list[dict[str, Any]] = []
                for m in parsed:
                    mid = self._extract_message_id(m)
                    is_new = bool(mid) and (
                        (child.key, mid) not in self._seen_notice_msgs
                    )
                    if is_new and mid:
                        # Remember and fire an event
                        self._seen_notice_msgs.add((child.key, mid))
                        self._fire_new_message_event(child.key, m)
                    annotated.append({**m, "is_new": is_new})
                messages_by_child[child.key] = annotated
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        else:
            return {
                "messages_by_child": messages_by_child,
                "last_sync_ok": True,
            }

    async def _fetch_child_messages(self, child_key: str) -> list[dict[str, Any]]:
        """Fetch and parse messages for a single child."""
        client = self.get_client(child_key)
        if client is None:
            return []

        raw_items = await client.async_fetch_noticeboard()
        parsed: list[dict[str, Any]] = []
        try:
            parsed = [orjson.loads(m.as_json()) for m in (raw_items or [])]
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed to parse noticeboard messages for child_key=%s",
                self.__class__.__name__,
                __name__,
                child_key,
            )
        return parsed

    # -------- Helpers --------

    @staticmethod
    def _extract_message_id(msg: dict[str, Any]) -> str | None:
        """Try to extract some stable identifier from the message."""
        for key in ("id", "message_id", "uuid", "guid", "Id", "MessageId"):
            v = msg.get(key)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        # Fallback: compose from typical fields, may be unstable but better than nothing
        composed = "-".join(
            str(msg.get(k, "")).strip() for k in ("subject", "title", "date", "created")
        ).strip("-")
        return composed or None

    @callback
    def _fire_new_message_event(self, child_key: str, msg: dict[str, Any]) -> None:
        """Emit HA event for a newly observed message."""
        try:
            self.hass.bus.async_fire(
                "bakalari_new_noticeboard_message",
                {"child_key": child_key, "message": msg},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed to fire new noticeboard message event for child_key=%s",
                self.__class__.__name__,
                __name__,
                child_key,
            )
