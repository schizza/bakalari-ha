"""Sensor platform for Bakalari - zprávy dítěte."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BakalariClient
from .const import CONF_CHILDREN, DOMAIN
from .coordinator import BakalariCoordinator
from .sensor_marks import (
    BakalariLastMarkSensor,
    BakalariNewMarksSensor,
)
from .utils import ensure_children_dict, redact_child_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up Bakalari sensors from a config entry."""

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coord: BakalariCoordinator = data["coordinator"]

    children = ensure_children_dict(entry.options.get(CONF_CHILDREN, {}))
    entities = []

    # Retain old entities for backward compatibility
    # We will delete them in the future, while they will use coordinator
    # and migration process will be done automatically
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
    # Setup new sensors that will use coordinator
    for child in coord.child_list:
        entities.append(BakalariNewMarksSensor(coord, child))
        entities.append(BakalariLastMarkSensor(coord, child))

    async_add_entities(entities, update_before_add=True)
