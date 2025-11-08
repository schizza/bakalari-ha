"""Marks sensors for Bakalari."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from sensor_helpers import sanitize

from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity


def _get_items_for_child(coord: BakalariCoordinator, child_key: str) -> list[dict[str, Any]]:
    """Get marks list for the child from coordinator data."""
    data = coord.data or {}
    by_child = data.get("marks_by_child") or {}
    items: list[dict[str, Any]] = by_child.get(child_key, []) or []
    return items


class BakalariNewMarksSensor(BakalariEntity, SensorEntity):
    """Sensor showing count of new marks for a specific child."""

    _attr_icon = "mdi:school"
    _attr_translation_key = "new_marks"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:new_marks"
        self._attr_name = f"Nové známky - {child.short_name}"

    @property
    def native_value(self) -> int:
        """Return the count of new marks for the child."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        # Prefer explicit "is_new" flag if provided by API; otherwise fall back to 0
        return sum(1 for it in items if bool(it.get("is_new")))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        recent = items[:5] if items else []
        return {
            "child_key": self.child.key,
            "recent": recent,
            "total_marks_cached": len(items),
        }


class BakalariLastMarkSensor(BakalariEntity, SensorEntity):
    """Sensor exposing a short text of the most recent mark for a specific child."""

    _attr_icon = "mdi:bookmark"
    _attr_translation_key = "last_mark"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:last_mark"
        self._attr_name = f"Poslední známka - {child.short_name}"

    @property
    def native_value(self) -> str | None:
        """Return the native value of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        if not items:
            return None
        last = items[0]
        subject = (last.get("subject_abbr") or last.get("subject_name") or "").strip()
        text = (last.get("mark_text") or last.get("points_text") or "").strip()
        value = f"{subject} {text}".strip()
        return value or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes of the sensor."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        last = items[0] if items else None
        return {
            "child_key": self.child.key,
            "last": last,
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


def _aggregate_marks_for_child(
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


class BakalariSubjectMarksSensor(BakalariEntity, SensorEntity):
    """Per-subject sensor exposing mark count and basic stats for a single subject."""

    _attr_icon = "mdi:book-education-outline"
    _attr_translation_key = "subject_marks"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BakalariCoordinator,
        child: Child,
        subject_key: str,
        label: str | None = None,
    ) -> None:
        """Initialize the sensor for a specific subject."""
        super().__init__(coordinator, child)
        self._subject_key = str(subject_key).strip()
        display = (label or self._subject_key).strip() or "Předmět"
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}:{child.key}:subject:{sanitize(self._subject_key)}"
        )
        self._attr_name = f"Známky {display} - {child.short_name}"

    def _matches_subject(self, item: dict[str, Any]) -> bool:
        """Return True if the given mark item belongs to this sensor's subject."""
        subj_id = str(item.get("subject_id") or item.get("subject") or "").strip() or None
        subj_abbr = str(item.get("subject_abbr") or "").strip()
        subj_name = str(item.get("subject_name") or "").strip()
        key = subj_id or subj_abbr or subj_name or "unknown"
        return key == self._subject_key

    @property
    def native_value(self) -> int:
        """Return total number of marks for this subject."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        sitems = [it for it in items if self._matches_subject(it)]
        return len(sitems)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return subject details, stats and recent marks."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        agg = _aggregate_marks_for_child(self.coordinator, self.child.key, items)
        subjects = agg.get("by_subject", []) or []
        info = next(
            (s for s in subjects if s.get("subject_key") == self._subject_key),
            None,
        )

        # Collect recent marks for this subject (limit to 30 to keep attributes manageable)
        sitems = [it for it in items if self._matches_subject(it)]
        recent = sitems[:30] if sitems else []

        return {
            "child_key": self.child.key,
            "subject_key": self._subject_key,
            "subject": info,
            "recent": recent,
        }


class BakalariAllMarksSensor(BakalariEntity, SensorEntity):
    """Comprehensive sensor exposing all marks per child with per-subject aggregation."""

    _attr_icon = "mdi:book-education"
    _attr_translation_key = "all_marks"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:all_marks"
        self._attr_name = f"Všechny známky - {child.short_name}"

    @property
    def native_value(self) -> int:
        """Return total number of marks for the child."""
        items = _get_items_for_child(self.coordinator, self.child.key)
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return aggregated attributes - overall stats and per-subject breakdown."""
        agg = _aggregate_marks_for_child(self.coordinator, self.child.key)
        overall = agg.get("overall", {})
        return {
            "child_key": self.child.key,
            "total": overall.get("total"),
            "new_count": overall.get("new_count"),
            "numeric_count": overall.get("numeric_count"),
            "non_numeric_count": overall.get("non_numeric_count"),
            "average": overall.get("average"),
            "weighted_average": overall.get("weighted_average"),
            "by_subject": agg.get("by_subject", []),
            "recent": agg.get("recent", []),
        }
