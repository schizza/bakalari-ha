"""Tests for sensor_helpers helpers: subject derivation, initial entities, seeding and dynamic listener behavior."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

from homeassistant.helpers import frame as ha_frame
import pytest

from custom_components.bakalari.const import CONF_CHILDREN, CONF_SERVER, CONF_USER_ID
from custom_components.bakalari.coordinator import BakalariCoordinator, Child
from custom_components.bakalari.sensor_helpers import (
    build_subjects_listener,
    create_initial_entities,
    create_subject_entities_for_child,
    derive_subjects_from_data,
    seed_created_subjects_from_data,
)


class FakeCoordinator:
    """Minimal fake of DataUpdateCoordinator for entity construction and listeners."""

    def __init__(self, *, entry_id: str, child_list: list[Child], data: dict | None = None) -> None:
        """Initialize a fake coordinator."""
        self.entry = SimpleNamespace(entry_id=entry_id)
        self.child_list = child_list
        self.data: dict[str, Any] = data or {}
        self.api_version = "API: x.y.z Library: 1.2.3"

        # Keep listeners added by CoordinatorEntity (not used in these tests, but we store them)
        self._listeners: list[Any] = []

    def async_add_listener(self, callback):
        """Store a listener and return an unsubscribe callable."""
        self._listeners.append(callback)

        def _unsub():
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return _unsub


def make_child(key: str = "srv|uid", name: str = "Name") -> Child:
    """Build a real Child dataclass instance for tests."""
    return Child(
        key=key,
        user_id="uid",
        server="srv",
        display_name=f"{name} (School)",
        short_name=name,
    )


def test_derive_subjects_from_data_with_subjects_map():
    """derive_subjects_from_data uses subjects_by_child when available."""
    ck = "srv|u1"
    data_now = {
        "subjects_by_child": {
            ck: {
                "S1": {"id": "S1", "abbr": "MA", "name": "Matematika"},
                "S2": {"id": "S2", "abbr": "AJ", "name": "Angličtina"},
            }
        }
    }

    coord = FakeCoordinator(entry_id="e1", child_list=[make_child(ck)], data=data_now)
    derived = derive_subjects_from_data(coord, ck, coord.data)  # pyright: ignore[]

    # Order is not strictly important; assert sets for keys and labels
    keys = {k for (k, _label) in derived}
    labels = {label for (_k, label) in derived}
    assert keys == {"S1", "S2"}
    assert labels == {"MA", "AJ"}


def test_derive_subjects_from_data_fallback_to_marks_flat():
    """derive_subjects_from_data falls back to marks_flat_by_child and deduplicates subjects."""
    ck = "srv|u2"
    m1 = {"subject_id": "S1", "subject_abbr": "MA", "subject_name": "Matematika"}
    m2 = {"subject_id": "S1", "subject_abbr": "MA", "subject_name": "Matematika"}  # duplicate
    m3 = {"subject_id": "S2", "subject_abbr": "FY", "subject_name": "Fyzika"}
    data_now = {"marks_flat_by_child": {ck: [m1, m2, m3]}}

    coord = FakeCoordinator(entry_id="e2", child_list=[make_child(ck)], data=data_now)
    derived = derive_subjects_from_data(coord, ck, coord.data)  # pyright: ignore[]

    keys = {k for (k, _label) in derived}
    labels = {label for (_k, label) in derived}
    assert keys == {"S1", "S2"}
    # Labels prefer abbr
    assert labels == {"MA", "FY"}


def test_create_initial_entities_count():
    """create_initial_entities returns expected number of base sensors."""

    loop = asyncio.get_event_loop()

    class FakeHass:
        def __init__(self, loop):
            self.loop = loop
            self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

        def async_create_task(self, coro):
            return self.loop.create_task(coro)

    class FakeConfigEntry:
        def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.options = options
            self.domain = "bakalari"

    hass = FakeHass(loop)
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    options = {
        CONF_CHILDREN: {
            "c1": {
                CONF_SERVER: "srv",
                CONF_USER_ID: "uid",
                "name": "Name",
                "surname": "Surname",
                "school": "School",
                "username": "user",
            }
        }
    }
    entry = FakeConfigEntry(entry_id="entry-xyz", options=options)
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    child = coord.child_list[0]

    ents = create_initial_entities(coord, child)
    # NewMarks, LastMark, AllMarks, Messages, Timetable
    assert len(ents) == 5


def test_create_subject_entities_for_child_uses_derivation():
    """create_subject_entities_for_child builds one entity per derived subject."""

    loop = asyncio.get_event_loop()

    class FakeHass:
        def __init__(self, loop):
            self.loop = loop
            self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

        def async_create_task(self, coro):
            return self.loop.create_task(coro)

    class FakeConfigEntry:
        def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.options = options
            self.domain = "bakalari"

    hass = FakeHass(loop)
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    options = {
        CONF_CHILDREN: {
            "c1": {
                CONF_SERVER: "srv",
                CONF_USER_ID: "uid",
                "name": "Name",
                "surname": "Surname",
                "school": "School",
                "username": "user",
            }
        }
    }
    entry = FakeConfigEntry(entry_id="entry-e4", options=options)
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    child = coord.child_list[0]

    data_now = {
        "subjects_by_child": {
            child.key: {
                "S1": {"id": "S1", "abbr": "MA", "name": "Matematika"},
                "S2": {"id": "S2", "abbr": "CJ", "name": "Čeština"},
            }
        }
    }

    ents = create_subject_entities_for_child(coord, child, data_now)
    assert len(ents) == 2


def test_seed_created_subjects_from_data_collects_per_child():
    """seed_created_subjects_from_data produces map child_key -> set(subject_key)."""

    loop = asyncio.get_event_loop()

    class FakeHass:
        def __init__(self, loop):
            self.loop = loop
            self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

        def async_create_task(self, coro):
            return self.loop.create_task(coro)

    class FakeConfigEntry:
        def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.options = options
            self.domain = "bakalari"

    hass = FakeHass(loop)
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    options = {
        CONF_CHILDREN: {
            "alpha": {
                CONF_SERVER: "servA",
                CONF_USER_ID: "userA",
                "name": "A",
                "surname": "A",
                "school": "School",
                "username": "user",
            },
            "beta": {
                CONF_SERVER: "servB",
                CONF_USER_ID: "userB",
                "name": "B",
                "surname": "B",
                "school": "School",
                "username": "user",
            },
        }
    }
    entry = FakeConfigEntry(entry_id="entry-e5", options=options)
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    # Build data_now against real child keys
    keys = {c.short_name: c.key for c in coord.child_list}
    data_now = {
        "subjects_by_child": {
            keys["A"]: {"S1": {"id": "S1", "abbr": "MA", "name": "Matematika"}},
            keys["B"]: {
                "S2": {"id": "S2", "abbr": "FY", "name": "Fyzika"},
                "S3": {"id": "S3", "abbr": "BI", "name": "Biologie"},
            },
        }
    }
    coord.data = data_now

    created = seed_created_subjects_from_data(coord, coord.data)
    assert set(created.keys()) == set(keys.values())
    assert created[keys["A"]] == {"S1"}
    assert created[keys["B"]] == {"S2", "S3"}


def test_build_subjects_listener_adds_new_subjects(monkeypatch: pytest.MonkeyPatch):
    """build_subjects_listener should add only new subject sensors and update tracking state."""

    loop = asyncio.get_event_loop()

    class FakeHass:
        def __init__(self, loop):
            self.loop = loop
            self.bus = SimpleNamespace(async_fire=lambda *a, **k: None)

        def async_create_task(self, coro):
            return self.loop.create_task(coro)

    class FakeConfigEntry:
        def __init__(self, *, entry_id: str, options: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.options = options
            self.domain = "bakalari"

    hass = FakeHass(loop)
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    options = {
        CONF_CHILDREN: {
            "cX": {
                CONF_SERVER: "srv",
                CONF_USER_ID: "uid",
                "name": "Name",
                "surname": "Surname",
                "school": "School",
                "username": "user",
            }
        }
    }
    entry = FakeConfigEntry(entry_id="entry-e6", options=options)
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    child = coord.child_list[0]

    # Initially only S1 exists
    coord.data = {
        "subjects_by_child": {child.key: {"S1": {"id": "S1", "abbr": "MA", "name": "Matematika"}}}
    }

    created_subjects = {child.key: {"S1"}}
    added: list[Any] = []

    def fake_async_add_entities(new_entities, update_before_add: bool = False):
        added.extend(list(new_entities))

    listener = build_subjects_listener(coord, created_subjects, fake_async_add_entities)

    # New data introduces S2 as a new subject
    coord.data = {
        "subjects_by_child": {
            child.key: {
                "S1": {"id": "S1", "abbr": "MA", "name": "Matematika"},
                "S2": {"id": "S2", "abbr": "FY", "name": "Fyzika"},
            }
        }
    }

    listener()

    # One new entity should be added for S2
    assert len(added) == 1
    # Tracking updated
    assert created_subjects[child.key] == {"S1", "S2"}

    # Calling again shouldn't add duplicates
    listener()
    assert len(added) == 1
