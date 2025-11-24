"""Coordinator-based timetable sensor for Bakalari."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity

from .children import Child
from .entity import BakalariEntity


def _get_timetable_for_child(coord: Any, child_key: str) -> list[Any]:
    """Get timetable list (weeks) for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("timetable_by_child") or {}
    items: list[Any] = by_child.get(child_key, []) or []
    return items


class BakalariTimetableSensor(BakalariEntity, SensorEntity):
    """Sensor showing timetable info for a specific child, backed by the coordinator."""

    _attr_icon = "mdi:calendar-clock"
    _attr_has_entity_name = True

    def __init__(self, coordinator: Any, child: Child) -> None:
        """Initialize the sensor for a specific child."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:timetable"
        self._attr_name = f"Rozvrh - {child.short_name}"

    async def async_added_to_hass(self) -> None:
        """Initialize the sensor for a specific child."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def native_value(self) -> int:
        """Return number of weeks cached for the child's timetable."""
        items = _get_timetable_for_child(self.coordinator, self.child.key)
        try:
            return len(items)
        except Exception:
            return 1 if items else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the timetable as attributes for advanced use."""
        items = _get_timetable_for_child(self.coordinator, self.child.key)
        return {
            "child_key": self.child.key,
            "timetable": items,
            "total_weeks_cached": len(items) if isinstance(items, list) else 0,
        }
