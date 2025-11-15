"""Typed helper functions for Bakalari sensor setup and per-subject handling."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BakalariCoordinator, Child

_LOGGER = logging.getLogger(__name__)


def _subjects_sensors_map(coordinator: BakalariCoordinator, child: Child) -> dict[str, str]:
    """Generate a mapping of sensors names to subject names."""
    entry_id = coordinator.entry.entry_id

    reg = er.async_get(coordinator.hass)
    result: dict[str, str] = {}
    for ent in reg.entities.values():
        if ent.config_entry_id != entry_id:
            continue
        if ent.domain != "sensor" or ent.platform != "bakalari":
            continue

        uid = ent.unique_id
        needle = f":{child.key}:subject:"
        if needle not in uid:
            continue

        subject_key = uid.split(":subject:", 1)[1]
        name = (
            ent.entity_id
        )  #  or we can fetch getattr(ent, "original_name", None) or getattr(ent, "name", None)

        result[str(subject_key)] = name

    return result


def get_child_subjects(coordinator: BakalariCoordinator, child: Child) -> dict[str, Any]:
    """Get childs subjects."""

    data = coordinator.data

    subjs: dict[str, dict[str, Any]] = data.get("subjects_by_child", {}).get(child.key, {})
    if not subjs:
        _LOGGER.error("No subjects found for child %s. Data received: %s", child.key, subjs)
        return {}

    friendly_names: list[str] = [subj["name"].strip() for subj in subjs.values()]

    mapping_names: dict[str, dict[str, Any]] = {
        mapping["id"].strip(): {"name": mapping["name"].strip(), "abbr": mapping["abbr"].strip()}
        for mapping in subjs.values()
    }

    sensor_map: dict[str, str] = _subjects_sensors_map(coordinator, child)

    _LOGGER.error("get_child_subjects: %s", friendly_names)

    return {
        "friendly_names": friendly_names,
        "mapping_names": mapping_names,
        "sensor_map": sensor_map,
        "summary": data.get("summary", {}).get(child.key, {}),
    }


def derive_subjects_from_data(data: dict[str, Any], child_key: str) -> list[tuple[str, str]]:
    """Return a list of tuples (subject_key, label) derived from current coordinator data.

    Subject key is stable priority order: subject_id or subject_abbr or subject_name or "unknown".
    Label prefers subject_abbr, then subject_name, finally the subject_key.

    Args:
        data: Snapshot of coordinator.data
        child_key: Composite child key for which to derive subjects.

    Returns:
        A list of (subject_key, label) pairs.

    """
    subjects_map: dict[str, Any] = (data.get("subjects_by_child") or {}).get(child_key, {}) or {}
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

    marks: Sequence[dict[str, Any]] = (data.get("marks_flat_by_child") or {}).get(
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


def create_subject_entities_for_child(
    coord: BakalariCoordinator, child: Child, data_now: dict[str, Any]
) -> list[tuple[str, str]]:
    """Create per-subject mark sensors for a child based on current data.

    Args:
        coord: Bakalari coordinator instance.
        child: Child descriptor.
        data_now: Snapshot of coordinator.data (already dict or fallback {}).

    Returns:
        List of per-subject SensorEntity instances.

    """
    return derive_subjects_from_data(data_now, child.key)


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
        keys = {skey for (skey, _label) in derive_subjects_from_data(coord.data, ch.key)}
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
        to_add: list[SensorEntity] = []
        for child in coord.child_list:
            existing = created_subjects.setdefault(child.key, set())
            for skey, _label in derive_subjects_from_data(coord.data, child.key):
                if skey in existing:
                    continue
                # to_add.append(BakalariSubjectMarksSensor(coord, child, skey, label))
                existing.add(skey)
        if to_add:
            async_add_entities(to_add)

    return _on_coordinator_update


def sanitize(sanitize: str) -> str:
    """Return sanitized slug."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", sanitize)


