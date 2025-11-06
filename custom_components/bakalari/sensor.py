"""Sensor platform for Bakalari - zprávy dítěte."""

from __future__ import annotations

import logging
import re

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHILDREN, CONF_SERVER, CONF_USER_ID, DOMAIN
from .coordinator import BakalariCoordinator
from .sensor_marks import (
    BakalariAllMarksSensor,
    BakalariLastMarkSensor,
    BakalariNewMarksSensor,
)
from .sensor_messages import BakalariMessagesSensor
from .sensor_timetable import BakalariTimetableSensor
from .utils import ensure_children_dict, make_child_key

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up Bakalari sensors from a config entry."""

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coord: BakalariCoordinator = data["coordinator"]

    entities = []

    # Legacy messages/timetable sensors have been removed; unique_id migration is handled at platform level.
    # Setup new sensors that will use coordinator
    for child in coord.child_list:
        entities.append(BakalariNewMarksSensor(coord, child))
        entities.append(BakalariLastMarkSensor(coord, child))
        entities.append(BakalariAllMarksSensor(coord, child))
        entities.append(BakalariMessagesSensor(coord, child))
        entities.append(BakalariTimetableSensor(coord, child))

    async_add_entities(entities, update_before_add=True)


async def async_migrate_entity_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    entity_entry,
):
    """Migrate unique_id from 'bakalari_<child_id>_(messages|timetable)' to '<entry_id>:<child_key>:(messages|timetable)'."""
    uid = entity_entry.unique_id or ""
    m = re.fullmatch(r"bakalari_(?P<cid>.+)_(?P<what>messages|timetable)", uid)
    if not m:
        return None

    opt_key = m.group("cid")
    what = m.group("what")

    # Build composite child key from options
    children = ensure_children_dict(config_entry.options.get(CONF_CHILDREN, {}))
    child_key = None
    for cid, cr in children.items():
        user_id = str(cr.get(CONF_USER_ID) or cid)
        if str(cid) == opt_key or user_id == opt_key:
            server = (cr.get(CONF_SERVER) or "").strip()
            if server and user_id:
                child_key = make_child_key(server, user_id)
                break

    if not child_key:
        return None

    new_unique_id = f"{config_entry.entry_id}:{child_key}:{what}"
    return {"new_unique_id": new_unique_id}
