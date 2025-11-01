"""Options flow for Bakalari."""

from __future__ import annotations

from typing import Any

from async_bakalari_api import Bakalari, Credentials, Ex, Schools
from homeassistant import config_entries
from homeassistant.helpers.storage import Store
import voluptuous as vol

from .const import (
    CONF_CHILDREN,
    CONF_NAME,
    CONF_SCHOOL,
    CONF_SERVER,
    CONF_SURNAME,
    CONF_USERNAME,
    SCHOOLS_CACHE_FILE,
    ChildRecord,
)
from .utils import child_from_raw, ensure_children_dict


class BakalariOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Bakalari.

    We should enable add/modify/delete children in this flow.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize BakalariOptionsFlow."""

        self.children = ensure_children_dict(
            config_entry.options.get(CONF_CHILDREN, {})
        )  # list(config_entry.options.get("children", []))
        self._edit_index = None
        self._schools: Schools | None = None
        self._new_child: dict[str, Any] | None = None
        self._edit_school_for: str | None = None

    async def create_schools_instance(self) -> None:
        """Create a new instance of Schools from the cache."""

        # Import schools from cache as we should have them from initial setup
        schools_store = Store(self.hass, 1, SCHOOLS_CACHE_FILE)
        schools_cache = await schools_store.async_load() or []

        _schools_cache = Schools()

        for item in schools_cache:
            _schools_cache.append_school(
                name=item.get("name"),
                api_point=item.get("api_point"),
                town=item.get("town"),
            )
        self._schools = _schools_cache

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Initialize BakalariOptionsFlow.

        Create list of children or Add new child.
        """

        await self.create_schools_instance()

        actions = {"add": "Přidat nové dítě", "edit": "Upravit dítě", "delete": "Smazat dítě"}

        data_schema = vol.Schema({vol.Required("action"): vol.In(actions)})
        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_add_child()
            if action == "edit":
                return await self.async_step_select_child_to_edit()
            if action == "delete":
                return await self.async_step_select_child_to_delete()

        return self.async_show_form(step_id="init", data_schema=data_schema)

    async def async_step_select_child_to_edit(self, user_input=None):
        """Step to select child for editing."""

        options = {
            cid: f"{child.get(CONF_NAME, '')} {child.get(CONF_SURNAME, '')}".strip()
            for cid, child in self.children.items()
        }

        data_schema = vol.Schema({vol.Required("action"): vol.In(options)})

        if user_input is not None:
            action = user_input["action"]
            self._edit_index = action
            return await self.async_step_edit_child()

        return self.async_show_form(step_id="select_child_to_edit", data_schema=data_schema)

    async def async_step_add_child(self, user_input=None):
        """Step add child."""

        data_schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("surname"): str,
            }
        )

        if user_input is not None:
            self._new_child = {
                "name": user_input["name"],
                "surname": user_input["surname"],
            }

            return await self.async_step_select_city()

        return self.async_show_form(step_id="add_child", data_schema=data_schema)

    async def async_step_select_city(self, user_input=None):
        """Step select city."""

        data_schema = vol.Schema({vol.Required("city"): vol.In(self._schools.get_all_towns())})

        # we have city selected
        if user_input is not None:
            self._selected_city = user_input["city"]
            return await self.async_step_select_school()

        # we have to select city
        return self.async_show_form(step_id="select_city", data_schema=data_schema)

    async def async_step_select_school(self, user_input=None):
        """Step select school."""

        _schools = [
            school.name for school in self._schools.get_schools_by_town(self._selected_city)
        ]

        data_schema = vol.Schema({vol.Required(CONF_SCHOOL): vol.In(_schools)})

        if user_input is not None:
            # change school for child
            if self._edit_school_for:
                self.children[self._edit_school_for][CONF_SCHOOL] = user_input[CONF_SCHOOL]
                url = self._schools.get_url(name=user_input[CONF_SCHOOL])
                self.children[self._edit_school_for][CONF_SERVER] = (
                    url if isinstance(url, str) and url else ""
                )

                self.async_create_entry(title="", data={CONF_CHILDREN: self.children})
                return await self.async_step_edit_child()

            self._new_child[CONF_SCHOOL] = user_input[CONF_SCHOOL]  # pyright: ignore[reportOptionalSubscript]
            self._new_child[CONF_SERVER] = self._schools.get_url(name=user_input[CONF_SCHOOL])  # pyright: ignore[reportOptionalSubscript]
            return await self.async_step_login()

        return self.async_show_form(step_id="select_school", data_schema=data_schema)

    async def async_step_login(self, user_input=None):
        """Step login."""

        credentials: Credentials | None = None

        data_schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
            }
        )

        # we have login data
        if user_input is not None:
            school_url = self._schools.get_url(self._new_child[CONF_SCHOOL])  # pyright: ignore[reportOptionalSubscript]
            school_url = school_url if isinstance(school_url, str) and school_url else ""

            try:
                async with Bakalari(school_url) as api:
                    credentials = await api.first_login(
                        user_input[CONF_USERNAME], user_input["password"]
                    )

                self._new_child["credentials"] = credentials  # pyright: ignore[reportOptionalSubscript]
                self._new_child[CONF_USERNAME] = user_input[CONF_USERNAME]  # pyright: ignore[reportOptionalSubscript]
                self._new_child[CONF_SERVER] = school_url  # pyright: ignore[reportOptionalSubscript]

            except Ex.InvalidLogin:
                return self.async_show_form(
                    step_id="login",
                    data_schema=data_schema,
                    errors={"base": "invalid_login"},
                )

            child_id, child = child_from_raw(self._new_child)
            self.children[child_id] = child

            return self.async_create_entry(title="", data={CONF_CHILDREN: self.children})

        # we have to login
        return self.async_show_form(step_id="login", data_schema=data_schema)

    async def async_step_edit_child(self, user_input=None):
        """Step to edit an existing child."""

        child_id = self._edit_index
        child: ChildRecord = self.children.get(child_id)  # type: ignore[assignment]
        if not child:
            # fallback, child not found
            return self.async_step_init()

        school: str = child.get(CONF_SCHOOL)
        school_label: str = f"Změnit školu (aktuálně: {school})"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=child.get(CONF_NAME, "")): str,
                vol.Required(CONF_SURNAME, default=child.get(CONF_SURNAME, "")): str,
                vol.Required(CONF_USERNAME, default=child.get(CONF_USERNAME, "")): str,
                vol.Optional(school_label, description=child.get(CONF_SCHOOL, "")): bool,
            }
        )

        if user_input is not None:
            # Update values
            child[CONF_NAME] = user_input[CONF_NAME]
            child[CONF_SURNAME] = user_input[CONF_SURNAME]
            child[CONF_SCHOOL] = child.get(CONF_SCHOOL) if not user_input.get(school_label) else ""
            child[CONF_USERNAME] = user_input[CONF_USERNAME]

            self.children[child_id] = child  # type: ignore[assignment]

            if not user_input.get(school_label, False):
                return self.async_create_entry(title="", data={CONF_CHILDREN: self.children})

            self._edit_school_for = child_id
            self.async_create_entry(title="", data={CONF_CHILDREN: self.children})
            return await self.async_step_select_city()

        return self.async_show_form(step_id="edit_child", data_schema=data_schema)

    async def async_step_select_child_to_delete(self, user_input=None):
        """Delete a child."""

        options = {
            cid: f"{child.get(CONF_NAME, '')} {child.get(CONF_SURNAME, '')}".strip()
            for cid, child in self.children.items()
        }

        data_schema = vol.Schema({vol.Required("child_id"): vol.In(options)})

        if user_input is not None:
            child_id = user_input["child_id"]
            self.children.pop(child_id)
            return self.async_create_entry(title="", data={CONF_CHILDREN: self.children})

        return self.async_show_form(step_id="select_child_to_delete", data_schema=data_schema)
