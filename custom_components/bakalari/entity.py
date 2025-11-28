"""Base entity bound to the Bakalari coordinator and a specific child."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .children import Child
from .const import MANUFACTURER, MODEL, SW_VERSION
from .utils import device_ident


class BakalariEntity(CoordinatorEntity[DataUpdateCoordinator]):
    """Base entity bound to the Bakalari coordinator and a specific child."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, child: Child) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self.child = child
        entry = getattr(coordinator, "entry", None)
        entry_id = getattr(entry, "entry_id", "unknown")
        self._entry_id = entry_id
        self._device_ident = device_ident(entry_id, child.key)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information for the specific child."""
        return {
            "identifiers": {self._device_ident},
            "manufacturer": MANUFACTURER,
            "name": f"Bakaláři – {self.child.display_name}",
            "model": MODEL,
            "sw_version": SW_VERSION,
        }
