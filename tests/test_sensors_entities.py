"""Tests for sensor entities: messages, timetable, marks (new, last, all) and per-subject."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.helpers import frame as ha_frame
import pytest

from custom_components.bakalari.const import (
    CONF_CHILDREN,
    CONF_SERVER,
    CONF_USER_ID,
)
from custom_components.bakalari.coordinator import BakalariCoordinator, Child
from custom_components.bakalari.sensor_marks import (
    BakalariAllMarksSensor,
    BakalariLastMarkSensor,
    BakalariNewMarksSensor,
    BakalariSubjectMarksSensor,
)
from custom_components.bakalari.sensor_messages import BakalariMessagesSensor
from custom_components.bakalari.sensor_timetable import BakalariTimetableSensor


class FakeBus:
    """Fake HA bus."""

    def __init__(self) -> None:
        """Initialize FakeBus."""
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Fire an event."""
        self.events.append((event_type, event_data))


class FakeHass:
    """Minimal fake Home Assistant core."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize FakeHass."""
        self.loop = loop
        self.bus = FakeBus()

    def async_create_task(self, coro):
        """Create a task."""
        return self.loop.create_task(coro)


class FakeConfigEntry:
    """Minimal fake ConfigEntry."""

    def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
        """Initialize FakeConfigEntry."""
        self.entry_id = entry_id
        self.options = options
        self.domain = "bakalari"


def _make_child_options(server: str, user_id: str, **extra: Any) -> dict[str, Any]:
    """Create a minimal valid child record for options[CONF_CHILDREN]."""
    base = {
        CONF_USER_ID: user_id,
        CONF_SERVER: server,
        "name": extra.get("name", "Name"),
        "surname": extra.get("surname", "Surname"),
        "school": extra.get("school", "School"),
        "username": extra.get("username", "user"),
    }
    base.update({k: v for k, v in extra.items() if k not in base})
    return base


