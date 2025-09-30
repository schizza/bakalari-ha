"""Základní config_flow.py pro Home Assistant integraci Bakalari."""

from __future__ import annotations

import logging

from async_bakalari_api import Bakalari
from async_bakalari_api.bakalari import Schools
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SCHOOLS_CACHE_FILE
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

    async def _load_schools(self) -> bool:
        """Load schools from cache or fetch new ones from server."""

        api = Bakalari()

        schools_storage = Store(self.hass, 1, SCHOOLS_CACHE_FILE)
        schools_cache = await schools_storage.async_load()

        if schools_cache is None:
            _LOGGER.debug("Fetching new schools from server ")
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> config_entries.OptionsFlow:
        """Options flow handler."""

        return BakalariOptionsFlow(config_entry)
