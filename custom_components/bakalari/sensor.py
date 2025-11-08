"""Sensor platform for Bakalari - zprávy dítěte."""

from __future__ import annotations

import logging
import re

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHILDREN, CONF_SERVER, CONF_USER_ID, DOMAIN
from .coordinator import BakalariCoordinator
from .sensor_helpers import (
    build_subjects_listener,
    create_initial_entities,
    create_subject_entities_for_child,
    seed_created_subjects_from_data,
)
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
    data_now = coord.data or {}

    # Base sensors and initial per-subject sensors
    for child in coord.child_list:
        entities.extend(create_initial_entities(coord, child))
        try:
            entities.extend(create_subject_entities_for_child(coord, child, data_now))
        except Exception:
            _LOGGER.exception("Failed to create per-subject sensors for child_key=%s", child.key)

    async_add_entities(entities, update_before_add=True)

    # Dynamic per-subject sensors (no reload required)
    created_subjects = seed_created_subjects_from_data(coord, data_now)
    coord.async_add_listener(build_subjects_listener(coord, created_subjects, async_add_entities))


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
