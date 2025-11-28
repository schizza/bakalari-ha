"""Test for coordinator."""

import asyncio
from datetime import datetime, timedelta
import json
from typing import Any

from homeassistant.helpers import frame as ha_frame
import pytest

from custom_components.bakalari import coordinator_marks as coordinator_mod
from custom_components.bakalari.children import ChildrenIndex
from custom_components.bakalari.const import (
    CONF_CHILDREN,
    CONF_SCAN_INTERVAL,
    CONF_SERVER,
    CONF_USER_ID,
)
from custom_components.bakalari.coordinator_marks import BakalariMarksCoordinator

# Coordinator will be imported within tests after patching frame/report_usage


class FakeMessage:
    """Simple fake for Komens message container."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Initialize a fake message."""
        self._payload = payload

    def as_json(self) -> str:
        """Return a JSON string representation of the message."""
        # Coordinator uses orjson.loads(msg.as_json()), so return a JSON string
        return json.dumps(self._payload)


class FakeBus:
    """Fake Home Assistant event bus to capture fired events."""

    def __init__(self) -> None:
        """Initialize a fake event bus."""
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Fire an event on the fake bus."""
        self.events.append((event_type, event_data))


class FakeHass:
    """Minimal fake Home Assistant core object for DataUpdateCoordinator."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize a fake Home Assistant core object."""
        self.loop = loop
        self.bus = FakeBus()

    def async_create_task(self, coro):
        """Create a task on the fake event loop."""
        return self.loop.create_task(coro)


class FakeConfigEntry:
    """Minimal fake ConfigEntry."""

    def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
        """Initialize a fake ConfigEntry."""
        self.entry_id = entry_id
        self.options = options
        self.domain = "bakalari"


