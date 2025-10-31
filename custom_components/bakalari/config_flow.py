"""Základní config_flow.py pro Home Assistant integraci Bakalari."""

from __future__ import annotations

import logging

from async_bakalari_api import Bakalari
from async_bakalari_api.bakalari import Schools
from async_bakalari_api.exceptions import Ex
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
import voluptuous as vol

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_REFRESH_TOKEN,
    CONF_SERVER,
    CONF_USERNAME,
    DOMAIN,
    SCHOOLS_CACHE_FILE,
)
from .options_flow import BakalariOptionsFlow

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bakalari."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""

        super().__init__()
        self._schools: Schools | None = None
        self._loading_task = None
        self._reauth_data: dict | None = None

    async def _load_schools(self) -> bool:
        """Load schools from cache or fetch new ones from server."""

        schools_storage = Store(self.hass, 1, SCHOOLS_CACHE_FILE)
        schools_cache = await schools_storage.async_load()

        if schools_cache is None:
            _LOGGER.debug("Fetching new schools from server ")

            async with Bakalari() as api:
                schools_cache = await api.schools_list()

            if schools_cache is None:
                _LOGGER.error("Schools cannot be fetched from server!")
                return False

            await schools_storage.async_save(schools_cache.school_list)
            _LOGGER.debug("Schools saved to cache.")
        else:
            _LOGGER.debug("Schools loaded from cache.")

        return False

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""

        if self._loading_task is None:
            self._loading_task = self.hass.async_create_task(self._load_schools())

            return self.async_show_progress(
                step_id="user",
                progress_action="loading_schools",
                progress_task=self._loading_task,
            )

        return self.async_show_progress_done(next_step_id="complete")

    async def async_step_complete(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the completion step."""

        return self.async_create_entry(title="Bakaláři", data={}, options={"children": []})

    async def async_step_reauth(self, data: dict | None) -> config_entries.ConfigFlowResult:
        """Handle the reauthentication step."""

        self._reauth_data = data or {}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the reauthentication confirmation step."""

        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Required("password"): str,
                }
            )
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                description_placeholders={
                    "displayName": self._reauth_data.get("displayName") or "",
                    "username": self._reauth_data.get("username") or "",
                },
            )

        entry_id = (self._reauth_data or {}).get("entry_id")
        child_id = (self._reauth_data or {}).get("child_id")
        server = (self._reauth_data or {}).get("server")
        username = (self._reauth_data or {}).get("username")

        if not entry_id or not child_id or not server or not username:
            return self.async_abort(reason="reauth_missing_context")

        try:
            async with Bakalari(server) as api:
                credentials = await api.first_login(username, user_input["password"])
        except Ex.InvalidLogin:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required("password"): str}),
                errors={"base": "invalid_auth"},
            )
        except Exception:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required("password"): str}),
                errors={"base": "cannot_connect"},
            )

        # Update entry options with new tokens
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="reauth_entry_not_found")

        children = dict(entry.options.get(CONF_CHILDREN, {}))
        child = dict(children.get(child_id, {}))
        child[CONF_ACCESS_TOKEN] = getattr(credentials, "access_token", "") or ""
        child[CONF_REFRESH_TOKEN] = getattr(credentials, "refresh_token", "") or ""
        # Keep existing username/server, but refresh username if present
        if CONF_USERNAME in (self._reauth_data or {}):
            child[CONF_USERNAME] = username
        if CONF_SERVER in (self._reauth_data or {}):
            child[CONF_SERVER] = server
        children[child_id] = child

        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_CHILDREN: children}
        )

        return self.async_abort(reason="reauth_successful")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> config_entries.OptionsFlow:
        """Options flow handler."""

        return BakalariOptionsFlow(config_entry)
