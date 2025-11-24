"""Messages-specific coordinator for Bakalari API with independent update interval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from random import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import orjson

from .api import BakalariClient
from .children import Child, ChildrenIndex
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Optional options key for messages polling. If not provided, falls back to DEFAULT_SCAN_INTERVAL.
CONF_SCAN_INTERVAL_MESSAGES = "scan_interval_messages"
MESSAGES_DEFAULT_SCAN_INTERVAL = 3600  # 1 hour default for messages


@dataclass(slots=True, frozen=True)
class _ChildOptMap:
    child: Child
    opt_key: str  # original options key (usually user_id)


class BakalariMessagesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator fetching Komens messages per child at an independent interval."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, children_index: ChildrenIndex
    ) -> None:
        """Initialize the messages coordinator."""
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

        # Diff cache: remember seen messages per (child_key, message_id)
        self._seen_msgs: set[tuple[str, str]] = set()

        # Interval with jitter so we don't stampede servers
        base = int(
            entry.options.get(
                CONF_SCAN_INTERVAL_MESSAGES, MESSAGES_DEFAULT_SCAN_INTERVAL
            )
            or DEFAULT_SCAN_INTERVAL
        )
        jittered = int(base * (0.9 + 0.2 * random()))
        update_interval = timedelta(seconds=jittered)

        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN} messages coordinator ({entry.entry_id})",
            update_interval=update_interval,
        )

        _LOGGER.debug(
            "[class=%s module=%s] Messages coordinator initialized for entry_id=%s with %d child(ren). Interval=%ss",
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

    def select_messages(
        self, child_key: str | None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return messages for a child (already parsed/flattened)."""
        ck = child_key or (self._children[0].child.key if self._children else "")
        items: list[dict[str, Any]] = (self.data or {}).get(
            "messages_by_child", {}
        ).get(ck, []) or []
        if limit is not None and limit >= 0:
            return items[:limit]
        return items

    async def async_mark_message_seen(
        self, message_id: str, child_key: str | None
    ) -> None:
        """Mark a message as seen to suppress 'new message' events."""
        ck = child_key or (self._children[0].child.key if self._children else "")
        if ck and message_id:
            self._seen_msgs.add((ck, message_id))

    # -------- Update lifecycle --------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch messages for each configured child."""
        try:
            messages_by_child: dict[str, list[dict[str, Any]]] = {}

            for cm in self._children:
                parsed = await self._fetch_child_messages(cm)
                # annotate new/seen
                annotated: list[dict[str, Any]] = []
                for m in parsed:
                    mid = self._extract_message_id(m)
                    is_new = bool(mid) and ((cm.child.key, mid) not in self._seen_msgs)
                    if is_new and mid:
                        # Remember and fire an event
                        self._seen_msgs.add((cm.child.key, mid))
                        self._fire_new_message_event(cm.child.key, m)
                    annotated.append({**m, "is_new": is_new})
                messages_by_child[cm.child.key] = annotated
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        else:
            return {
                "messages_by_child": messages_by_child,
                "last_sync_ok": True,
            }

    async def _fetch_child_messages(self, cm: _ChildOptMap) -> list[dict[str, Any]]:
        """Fetch and parse messages for a single child."""
        client = self._clients.get(cm.child.key)
        if client is None:
            # Map to the original options key for client state/tokens
            opt_key = cm.opt_key
            client = BakalariClient(self.hass, self.entry, opt_key)
            self._clients[cm.child.key] = client

        raw_items = await client.async_get_messages()
        parsed: list[dict[str, Any]] = []
        try:
            parsed = [orjson.loads(m.as_json()) for m in (raw_items or [])]
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed to parse messages for child_key=%s",
                self.__class__.__name__,
                __name__,
                cm.child.key,
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
                "bakalari_new_message", {"child_key": child_key, "message": msg}
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed to fire new message event for child_key=%s",
                self.__class__.__name__,
                __name__,
                child_key,
            )