class FakeBakalariClient:
    """Fake BakalariClient injected into coordinator for deterministic tests."""

    # Class-level stores to customize returns per test
    SNAPSHOT: dict[str, Any] = {
        "subjects": {},
        "marks_grouped": {},
        "marks_flat": [],
    }
    MESSAGES: list[FakeMessage] = []
    TIMETABLE_WEEK: dict[str, Any] = {"week": "stub"}

    def __init__(self, hass, entry, child_opt_key) -> None:  # noqa: ANN001
        """Initialize a fake BakalariClient."""
        self.hass = hass
        self.entry = entry
        self.child_opt_key = child_opt_key

    async def async_get_marks_snapshot(  # noqa: D401
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        subject_id: str | None = None,
        to_dict: bool = True,
        order: str = "desc",
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Return preconfigured snapshot and summary without touching arguments."""
        # Return a shallow copy to reduce mutation side effects in tests
        snapshot = {
            "subjects": dict(self.SNAPSHOT.get("subjects", {})),
            "marks_grouped": dict(self.SNAPSHOT.get("marks_grouped", {})),
            "marks_flat": list(self.SNAPSHOT.get("marks_flat", [])),
        }
        summary: dict[str, str] = {}
        return snapshot, summary

    async def async_get_messages(self) -> list[FakeMessage]:
        """Return preconfigured messages without touching arguments."""
        return list(self.MESSAGES)

    async def async_get_timetable_actual(self, for_date):  # noqa: ANN001
        """Initialize a fake BakalariClient."""
        # Return a structure that can be serialized/logged by coordinator
        return {"week": str(for_date)}


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
    # access_token/refresh_token optional; can be added via extra if needed
    base.update({k: v for k, v in extra.items() if k not in base})
    return base


@pytest.mark.asyncio
async def test_coordinator_builds_snapshot_and_emits_events(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that coordinator builds snapshot and emits events."""

    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    ha_frame._hass.hass = hass  # pyright: ignore[]
    entry = FakeConfigEntry(
        entry_id="entry-1",
        options={
            CONF_CHILDREN: {
                # option-key "child1" refers to user_id "u1" on server "srv1"
                "child1": _make_child_options("srv1", "u1"),
            },
            CONF_SCAN_INTERVAL: 900,
        },
    )

    # Prepare fake snapshot with two flat marks belonging to one subject
    now = datetime.now()
    m1 = {
        "id": "m1",
        "date": (now - timedelta(days=1)).isoformat(),
        "subject_id": "S1",
        "subject_abbr": "MA",
        "subject_name": "Matematika",
        "caption": "Test 1",
        "theme": "Téma 1",
        "mark_text": "1",
        "is_new": True,
        "is_points": False,
        "points_text": None,
        "max_points": None,
        "teacher": "Učitel",
    }
    m2 = {
        "id": "m2",
        "date": (now - timedelta(days=2)).isoformat(),
        "subject_id": "S1",
        "subject_abbr": "MA",
        "subject_name": "Matematika",
        "caption": "Test 2",
        "theme": None,
        "mark_text": "2",
        "is_new": False,
        "is_points": False,
        "points_text": None,
        "max_points": None,
        "teacher": "Učitel",
    }
    FakeBakalariClient.SNAPSHOT = {
        "subjects": {
            "S1": {
                "id": "S1",
                "abbr": "MA",
                "name": "Matematika",
                "average_text": "1.5",
                "points_only": False,
            }
        },
        "marks_grouped": {"S1": [m1, m2]},
        "marks_flat": [m1, m2],
    }

    # Prepare messages and timetable returns
    FakeBakalariClient.MESSAGES = [
        FakeMessage({"id": "msg1", "subject": "Ahoj", "body": "Obsah"}),
        FakeMessage({"id": "msg2", "subject": "Info", "body": "Text"}),
    ]

    # Initialize frame helper and patch frame.report_usage before importing coordinator

    monkeypatch.setattr(ha_frame, "report_usage", lambda *a, **k: None)

    # Inject our fake client into the coordinator module
    monkeypatch.setattr(coordinator_mod, "BakalariClient", FakeBakalariClient)

    children = ChildrenIndex.from_entry(entry)
    coord = BakalariMarksCoordinator(hass, entry, children)  # pyright: ignore[]

    # Run update cycle
    data = await coord._async_update_data()

    # Snapshot data present and correctly mapped per child
    assert "subjects_by_child" in data
    assert "marks_by_child" in data
    assert "marks_flat_by_child" in data
    assert len(coord.child_list) == 1
    ck = coord.child_list[0].key
    assert data["subjects_by_child"][ck]["S1"]["name"] == "Matematika"
    assert len(data["marks_flat_by_child"][ck]) == 2

    # Messages and Timetable are handled by separate coordinators now; marks coordinator exposes only marks.

    # Events emitted for all marks on first run
    fired = hass.bus.events
    assert len(fired) == 2
    for evt_type, payload in fired:
        assert evt_type == "bakalari_new_mark"
        assert payload["id"] in {"m1", "m2"}


@pytest.mark.asyncio
async def test_coordinator_event_diff_only_new(monkeypatch: pytest.MonkeyPatch):
    """Test that coordinator emits events for new marks only."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)

    ha_frame._hass.hass = hass  # pyright: ignore[]
    entry = FakeConfigEntry(
        entry_id="entry-2",
        options={
            CONF_CHILDREN: {"cX": _make_child_options("srvX", "uidX")},
            CONF_SCAN_INTERVAL: 900,
        },
    )

    # A snapshot with a single mark
    now = datetime.now()
    item = {
        "id": "m42",
        "date": now.isoformat(),
        "subject_id": "S2",
        "subject_abbr": "FY",
        "subject_name": "Fyzika",
        "caption": "Písemka",
        "theme": None,
        "mark_text": "1",
        "is_new": True,
        "is_points": False,
        "points_text": None,
        "max_points": None,
        "teacher": "Učitel",
    }
    FakeBakalariClient.SNAPSHOT = {
        "subjects": {
            "S2": {
                "id": "S2",
                "abbr": "FY",
                "name": "Fyzika",
                "average_text": "",
                "points_only": False,
            }
        },
        "marks_grouped": {"S2": [item]},
        "marks_flat": [item],
    }
    FakeBakalariClient.MESSAGES = []
    # Initialize frame helper and patch frame.report_usage before importing coordinator

    monkeypatch.setattr(ha_frame, "report_usage", lambda *a, **k: None)

    # Inject our fake client into the coordinator module
    monkeypatch.setattr(coordinator_mod, "BakalariClient", FakeBakalariClient)

    children = ChildrenIndex.from_entry(entry)
    coord = BakalariMarksCoordinator(hass, entry, children)  # pyright: ignore[]

    # First update -> one event
    data1 = await coord._async_update_data()
    assert len(hass.bus.events) == 1
    assert hass.bus.events[0][1]["id"] == "m42"

    # Second update with the same snapshot -> no new events
    data2 = await coord._async_update_data()
    assert len(hass.bus.events) == 1  # unchanged

    # Ensure marks_flat_by_child still contains the single mark
    ck = coord.child_list[0].key
    assert len(data1["marks_flat_by_child"][ck]) == 1
    assert len(data2["marks_flat_by_child"][ck]) == 1


@pytest.mark.asyncio
async def test_coordinator_child_mapping_and_keys(monkeypatch: pytest.MonkeyPatch):
    """Test that coordinator maps child keys to option keys correctly."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)

    ha_frame._hass.hass = hass  # pyright: ignore[]
    opts_children = {
        "alpha": _make_child_options("servA", "userA", name="Anna"),
        "beta": _make_child_options("servB", "userB", name="Boris"),
    }
    entry = FakeConfigEntry(
        entry_id="entry-3",
        options={CONF_CHILDREN: opts_children, CONF_SCAN_INTERVAL: 300},
    )

    # Minimal snapshot (no marks) to avoid event noise
    FakeBakalariClient.SNAPSHOT = {
        "subjects": {},
        "marks_grouped": {},
        "marks_flat": [],
    }
    FakeBakalariClient.MESSAGES = []
    # Initialize frame helper and patch frame.report_usage before importing coordinator

    monkeypatch.setattr(ha_frame, "report_usage", lambda *a, **k: None)

    monkeypatch.setattr(coordinator_mod, "BakalariClient", FakeBakalariClient)

    children = ChildrenIndex.from_entry(entry)
    coord = BakalariMarksCoordinator(hass, entry, children)  # pyright: ignore[]

    # Two children discovered
    assert len(coord.child_list) == 2
    keys = {c.key for c in coord.child_list}
    assert "servA|userA" in keys
    assert "servB|userB" in keys
