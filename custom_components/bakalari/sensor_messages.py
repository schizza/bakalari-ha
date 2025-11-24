"""Coordinator-based messages sensor for Bakalari."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity

from .children import Child
from .entity import BakalariEntity


def _get_messages_for_child(coord: Any, child_key: str) -> list[dict[str, Any]]:
    """Get messages list for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("messages_by_child") or {}
    items: list[dict[str, Any]] = by_child.get(child_key, []) or []
    return items


class BakalariMessagesSensor(BakalariEntity, SensorEntity):
    """Sensor showing messages count for a specific child."""

    _attr_icon = "mdi:email"
    _attr_has_entity_name = True

    def __init__(self, coordinator: Any, child: Child) -> None:
        """Initialize the sensor for a specific child."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:messages"
        self._attr_name = f"Zprávy - {child.short_name}"

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @property
    def native_value(self) -> int:
        """Return the number of messages for the child."""
        items = _get_messages_for_child(self.coordinator, self.child.key)
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the messages as attributes for advanced use."""
        items = _get_messages_for_child(self.coordinator, self.child.key)
        return {
            "child_key": self.child.key,
            "messages": items,
            "total_messages_cached": len(items),
        }
