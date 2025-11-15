"""Custom component for Bakalari API."""

from __future__ import annotations

import logging

from async_bakalari_api import configure_logging
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .const import DOMAIN, MANUFACTURER, MODEL, PLATFORMS
from .coordinator import BakalariCoordinator
from .utils import device_ident

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


class CustomFormatter(logging.Formatter):
    """Custom formater for module."""

    black = "\u001b[30m"
    yellow = "\u001b[33m"
    red = "\u001b[31m"
    bold_red = "\x1b[31;1m"
    reset = "\u001b[0m"
    green = "\u001b[32m"
    grey = "\u001b[30m"
    blue = "\u001b[34m"
    magenta = "\u001b[35m"
    cyan = "\u001b[36m"
    white = "\u001b[37m"

    _format = f"%(asctime)s - %(levelname)s [%(name)s]\n{reset}Message: %(message)s)"
    dateformat = "%d/%m/%Y %H:%M:%S"

    FORMATS = {
        logging.DEBUG: blue + _format + reset,
        logging.INFO: green + _format + reset,
        logging.WARNING: yellow + _format + reset,
        logging.ERROR: bold_red + _format + reset,
        logging.CRITICAL: bold_red + _format + reset,
    }

    def format(self, record):
        """Format string."""

        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt=self.dateformat)
        return formatter.format(record)


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Bakalari component."""
    hass.data.setdefault(DOMAIN, {})
    return True


def _dev_console_handler_for(
    logger: logging.Logger, formatter: logging.Formatter | None
) -> None:
    """Přidej konzolový handler jen když žádný není – vhodné pro lokální skripty, NE pro HA."""
    # pokud už nějaké handlery existují (na loggeru NEBO u předků), nedělej nic
    # if logger.hasHandlers():
    #     return

    h = logging.StreamHandler()  # default: stderr
    if formatter is None:
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    h.setFormatter(formatter)

    # level nech na loggeru; handler level nenech NOTSET explicitně – zbytečné
    logger.addHandler(h)
    # Zachovej propagaci, ať se to dá přesměrovat nadřazeným loggerem, pokud se objeví.
    logger.propagate = False
    configure_logging(logger.getEffectiveLevel())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up of Bakalari component."""
    _dev_console_handler_for(
        logging.getLogger("custom_components.bakalari"), CustomFormatter()
    )

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
        await coord.async_refresh()

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