def _make_coordinator_with_child() -> tuple[BakalariCoordinator, Child]:
    """Build a real coordinator with one child for entity tests."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    # Setup HA frame helper to avoid RuntimeError in HA frame usage
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))
    entry = FakeConfigEntry(
        entry_id="entry-entities",
        options={CONF_CHILDREN: {"c1": _make_child_options("srv1", "u1", name="Jan")}},
    )
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    assert len(coord.child_list) == 1
    child = coord.child_list[0]
    # Ensure api_version exists for device_info
    coord.api_version = "API: 1 Library: 1"
    coord.data = {}
    return coord, child


def test_messages_sensor_native_value_and_attrs():
    """Messages sensor should reflect the count and expose messages in attributes."""
    coord, child = _make_coordinator_with_child()
    coord.data = {
        "messages_by_child": {
            child.key: [
                {"id": "m1", "subject": "Ahoj", "body": "Obsah"},
                {"id": "m2", "subject": "Info", "body": "Text"},
            ]
        }
    }

    sensor = BakalariMessagesSensor(coord, child)
    assert sensor.native_value == 2
    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert isinstance(attrs["messages"], list)
    assert len(attrs["messages"]) == 2
    assert attrs["total_messages_cached"] == 2


def test_timetable_sensor_native_value_and_attrs():
    """Timetable sensor should reflect number of weeks and expose timetable list."""
    coord, child = _make_coordinator_with_child()
    coord.data = {
        "timetable_by_child": {
            child.key: [
                {"week": "2025-01-01"},
                {"week": "2025-01-08"},
                {"week": "2025-01-15"},
            ]
        }
    }

    sensor = BakalariTimetableSensor(coord, child)
    assert sensor.native_value == 3
    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert isinstance(attrs["timetable"], list)
    assert len(attrs["timetable"]) == 3
    assert attrs["total_weeks_cached"] == 3


def _marks_sample() -> list[dict[str, Any]]:
    """Create a list of marks across two subjects (S1=MA, S2=FY) in descending time order."""
    return [
        # S1 / MA: mark "1" (numeric via text), is_new
        {
            "id": "m1",
            "date": "2025-01-10",
            "subject_id": "S1",
            "subject_abbr": "MA",
            "subject_name": "Matematika",
            "mark_text": "1",
            "is_new": True,
        },
        # S1 / MA: numeric_value 2 with weight 2
        {
            "id": "m2",
            "date": "2025-01-09",
            "subject_id": "S1",
            "subject_abbr": "MA",
            "subject_name": "Matematika",
            "numeric_value": 2,
            "weight": 2,
            "is_new": False,
        },
        # S2 / FY: non-numeric mark
        {
            "id": "m3",
            "date": "2025-01-08",
            "subject_id": "S2",
            "subject_abbr": "FY",
            "subject_name": "Fyzika",
            "mark_text": "A",
            "is_new": True,
        },
        # S2 / FY: numeric via text "3"
        {
            "id": "m4",
            "date": "2025-01-07",
            "subject_id": "S2",
            "subject_abbr": "FY",
            "subject_name": "Fyzika",
            "mark_text": "3",
            "is_new": False,
        },
    ]


def test_new_marks_sensor_counts_is_new_and_recent():
    """New marks sensor should count items with is_new and expose a short recent list."""
    coord, child = _make_coordinator_with_child()
    coord.data = {"marks_by_child": {child.key: _marks_sample()}}

    sensor = BakalariNewMarksSensor(coord, child)
    assert sensor.native_value == 2  # m1, m3
    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert len(attrs["recent"]) == 4  # <= 5, all present
    assert attrs["recent"][0]["id"] == "m1"
    assert attrs["total_marks_cached"] == 4


def test_last_mark_sensor_value_and_attrs():
    """Last mark sensor should provide a short text of the most recent mark."""
    coord, child = _make_coordinator_with_child()
    coord.data = {"marks_by_child": {child.key: _marks_sample()}}

    sensor = BakalariLastMarkSensor(coord, child)
    # Most recent is m1 with subject MA and mark_text "1"
    assert sensor.native_value == "MA 1"
    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert attrs["last"]["id"] == "m1"


def test_all_marks_sensor_aggregates_counts_and_subjects():
    """All marks sensor should expose overall totals and per-subject breakdown."""
    coord, child = _make_coordinator_with_child()
    coord.data = {"marks_by_child": {child.key: _marks_sample()}}

    sensor = BakalariAllMarksSensor(coord, child)
    assert sensor.native_value == 4
    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert attrs["total"] == 4
    assert attrs["new_count"] == 2
    assert attrs["numeric_count"] == 3
    assert attrs["non_numeric_count"] == 1
    # Overall averages
    assert attrs["average"] == pytest.approx(2.0, rel=1e-5)
    assert attrs["weighted_average"] == pytest.approx(2.0, rel=1e-5)

    # Subject breakdown
    by_subject: list[dict[str, Any]] = attrs["by_subject"]
    # Convert to dict by subject_abbr for easier assertions
    bmap = {s["subject_abbr"]: s for s in by_subject}
    assert "MA" in bmap and "FY" in bmap

    ma = bmap["MA"]
    assert ma["count"] == 2
    assert ma["numeric_count"] == 2
    assert ma["non_numeric_count"] == 0
    assert ma["avg"] == pytest.approx(1.5, rel=1e-3)
    assert ma["wavg"] == pytest.approx(5 / 3, rel=1e-3)
    assert ma["last_text"] == "1"

    fy = bmap["FY"]
    assert fy["count"] == 2
    assert fy["numeric_count"] == 1
    assert fy["non_numeric_count"] == 1
    assert fy["avg"] == pytest.approx(3.0, rel=1e-5)
    assert fy["wavg"] == pytest.approx(3.0, rel=1e-5)
    assert fy["last_text"] == "A"

    # Recent list preserves ordering and is capped at 20 internally (we have 4)
    assert len(attrs["recent"]) == 4
    assert attrs["recent"][0]["id"] == "m1"


def test_subject_marks_sensor_counts_and_attrs():
    """Per-subject sensor should expose count, subject info and recent marks for that subject."""
    coord, child = _make_coordinator_with_child()
    coord.data = {"marks_by_child": {child.key: _marks_sample()}}

    # Build for subject S1 (Matematika)
    sensor = BakalariSubjectMarksSensor(coord, child, subject_key="S1", label="MA")
    assert sensor.native_value == 2

    attrs = sensor.extra_state_attributes
    assert attrs["child_key"] == child.key
    assert attrs["subject_key"] == "S1"
    # subject info should be present and include averages
    assert attrs["subject"] is not None
    assert attrs["subject"]["avg"] == pytest.approx(1.5, rel=1e-5)
    # recent only shows marks from this subject
    recent_ids = [m["id"] for m in attrs["recent"]]
    assert recent_ids == ["m1", "m2"]


def test_last_mark_sensor_no_items_returns_none():
    """When there are no marks, last mark sensor should return None."""
    coord, child = _make_coordinator_with_child()
    coord.data = {"marks_by_child": {child.key: []}}

    sensor = BakalariLastMarkSensor(coord, child)
    assert sensor.native_value is None
    attrs = sensor.extra_state_attributes
    assert attrs["last"] is None
