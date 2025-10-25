"""Sensor platform for Bakalari - zprávy dítěte."""

from __future__ import annotations

from datetime import timedelta
import logging

from async_bakalari_api.komens import MessageContainer
from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import orjson

from .api import BakalariClient
from .const import CONF_CHILDREN
from .utils import ensure_children_dict, redact_child_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
SCAN_INTERVAL = timedelta(minutes=10)


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up Bakalari sensors from a config entry."""

    children = ensure_children_dict(entry.options.get(CONF_CHILDREN, {}))
    entities = []
    for child_id, child_info in children.items():
        _LOGGER.warning(
            "Setting up Bakalari sensors for child %s with child_info: %s",
            child_id,
            redact_child_info(child_info),
        )
        entities.append(
            BakalariMessagesSensor(hass, entry, child_id, child_info.get("name", child_id))
        )
        entities.append(
            BakalariTimetableSensor(hass, entry, child_id, child_info.get("name", child_id))
        )
    async_add_entities(entities, update_before_add=True)


class BakalariMessagesSensor(SensorEntity):
    """Sensor for Bakalari messages for a specific child."""

    def __init__(self, hass: HomeAssistant, entry, child_id: str, child_name: str):
        """Initialize the sensors."""
        self._hass = hass
        self._entry = entry
        self._child_id = child_id
        self._child_name = child_name
        self._attr_name = f"Bakaláři zprávy {child_name}"
        self._attr_unique_id = f"bakalari_{child_id}_messages"
        self._attr_icon = "mdi:email"
        self._messages = []
        self._client = BakalariClient(hass, entry, child_id)

    @property
    def state(self):
        """Return the number of messages."""
        return len(self._messages)

    @property
    def extra_state_attributes(self):
        """Return the messages as attribute."""
        return {"messages": self._messages}

    async def async_update(self):
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


class BakalariTimetableSensor(SensorEntity):
    """Sensor for Bakalari timetable for a specific child."""

    def __init__(self, hass: HomeAssistant, entry, child_id: str, child_name: str):
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._child_id = child_id
        self._child_name = child_name
        self._attr_name = f"Bakaláři rozvrh {child_name}"
        self._attr_unique_id = f"bakalari_{child_id}_timetable"
        self._attr_icon = "mdi:calendar-clock"
        self._timetable = None
        self._client = BakalariClient(hass, entry, child_id)

    @property
    def state(self):
        """Return a simple state indicating availability or size."""
        if self._timetable is None:
            return 0
        try:
            return len(self._timetable)
        except Exception:
            return 1 if self._timetable else 0

    @property
    def extra_state_attributes(self):
        """Return the timetable as attribute."""
        return {"timetable": self._timetable}

    async def async_update(self):
        """Fetch timetable from Bakalari."""
        _LOGGER.warning(
            "[timetable.async_update] unique_id=%s self_id=%s client_id=%s child_id=%s client.child_id=%s",
            self._attr_unique_id,
            hex(id(self)),
            hex(id(self._client)),
            self._child_id,
            getattr(self._client, "child_id", None),
        )
        data = await self._client.async_get_timetable_actual()
        try:
            if hasattr(data, "as_json"):
                self._timetable = orjson.loads(data.as_json())
            else:
                self._timetable = data
        except Exception as e:
            _LOGGER.error("Failed to parse timetable: %s", e)
            self._timetable = None
