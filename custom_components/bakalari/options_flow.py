"""Options flow for Bakalari."""

from __future__ import annotations

from typing import Any

from async_bakalari_api import Bakalari, Credentials, Ex, Schools
from homeassistant import config_entries
from homeassistant.helpers.storage import Store
import voluptuous as vol

from .const import SCHOOLS_CACHE_FILE


class BakalariOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Bakalari.

    We should enable add/modify/delete children in this flow.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize BakalariOptionsFlow."""

        self.children = list(config_entry.options.get("children", []))
        self._edit_index = None
        self._schools: Schools | None = None
        self._new_child: dict[str, Any] | None = None

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

        options = {str(i): child["name"] for i, child in enumerate(self.children)}
        options["add"] = "Přidat nové dítě"

        data_schema = vol.Schema({vol.Required("action"): vol.In(options)})

        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_add_child()
            self._edit_index = int(action)
            return await self.async_step_edit_child()

        return self.async_show_form(step_id="init", data_schema=data_schema)

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

        data_schema = vol.Schema({vol.Required("school"): vol.In(_schools)})

        if user_input is not None:
            self._new_child["school"] = user_input["school"]  # pyright: ignore[reportOptionalSubscript]

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
            school_url = self._schools.get_url(self._new_child["school"])  # pyright: ignore[reportOptionalSubscript]

            api = Bakalari(school_url)

            try:
                credentials = await api.first_login(user_input["username"], user_input["password"])

                self._new_child["credentials"] = credentials  # pyright: ignore[reportOptionalSubscript]

            except Ex.InvalidLogin:
                return self.async_show_form(
                    step_id="login",
                    data_schema=data_schema,
                    errors={"base": "invalid_login"},
                )

            self.children.append(self._new_child)

            return self.async_create_entry(title="", data={"children": self.children})

        # we have to login
        return self.async_show_form(step_id="login", data_schema=data_schema)
