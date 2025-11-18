"""End-to-end tests for async_setup_entry and async_migrate_entity_entry."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from homeassistant.helpers import frame as ha_frame
import pytest

from custom_components.bakalari.const import (
    CONF_CHILDREN,
    CONF_SERVER,
    CONF_USER_ID,
    DOMAIN,
)
from custom_components.bakalari.coordinator import BakalariCoordinator
from custom_components.bakalari.sensor import (
    async_migrate_entity_entry,
    async_setup_entry,
)
from custom_components.bakalari.sensor_marks import BakalariSubjectMarksSensor


class FakeBus:
    """Fake HA bus (unused here, but kept for parity with other tests)."""

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
        self.data: dict[str, Any] = {}

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


@pytest.mark.asyncio
async def test_sensor_setup_initial_and_dynamic_subject_entities():
    """async_setup_entry should add base + per-subject entities and react to new subjects dynamically."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    # Setup HA frame helper to avoid RuntimeError in HA frame usage
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    entry = FakeConfigEntry(
        entry_id="entry-setup",
        options={CONF_CHILDREN: {"c1": _make_child_options("srv1", "u1", name="Jan")}},
    )

    # Create a real coordinator and insert it into hass.data
    coord = BakalariCoordinator(hass, entry)  # pyright: ignore[reportArgumentType]
    assert len(coord.child_list) == 1
    child = coord.child_list[0]

    # Initial data: one known subject S1
    coord.data = {
        "subjects_by_child": {child.key: {"S1": {"id": "S1", "abbr": "MA", "name": "Matematika"}}},
        "marks_flat_by_child": {child.key: []},
    }

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coord}

    added_batches: list[list[Any]] = []
    added_all: list[Any] = []

    def fake_async_add_entities(entities, update_before_add: bool = False):
        batch = list(entities)
        added_batches.append(batch)
        added_all.extend(batch)

    # Run setup
    await async_setup_entry(hass, entry, fake_async_add_entities)  # pyright: ignore[]

    # One batch with base 5 + 1 per-subject = 6
    assert len(added_batches) >= 1
    initial_total = sum(len(b) for b in added_batches)
    assert initial_total == 6

    # Verify we have exactly one per-subject entity for S1
    subject_entities = [e for e in added_all if isinstance(e, BakalariSubjectMarksSensor)]
    assert len(subject_entities) == 1
    assert subject_entities[0].unique_id.endswith(":subject:S1")

    # Now coordinator gets a new subject S2 and notifies listeners
    coord.data = {
        "subjects_by_child": {
            child.key: {
                "S1": {"id": "S1", "abbr": "MA", "name": "Matematika"},
                "S2": {"id": "S2", "abbr": "FY", "name": "Fyzika"},
            }
        }
    }
    # Notify listeners (registered by async_setup_entry) about the update
    coord.async_set_updated_data(coord.data)

    # A new batch should have been added containing the new subject sensor S2
    # Find all per-subject sensors again
    subject_entities_after = [e for e in added_all if isinstance(e, BakalariSubjectMarksSensor)]
    assert len(subject_entities_after) == 2
    assert any(e.unique_id.endswith(":subject:S2") for e in subject_entities_after)


@pytest.mark.asyncio
async def test_async_migrate_entity_entry_success_by_option_key():
    """Migration should succeed when cid matches the options key of the child."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    # Setup HA frame helper to avoid RuntimeError in HA frame usage
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    # Entry with two children; we'll migrate one by its option key
    options_children = {
        "child1": _make_child_options("srvA", "userA"),
        "child2": _make_child_options("srvB", "userB"),
    }
    entry = FakeConfigEntry(entry_id="entry-mig", options={CONF_CHILDREN: options_children})

    # Entity entry with legacy unique_id pattern
    entity_entry = SimpleNamespace(unique_id="bakalari_child1_messages")

    res = await async_migrate_entity_entry(hass, entry, entity_entry)  # pyright: ignore[]
    # Expected new unique_id is "<entry_id>:<server|user_id>:messages"
    assert isinstance(res, dict)
    assert "new_unique_id" in res
    assert res["new_unique_id"] == "entry-mig:srvA|userA:messages"


@pytest.mark.asyncio
async def test_async_migrate_entity_entry_no_match_returns_none():
    """Migration should return None when cid doesn't match any known child."""
    loop = asyncio.get_event_loop()
    hass = FakeHass(loop)
    # Setup HA frame helper to avoid RuntimeError in HA frame usage
    setattr(ha_frame._hass, "hass", hass)
    setattr(ha_frame, "report_usage", (lambda *a, **k: None))

    options_children = {"child1": _make_child_options("srvA", "userA")}
    entry = FakeConfigEntry(entry_id="entry-mig2", options={CONF_CHILDREN: options_children})
    entity_entry = SimpleNamespace(unique_id="bakalari_unknown_messages")

    res = await async_migrate_entity_entry(hass, entry, entity_entry)  # pyright: ignore[]
    assert res is None
