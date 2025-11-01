"""Custom component for Bakalari API."""

from __future__ import annotations

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .const import DOMAIN, MANUFACTURER, MODEL, PLATFORMS
from .coordinator import BakalariCoordinator
from .utils import device_ident

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Bakalari component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up of Bakalari component."""

    coord = BakalariCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coord}
    await coord.async_config_entry_first_refresh()

    # Device Registry: one device per child
    devreg = dr.async_get(hass)
    for child in coord.child_list:
        devreg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={device_ident(entry.entry_id, child.key)},
            manufacturer=MANUFACTURER,
            name=f"Bakaláři – {child.display_name}",
            model=MODEL,
            sw_version=coord.api_version,
        )

    # Services
    async def _srv_mark_seen(call) -> None:
        await coord.async_mark_seen(call.data["mark_id"], call.data.get("child_key"))
        await coord.async_request_refresh()

    async def _srv_refresh(call) -> None:  # noqa: ARG001
        await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, "mark_as_seen", _srv_mark_seen)
    hass.services.async_register(DOMAIN, "refresh", _srv_refresh)

    # WebSocket API
    @websocket_api.websocket_command(  # type: ignore[attr-defined]
        {
            vol.Required("type"): f"{DOMAIN}/get_marks",
            vol.Required("config_entry_id"): str,
            vol.Optional("child_key"): str,
            vol.Optional("limit", default=50): int,
        }
    )
    @websocket_api.async_response  # type: ignore[attr-defined]
    async def ws_get_marks(hass_, connection, msg):  # noqa: ANN001
        ceid = msg["config_entry_id"]
        limit = msg.get("limit", 50)
        child_key = msg.get("child_key")
        data = hass.data[DOMAIN][ceid]["coordinator"].select_marks(child_key, limit)
        connection.send_result(msg["id"], {"items": data})

    websocket_api.async_register_command(hass, ws_get_marks)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
