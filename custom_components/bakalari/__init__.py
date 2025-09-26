"""Custom component for Bakalari API."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Bakalari component."""

    # async def _svc_refresh(call: ServiceCall) -> None:
    #     for entry_id, data in hass.data.get(DOMAIN, {}).items():
    #         await data["coordinator"].async_request_refresh()

    # hass.services.async_register(DOMAIN, "refresh", _svc_refresh)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up of Bakalari component."""

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


# async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
#     data = hass.data[DOMAIN][entry.entry_id]
#     coord: BakalariCoordinator = data["coordinator"]
#     seconds = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
#     await coord.async_set_update_interval(seconds)
#     await coord.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data:
        await data["client"].async_close()
    return ok
