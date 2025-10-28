"""Sensor for Bakalari - rozvrh dítěte."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.util import dt

from .api import BakalariClient

_LOGGER = logging.getLogger(__name__)


class BakalariTimetableSensor(SensorEntity):
    """Sensor for Bakalari timetable for a specific child."""

    def __init__(
        self, hass: HomeAssistant, entry: config_entries.ConfigEntry, child_id: str, child_name: str
    ) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._child_id = child_id
        self._child_name = child_name
        # Keep short, child will be visible at device level
        self._attr_name = "Bakaláři rozvrh"
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

    async def async_update(self) -> None:
        """Fetch timetable from Bakalari."""
        _LOGGER.warning(
            "[timetable.async_update] unique_id=%s self_id=%s client_id=%s child_id=%s client.child_id=%s",
            self._attr_unique_id,
            hex(id(self)),
            hex(id(self._client)),
            self._child_id,
            getattr(self._client, "child_id", None),
        )
        today = dt.now().date()
        dates = [today, today + timedelta(weeks=1), today - timedelta(weeks=1)]
        weeks = []
        for d in dates:
            w = await self._client.async_get_timetable_actual(d)
            weeks.append(w)

        self._timetable = weeks