def aggregate_marks_for_child(
    coord: BakalariCoordinator, child_key: str, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Aggregate marks by subject and compute overall statistics for a child."""
    if not items:
        items = _get_items_for_child(coord, child_key)

    by_subject: dict[str, dict[str, Any]] = {}
    total = len(items)
    new_count = 0
    overall_numeric = 0
    overall_non_numeric = 0
    overall_sum = 0.0
    overall_wsum = 0.0
    overall_w = 0.0

    for it in items:
        subj_id = str(it.get("subject_id") or it.get("subject") or "").strip() or None
        subj_abbr = str(it.get("subject_abbr") or "").strip()
        subj_name = str(it.get("subject_name") or "").strip()
        subj_key = subj_id or subj_abbr or subj_name or "unknown"

        if subj_key not in by_subject:
            by_subject[subj_key] = {
                "subject_id": subj_id,
                "subject_key": subj_key,
                "subject_abbr": subj_abbr or None,
                "subject_name": subj_name or None,
                "count": 0,
                "new_count": 0,
                "numeric_count": 0,
                "non_numeric_count": 0,
                "sum": 0.0,
                "wsum": 0.0,
                "weight": 0.0,
                "last_text": None,
                "last_date": None,
            }

        agg = by_subject[subj_key]
        agg["count"] += 1
        if it.get("is_new"):
            agg["new_count"] += 1
            new_count += 1

        val, w = _parse_numeric_mark(it)
        if val is None:
            agg["non_numeric_count"] += 1
            overall_non_numeric += 1
        else:
            agg["numeric_count"] += 1
            agg["sum"] += val
            agg["wsum"] += val * (w or 1.0)
            agg["weight"] += w or 1.0
            overall_numeric += 1
            overall_sum += val
            overall_wsum += val * (w or 1.0)
            overall_w += w or 1.0

        # Keep the latest mark info per subject (items are expected in descending time order)
        if agg["last_text"] is None:
            last_text = (it.get("mark_text") or it.get("points_text") or "").strip() or None
            last_date = it.get("date") or it.get("created") or it.get("inserted") or None
            agg["last_text"] = last_text
            agg["last_date"] = last_date

    # Finalize averages
    subjects: list[dict[str, Any]] = []
    for s in by_subject.values():
        n = s["numeric_count"]
        w = s["weight"]
        s["avg"] = round(s["sum"] / n, 3) if n > 0 else None
        s["wavg"] = round(s["wsum"] / w, 3) if w and w > 0 else s["avg"]
        # Remove intermediate sums to keep attributes small but useful
        del s["sum"]
        del s["wsum"]
        del s["weight"]
        subjects.append(s)

    # Sort subjects naturally: first by abbr, then by name
    subjects.sort(key=lambda s: (s.get("subject_abbr") or "", s.get("subject_name") or ""))

    overall = {
        "total": total,
        "new_count": new_count,
        "numeric_count": overall_numeric,
        "non_numeric_count": overall_non_numeric,
        "average": round(overall_sum / overall_numeric, 3) if overall_numeric > 0 else None,
        "weighted_average": round(overall_wsum / overall_w, 3) if overall_w > 0 else None,
    }

    return {
        "overall": overall,
        "by_subject": subjects,
        "recent": items[:20] if items else [],
    }


def _parse_numeric_mark(item: dict[str, Any]) -> tuple[float | None, float]:
    """Extract numeric value and optional weight from a mark item. Returns (value, weight)."""
    # Direct numeric fields (prefer explicit numeric values if present)
    for key in ("value", "numeric_value", "mark_value"):
        v = item.get(key)
        if isinstance(v, int | float):
            w_raw = item.get("weight") or item.get("coef") or item.get("coefficient")
            try:
                w = float(w_raw) if w_raw is not None and str(w_raw).strip() != "" else 1.0
            except Exception:  # noqa: BLE001
                w = 1.0
            return float(v), w

    # Parse from text fields (e.g., "1-", "2+", "15/20", "18 b.") - take the first number found
    txt = str(item.get("mark_text") or item.get("points_text") or "").strip()
    m = re.search(r"(\d+[.,]?\d*)", txt)
    if not m:
        return None, 0.0
    try:
        val = float(m.group(1).replace(",", "."))
    except Exception:  # noqa: BLE001
        return None, 0.0

    w_raw = item.get("weight") or item.get("coef") or item.get("coefficient")
    try:
        w = float(w_raw) if w_raw is not None and str(w_raw).strip() != "" else 1.0
    except Exception:  # noqa: BLE001
        w = 1.0
    return val, w


def _get_items_for_child(coord: BakalariCoordinator, child_key: str) -> list[dict[str, Any]]:
    """Get marks list for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("marks_by_child") or {}
    items: list[dict[str, Any]] = by_child.get(child_key, []) or []
    return items
