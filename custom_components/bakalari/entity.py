"""Base entity bound to the Bakalari coordinator and a specific child."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MANUFACTURER, MODEL
from .coordinator import BakalariCoordinator, Child
from .utils import device_ident


class BakalariEntity(CoordinatorEntity[BakalariCoordinator]):
    """Base entity bound to the Bakalari coordinator and a specific child."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self.child = child
        self._device_ident = device_ident(coordinator.entry.entry_id, child.key)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the specific child."""
        return {
            "identifiers": {self._device_ident},
            "manufacturer": MANUFACTURER,
            "name": f"Bakaláři – {self.child.display_name}",
            "model": MODEL,
            "sw_version": self.coordinator.api_version,
        }
