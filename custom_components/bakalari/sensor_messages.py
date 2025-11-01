"""Coordinator-based messages sensor for Bakalari."""

from __future__ import annotations

from typing import Any, cast

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity


def _get_messages_for_child(coord: BakalariCoordinator, child_key: str) -> list[dict[str, Any]]:
    """Get messages list for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("messages_by_child") or {}
    items: list[dict[str, Any]] = by_child.get(child_key, []) or []
    return items


def _resolve_child_by_option_key(coord: BakalariCoordinator, option_key: str) -> Child | None:
    """Find Child by original options key (e.g., user_id)."""
    mapping = coord.option_key_by_child_key
    for ck, ok in mapping.items():
        if str(ok) == str(option_key):
            for ch in coord.child_list:
                if ch.key == ck:
                    return ch
            break
    return None


class BakalariMessagesSensor(BakalariEntity, SensorEntity):
    """Sensor showing messages count for a specific child."""

    _attr_icon = "mdi:email"
    _attr_has_entity_name = True

    def __init__(  # type: ignore[override]
        self,
        *args: Any,
    ) -> None:
        """Initialize the sensor.

        Supports two initialization modes for backward compatibility:
        1) New: BakalariMessagesSensor(coordinator: BakalariCoordinator, child: Child)
        2) Legacy: BakalariMessagesSensor(hass: HomeAssistant, entry: ConfigEntry, child_id: str, child_name: str)
        """
        # New style: (coordinator, child)
        if args and isinstance(args[0], BakalariCoordinator):
            coordinator = cast(BakalariCoordinator, args[0])
            child = cast(Child, args[1])
            super().__init__(coordinator, child)
            self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:messages"
            self._attr_name = f"Zprávy - {child.short_name}"
            return

        # Legacy style: (hass, entry, child_id, child_name)
        hass = cast(HomeAssistant, args[0])
        entry = cast(config_entries.ConfigEntry, args[1])
        child_id = cast(str, args[2])
        # child_name is intentionally ignored for entity naming; device provides child context
        # but we keep accepting it to avoid breaking imports/constructors
        _child_name = cast(str, args[3]) if len(args) > 3 else ""

        data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
        coord = cast(BakalariCoordinator, data.get("coordinator"))
        if not coord or not coord.child_list:
            # Fallback: initialize with a dummy first child-like behavior
            # This should be extremely rare; coordinator is created in __init__.py
            raise RuntimeError("Coordinator not available for Bakalari messages sensor")

        child = _resolve_child_by_option_key(coord, child_id) or coord.child_list[0]
        super().__init__(coord, child)

        # Use new unique_id scheme to allow entity_registry migration later
        self._attr_unique_id = f"{coord.entry.entry_id}:{child.key}:messages"
        self._attr_name = f"Zprávy - {child.short_name}"

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
