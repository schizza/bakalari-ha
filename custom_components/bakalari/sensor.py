"""Sensor platform for Bakalari - zprávy dítěte."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHILDREN, CONF_SERVER, CONF_USER_ID, DOMAIN
from .coordinator_marks import BakalariMarksCoordinator
from .sensor_helpers import (
    build_subjects_listener,
    get_child_subjects,
    seed_created_subjects_from_data,
)
from .sensor_marks import (
    BakalariIndexHelperSensor,
    BakalariLastMarkSensor,
    BakalariNewMarksSensor,
    BakalariSubjectMarksSensor,
)
from .sensor_messages import BakalariMessagesSensor
from .sensor_timetable import BakalariTimetableSensor
from .utils import ensure_children_dict, make_child_key

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up Bakalari sensors from a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    children = data["children"].children
    coord_marks: BakalariMarksCoordinator = data["marks"]
    coord_msgs = data.get("messages")
    coord_tt = data.get("timetable")

    entities = []
    data_now = coord_marks.data or {}

    # Create sensors for children.
    for child in children:
        # Base senors
        _LOGGER.debug(
            "[class=%s module=%s] Creating base sensors for child %s",
            async_setup_entry.__qualname__,
            __name__,
            child,
        )
        entities.append(BakalariNewMarksSensor(coord_marks, child))
        entities.append(BakalariLastMarkSensor(coord_marks, child))
        if coord_msgs is not None:
            entities.append(BakalariMessagesSensor(coord_msgs, child))
        if coord_tt is not None:
            entities.append(BakalariTimetableSensor(coord_tt, child))
        entities.append(BakalariIndexHelperSensor(coord_marks, child))

        # Per-subject sensors
        subjects_dict: dict[str, Any] = get_child_subjects(coord_marks, child)
        _LOGGER.debug(
            "[class=%s module=%s] Setting up subjects for child: %s: %s",
            async_setup_entry.__qualname__,
            __name__,
            child,
            subjects_dict.get("friendly_names", {}),
        )

        subjects: dict[str, dict[str, Any]] = subjects_dict.get("mapping_names", {})
        subj_sensors: list[dict[str, str]] = [
            {"id": s_id, "abbr": s_data["abbr"]} for s_id, s_data in subjects.items()
        ]

        entities.extend(
            BakalariSubjectMarksSensor(
                coord_marks, child, subject_sensor["id"], subject_sensor["abbr"]
            )
            for subject_sensor in subj_sensors
        )

    async_add_entities(entities, update_before_add=True)

    # Dynamic per-subject sensors (no reload required)
    created_subjects = seed_created_subjects_from_data(coord_marks, data_now)
    coord_marks.async_add_listener(
        build_subjects_listener(coord_marks, created_subjects, async_add_entities)
    )


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
