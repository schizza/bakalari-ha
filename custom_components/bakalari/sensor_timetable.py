"""Coordinator-based timetable sensor for Bakalari."""

from __future__ import annotations

from typing import Any, cast

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity


def _get_timetable_for_child(coord: BakalariCoordinator, child_key: str) -> list[Any]:
    """Get timetable list (weeks) for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("timetable_by_child") or {}
    items: list[Any] = by_child.get(child_key, []) or []
    return items


def _resolve_child_by_option_key(coord: BakalariCoordinator, option_key: str) -> Child | None:
    """Find Child by original options key (e.g., user_id) using coordinator mapping."""
    mapping = coord.option_key_by_child_key
    for ck, ok in mapping.items():
        if str(ok) == str(option_key):
            for ch in coord.child_list:
                if ch.key == ck:
                    return ch
            break
    return None


class BakalariTimetableSensor(BakalariEntity, SensorEntity):
    """Sensor showing timetable info for a specific child, backed by the coordinator."""

    _attr_icon = "mdi:calendar-clock"
    _attr_has_entity_name = True

    def __init__(  # type: ignore[override]
        self,
        *args: Any,
    ) -> None:
        """Initialize the sensor.

        Supports two initialization modes for backward compatibility:
        1) New: BakalariTimetableSensor(coordinator: BakalariCoordinator, child: Child)
        2) Legacy: BakalariTimetableSensor(hass: HomeAssistant, entry: ConfigEntry, child_id: str, child_name: str)
        """
        # New style: (coordinator, child)
        if args and isinstance(args[0], BakalariCoordinator):
            coordinator = cast(BakalariCoordinator, args[0])
            child = cast(Child, args[1])
            super().__init__(coordinator, child)
            self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:timetable"
            self._attr_name = "Rozvrh"
            return

        # Legacy style: (hass, entry, child_id, child_name)
        hass = cast(HomeAssistant, args[0])
        entry = cast(config_entries.ConfigEntry, args[1])
        child_id = cast(str, args[2])
        # child_name is accepted but unused; device provides the child context
        _child_name = cast(str, args[3]) if len(args) > 3 else ""

        data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
        coord = cast(BakalariCoordinator, data.get("coordinator"))
        if not coord or not coord.child_list:
            raise RuntimeError("Coordinator not available for Bakalari timetable sensor")

        child = _resolve_child_by_option_key(coord, child_id) or coord.child_list[0]
        super().__init__(coord, child)
        self._attr_unique_id = f"{coord.entry.entry_id}:{child.key}:timetable"
        self._attr_name = "Rozvrh"

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
