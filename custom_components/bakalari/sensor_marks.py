"""Marks sensors for Bakalari."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity

from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity


def _get_items_for_child(coord: BakalariCoordinator, child_key: str) -> list[dict[str, Any]]:
    """Get marks list for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("marks_by_child") or {}
    items: list[dict[str, Any]] = by_child.get(child_key, []) or []
    return items


class BakalariNewMarksSensor(BakalariEntity, SensorEntity):
    """Sensor showing count of new marks for a specific child."""

    _attr_icon = "mdi:school"
    _attr_translation_key = "new_marks"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:new_marks"
        self._attr_name = "Nové známky"

    @property
    def native_value(self) -> int:
        """Return the count of new marks for the child."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        # Prefer explicit "is_new" flag if provided by API; otherwise fall back to 0
        return sum(1 for it in items if bool(it.get("is_new")))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        recent = items[:5] if items else []
        return {
            "child_key": self.child.key,
            "recent": recent,
            "total_marks_cached": len(items),
        }


class BakalariLastMarkSensor(BakalariEntity, SensorEntity):
    """Sensor exposing a short text of the most recent mark for a specific child."""

    _attr_icon = "mdi:bookmark"
    _attr_translation_key = "last_mark"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:last_mark"
        self._attr_name = "Poslední známka"

    @property
    def native_value(self) -> str | None:
        """Return the native value of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        if not items:
            return None
        last = items[0]
        subject = (last.get("subject_abbr") or last.get("subject_name") or "").strip()
        text = (last.get("mark_text") or last.get("points_text") or "").strip()
        value = f"{subject} {text}".strip()
        return value or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        last = items[0] if items else None
        return {
            "child_key": self.child.key,
            "last": last,
        }
