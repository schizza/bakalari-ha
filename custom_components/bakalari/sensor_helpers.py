"""Typed helper functions for Bakalari sensor setup and per-subject handling."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BakalariCoordinator, Child
from .sensor_marks import (
    BakalariAllMarksSensor,
    BakalariLastMarkSensor,
    BakalariNewMarksSensor,
    BakalariSubjectMarksSensor,
)
from .sensor_messages import BakalariMessagesSensor
from .sensor_timetable import BakalariTimetableSensor

__all__ = [
    "derive_subjects_from_data",
    "create_initial_entities",
    "create_subject_entities_for_child",
    "seed_created_subjects_from_data",
    "build_subjects_listener",
]


def derive_subjects_from_data(
    coord: BakalariCoordinator, child_key: str, data_now: dict[str, Any]
) -> list[tuple[str, str]]:
    """Return a list of tuples (subject_key, label) derived from current coordinator data.

    Subject key is stable priority order: subject_id or subject_abbr or subject_name or "unknown".
    Label prefers subject_abbr, then subject_name, finally the subject_key.

    Args:
        coord: Bakalari coordinator instance.
        child_key: Composite child key for which to derive subjects.
        data_now: Snapshot of coordinator.data (already dict or fallback {}).

    Returns:
        A list of (subject_key, label) pairs.

    """
    del coord  # currently unused, kept for signature stability
    subjects_map: dict[str, Any] = (data_now.get("subjects_by_child") or {}).get(
        child_key, {}
    ) or {}
    derived: list[tuple[str, str]] = []

    if isinstance(subjects_map, dict) and subjects_map:
        for s in list(subjects_map.values()):
            sid = str(s.get("id") or s.get("subject_id") or s.get("subject") or "").strip() or None
            sabbr = str(s.get("abbr") or s.get("subject_abbr") or "").strip()
            sname = str(s.get("name") or s.get("subject_name") or "").strip()
            skey = sid or sabbr or sname or "unknown"
            label = sabbr or sname or skey
            derived.append((skey, label))
        return derived

    marks: Sequence[dict[str, Any]] = (data_now.get("marks_flat_by_child") or {}).get(
        child_key, []
    ) or []
    seen_keys: set[str] = set()
    for it in marks:
        sid = str(it.get("subject_id") or it.get("subject") or "").strip() or None
        sabbr = str(it.get("subject_abbr") or "").strip()
        sname = str(it.get("subject_name") or "").strip()
        skey = sid or sabbr or sname or "unknown"
        if skey in seen_keys:
            continue
        seen_keys.add(skey)
        label = sabbr or sname or skey
        derived.append((skey, label))

    return derived


def create_initial_entities(coord: BakalariCoordinator, child: Child) -> list[SensorEntity]:
    """Create base sensors (marks overview, messages, timetable) for a child.

    Args:
        coord: Bakalari coordinator instance.
        child: Child descriptor.

    Returns:
        List of initial SensorEntity instances.

    """
    ents: list[SensorEntity] = [
        BakalariNewMarksSensor(coord, child),
        BakalariLastMarkSensor(coord, child),
        BakalariAllMarksSensor(coord, child),
        BakalariMessagesSensor(coord, child),
        BakalariTimetableSensor(coord, child),
    ]
    return ents


def create_subject_entities_for_child(
    coord: BakalariCoordinator, child: Child, data_now: dict[str, Any]
) -> list[SensorEntity]:
    """Create per-subject mark sensors for a child based on current data.

    Args:
        coord: Bakalari coordinator instance.
        child: Child descriptor.
        data_now: Snapshot of coordinator.data (already dict or fallback {}).

    Returns:
        List of per-subject SensorEntity instances.

    """
    ents: list[SensorEntity] = []
    for skey, label in derive_subjects_from_data(coord, child.key, data_now):
        ents.append(BakalariSubjectMarksSensor(coord, child, skey, label))
    return ents


def seed_created_subjects_from_data(
    coord: BakalariCoordinator, data_now: dict[str, Any]
) -> dict[str, set[str]]:
    """Initialize a mapping child_key -> set(subject_key) from the current data snapshot.

    Args:
        coord: Bakalari coordinator instance.
        data_now: Snapshot of coordinator.data (already dict or fallback {}).

    Returns:
        Mapping of child composite key to the set of known subject keys.

    """

    created: dict[str, set[str]] = {}
    for ch in coord.child_list:
        keys = {skey for (skey, _label) in derive_subjects_from_data(coord, ch.key, data_now)}
        created[ch.key] = set(keys)
    return created


def build_subjects_listener(
    coord: BakalariCoordinator,
    created_subjects: dict[str, set[str]],
    async_add_entities: AddEntitiesCallback,
) -> Callable[[], None]:
    """Build a listener that adds new per-subject sensors when new subjects appear.

    Args:
        coord: Bakalari coordinator instance.
        created_subjects: Mutable map child_key -> set(subject_key) tracking already created sensors.
        async_add_entities: Home Assistant callback to add new entities.

    Returns:
        A zero-arg callable to register with coordinator's update listener API.

    """

    def _on_coordinator_update() -> None:
        data_now: dict[str, Any] = coord.data or {}
        to_add: list[SensorEntity] = []
        for child in coord.child_list:
            existing = created_subjects.setdefault(child.key, set())
            for skey, label in derive_subjects_from_data(coord, child.key, data_now):
                if skey in existing:
                    continue
                to_add.append(BakalariSubjectMarksSensor(coord, child, skey, label))
                existing.add(skey)
        if to_add:
            async_add_entities(to_add)

    return _on_coordinator_update
