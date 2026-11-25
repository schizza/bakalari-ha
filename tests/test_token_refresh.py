"""Token storage, migration and flow-driven reload regression tests."""

from collections.abc import Generator
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

from async_bakalari_api import Bakalari
from async_bakalari_api.datastructure import Credentials
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bakalari import async_migrate_entry
from custom_components.bakalari.api import BakalariClient
from custom_components.bakalari.config_flow import ConfigFlow
from custom_components.bakalari.const import (
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_CREDENTIALS,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.bakalari.options_flow import BakalariOptionsFlow

TOKENS = {CONF_ACCESS_TOKEN: "old-access", CONF_REFRESH_TOKEN: "old-refresh"}
CHILD = {
    "user_id": "child",
    "username": "user",
    "server": "https://example.com",
    "name": "Name",
    "surname": "Surname",
    "school": "School",
}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Register a migrated entry with one child."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_CREDENTIALS: {"child": dict(TOKENS)}, "extra": "keep"},
        options={CONF_CHILDREN: {"child": dict(CHILD)}, "scan_interval": 300},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def reload(hass: HomeAssistant) -> Generator[AsyncMock]:
    """Capture entry reloads so the integration is never set up."""
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        yield reload


@pytest.fixture
def schedule(hass: HomeAssistant) -> Generator[Mock]:
    """Capture scheduled entry reloads so the integration is never set up."""
    with patch.object(hass.config_entries, "async_schedule_reload") as schedule:
        yield schedule


def make_client(hass: HomeAssistant, entry: MockConfigEntry) -> BakalariClient:
    """Create a client with already installed credentials."""
    client = BakalariClient(hass, entry, "child")
    client.lib = Mock(spec=Bakalari, credentials=Credentials(**TOKENS))
    client._last_tokens = (TOKENS[CONF_ACCESS_TOKEN], TOKENS[CONF_REFRESH_TOKEN])
    return client


async def test_refresh_and_reset_do_not_reload(
    hass: HomeAssistant, entry: MockConfigEntry, reload: AsyncMock, schedule: Mock
):
    """Refreshes persist in data and resetting one client needs no entry reload."""
    client = make_client(hass, entry)
    original_options = deepcopy(dict(entry.options))
    for generation in range(2):
        credentials = Credentials(
            access_token=f"access-{generation}", refresh_token=f"refresh-{generation}"
        )

        async def fetch(lib, credentials=credentials):
            lib.credentials = credentials
            return ["notice"]

        assert await client._api_call(
            label="noticeboard", default=[], callable_fn=fetch
        ) == ["notice"]
        assert entry.data[CONF_CREDENTIALS]["child"] == {
            CONF_ACCESS_TOKEN: credentials.access_token,
            CONF_REFRESH_TOKEN: credentials.refresh_token,
        }
    await client._reset_tokens_and_client()
    assert client.lib is None
    assert entry.data[CONF_CREDENTIALS]["child"] == {
        CONF_ACCESS_TOKEN: "",
        CONF_REFRESH_TOKEN: "",
    }
    assert entry.options == original_options
    assert entry.data["extra"] == "keep"
    await hass.async_block_till_done()
    reload.assert_not_called()
    schedule.assert_not_called()


@pytest.mark.parametrize("children", [{"child": {**CHILD, **TOKENS}}, []])
async def test_migration(hass: HomeAssistant, children):
    """Migrate populated entries and the legacy empty-list initial entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={"extra": "keep"},
        options={CONF_CHILDREN: children, "scan_interval": 300},
    )
    entry.add_to_hass(hass)
    original = deepcopy(children)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.options["scan_interval"] == 300
    assert entry.data["extra"] == "keep"
    assert children == original
    assert all(
        CONF_ACCESS_TOKEN not in child and CONF_REFRESH_TOKEN not in child
        for child in entry.options[CONF_CHILDREN].values()
    )
    assert entry.data[CONF_CREDENTIALS] == dict.fromkeys(
        entry.options[CONF_CHILDREN], TOKENS
    )
    before = deepcopy(dict(entry.data))
    assert await async_migrate_entry(hass, entry)
    assert entry.data == before


async def test_options_edit_preserves_refreshed_tokens(
    hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock
):
    """An open options form cannot overwrite tokens refreshed in the meantime."""
    flow = BakalariOptionsFlow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    flow._edit_index = "child"
    client = make_client(hass, entry)
    client.lib.credentials = Credentials(
        access_token="new", refresh_token="new-refresh"
    )
    await client._save_tokens_if_changed()
    result = await flow.async_step_edit_child(
        {"name": "New name", "surname": "Surname", "username": "user"}
    )
    await hass.config_entries.options.async_finish_flow(flow, result)
    assert entry.options[CONF_CHILDREN]["child"]["name"] == "New name"
    assert entry.options["scan_interval"] == 300
    assert entry.data[CONF_CREDENTIALS]["child"][CONF_ACCESS_TOKEN] == "new"
    schedule.assert_called_once_with(entry.entry_id)


async def test_delete_and_inflight_refresh(
    hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock
):
    """Deleting a child removes its credentials and in-flight saves cannot restore it."""
    client = make_client(hass, entry)
    flow = BakalariOptionsFlow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    result = await flow.async_step_select_child_to_delete({"child_id": "child"})
    await hass.config_entries.options.async_finish_flow(flow, result)
    client.lib.credentials = Credentials(access_token="late", refresh_token="late")
    await client._save_tokens_if_changed()
    await client._reset_tokens_and_client()
    assert entry.data[CONF_CREDENTIALS] == {}
    assert entry.options[CONF_CHILDREN] == {}
    schedule.assert_called_once_with(entry.entry_id)


async def test_reauth_updates_data_and_reloads(
    hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock
):
    """Reauth explicitly reloads with new tokens while preserving other accounts."""
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_CREDENTIALS: {**entry.data[CONF_CREDENTIALS], "other": dict(TOKENS)},
        },
    )
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_REAUTH, "entry_id": entry.entry_id}
    flow._reauth_data = {
        "entry_id": entry.entry_id,
        "child_id": "child",
        "server": CHILD["server"],
        "username": "user",
    }
    api = AsyncMock()
    api.__aenter__.return_value = api
    api.first_login.return_value = Credentials(
        access_token="login", refresh_token="login-refresh"
    )
    with (
        patch("custom_components.bakalari.config_flow.Bakalari", return_value=api),
        patch(
            "custom_components.bakalari.config_flow.async_get_clientsession",
            return_value=Mock(),
        ),
    ):
        result = await flow.async_step_reauth_confirm({"password": "password"})
    assert result.get("reason") == "reauth_successful"
    assert entry.data[CONF_CREDENTIALS]["child"][CONF_ACCESS_TOKEN] == "login"
    assert entry.data[CONF_CREDENTIALS]["other"] == TOKENS
    assert entry.options[CONF_CHILDREN]["child"] == CHILD
    schedule.assert_called_once_with(entry.entry_id)


async def test_add_child(hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock):
    """Adding a child saves credentials separately and reloads on flow completion."""
    flow = BakalariOptionsFlow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    flow._new_child = {"name": "Second", "surname": "Child", "school": "School"}
    flow._schools = Mock()
    flow._schools.get_url.return_value = "https://example.com"
    api = AsyncMock()
    api.__aenter__.return_value = api
    api.first_login.return_value = Credentials(
        user_id="second", access_token="second-access", refresh_token="second-refresh"
    )
    with patch("custom_components.bakalari.options_flow.Bakalari", return_value=api):
        result = await flow.async_step_login(
            {"username": "second-user", "password": "password"}
        )
    await hass.config_entries.options.async_finish_flow(flow, result)
    assert entry.data[CONF_CREDENTIALS]["child"] == TOKENS
    assert entry.data[CONF_CREDENTIALS]["second"][CONF_ACCESS_TOKEN] == "second-access"
    assert CONF_ACCESS_TOKEN not in entry.options[CONF_CHILDREN]["second"]
    schedule.assert_called_once_with(entry.entry_id)


async def test_login_existing_child_reloads_with_unchanged_options(
    hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock
):
    """Replacing credentials through Add must reload even with identical settings."""
    flow = BakalariOptionsFlow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    flow._new_child = dict(CHILD)
    flow._schools = Mock()
    flow._schools.get_url.return_value = CHILD["server"]
    api = AsyncMock()
    api.__aenter__.return_value = api
    api.first_login.return_value = Credentials(
        user_id="child", access_token="replacement", refresh_token="replacement-refresh"
    )
    with patch("custom_components.bakalari.options_flow.Bakalari", return_value=api):
        result = await flow.async_step_login(
            {"username": "user", "password": "password"}
        )
    await hass.config_entries.options.async_finish_flow(flow, result)
    assert entry.options[CONF_CHILDREN]["child"] == CHILD
    assert entry.data[CONF_CREDENTIALS]["child"][CONF_ACCESS_TOKEN] == "replacement"
    schedule.assert_called_once_with(entry.entry_id)


async def test_unchanged_options_do_not_reload(
    hass: HomeAssistant, entry: MockConfigEntry, schedule: Mock
):
    """Submitting unchanged settings leaves the running integration alone."""
    flow = BakalariOptionsFlow(entry)
    flow.hass = hass
    flow.handler = entry.entry_id
    flow._edit_index = "child"
    result = await flow.async_step_edit_child(
        {"name": "Name", "surname": "Surname", "username": "user"}
    )
    await hass.config_entries.options.async_finish_flow(flow, result)
    schedule.assert_not_called()


async def test_client_loads_credentials_from_data(
    hass: HomeAssistant, entry: MockConfigEntry
):
    """A newly created client authenticates using migrated credentials."""
    client = BakalariClient(hass, entry, "child")
    with (
        patch(
            "custom_components.bakalari.api.async_get_clientsession",
            return_value=Mock(),
        ),
        patch("custom_components.bakalari.api.Bakalari") as library,
    ):
        library.return_value.credentials = Credentials(**TOKENS)
        assert await client._is_lib() is library.return_value
    credentials = library.call_args.kwargs["credentials"]
    assert credentials.access_token == TOKENS[CONF_ACCESS_TOKEN]
    assert credentials.refresh_token == TOKENS[CONF_REFRESH_TOKEN]
    assert credentials.username == CHILD["username"]
