"""Marks sensors for Bakalari."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity

from .coordinator import BakalariCoordinator, Child
from .entity import BakalariEntity
from .sensor_helpers import (
    _get_items_for_child,
    aggregate_marks_for_child,
    get_child_subjects,
    sanitize,
)

_LOGGER = logging.getLogger(__name__)


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


class BakalariSubjectMarksSensor(BakalariEntity, SensorEntity):
    """Per-subject sensor exposing mark count and basic stats for a single subject."""

    _attr_icon = "mdi:book-education-outline"
    _attr_translation_key = "subject_marks"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BakalariCoordinator,
        child: Child,
        subject_id: str,
        subject_abbr: str,
        label: str | None = None,
    ) -> None:
        """Initialize the sensor for a specific subject."""
        super().__init__(coordinator, child)
        self._subject_key = subject_id
        self._subject_abbr: str = subject_abbr
        display = (label or self._subject_abbr).strip()
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}:{child.key}:subject:{sanitize(self._subject_key)}"
        )
        self._attr_name = f"Známky {display} - {child.short_name}"
        self._friendly_name = f" Známky {display} - {child.short_name}"

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
        agg = aggregate_marks_for_child(self.coordinator, self.child.key, items)
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


class BakalariIndexHelperSensor(BakalariEntity, SensorEntity):
    """Create helper sensor for mapping subjects to their sensors."""

    _attr_icon = "mdi:book-education"
    _attr_translation_key = "index_helper"
    _attr_has_entity_name = True

    def __init__(self, coordinator: BakalariCoordinator, child: Child) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, child)
        self._attr_unique_id = f"{coordinator.entry.entry_id}:{child.key}:marks_helper"
        self._attr_name = f"Helper - Známky - {child.short_name}"

    @property
    def native_value(self) -> int:
        """Return total subjects for child."""
        items = aggregate_marks_for_child(self.coordinator, self.child.key)
        return len(items["by_subject"])

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""

        return get_child_subjects(self.coordinator, self.child)


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
