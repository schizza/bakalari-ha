"""Sensor for Bakalari - zprávy dítěte."""

from __future__ import annotations

import logging
from typing import Any

from async_bakalari_api.komens import MessageContainer
from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
import orjson

from .api import BakalariClient

_LOGGER = logging.getLogger(__name__)


class BakalariMessagesSensor(SensorEntity):
    """Sensor for Bakalari messages for a specific child."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
        child_id: str,
        child_name: str,
    ) -> None:
        """Initialize the sensors."""
        self._hass = hass
        self._entry = entry
        self._child_id = child_id
        self._child_name = child_name
        # Keep short, child will be visible at device level
        self._attr_name = f"Bakaláři zprávy {child_name}"
        self._attr_unique_id = f"bakalari_{child_id}_messages"
        self._attr_icon = "mdi:email"
        self._messages: list[dict[str, Any]] = []
        self._client = BakalariClient(hass, entry, child_id)

    @property
    def state(self) -> int:
        """Return the number of messages."""
        return len(self._messages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the messages as an attribute."""
        return {"messages": self._messages}

    async def async_update(self) -> None:
        """Fetch messages from Bakalari."""
        _LOGGER.warning(
            "[sensor.async_update][BEFORE] unique_id=%s self_id=%s client_id=%s child_id=%s client.child_id=%s",
            self._attr_unique_id,
            hex(id(self)),
            hex(id(self._client)),
            self._child_id,
            getattr(self._client, "child_id", None),
        )
        data: list[MessageContainer] = await self._client.async_get_messages()
        messages = [orjson.loads(msg.as_json()) for msg in data]
        _LOGGER.warning(
            "[sensor.async_update][AFTER ] unique_id=%s self_id=%s client_id=%s child_id=%s client.child_id=%s data_len=%s",
            self._attr_unique_id,
            hex(id(self)),
            hex(id(self._client)),
            self._child_id,
            getattr(self._client, "child_id", None),
            len(data) if data is not None else None,
        )
        self._messages = messages
