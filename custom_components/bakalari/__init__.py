"""Custom component for Bakalari API."""

from __future__ import annotations

import asyncio
import logging

from async_bakalari_api import configure_logging
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .children import ChildrenIndex
from .const import DOMAIN, MANUFACTURER, MODEL, PLATFORMS, SW_VERSION
from .coordinator_marks import BakalariMarksCoordinator
from .coordinator_messages import BakalariMessagesCoordinator
from .coordinator_timetable import BakalariTimetableCoordinator
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

    _format = f"%(asctime)s - %(levelname)s [%(name)s] %(funcName)s{reset}\nMessage: %(message)s)"
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

    _dev_console_handler_for(
        logging.getLogger("custom_components.bakalari"), CustomFormatter()
    )
    hass.data.setdefault(DOMAIN, {})
    return True


def _dev_console_handler_for(
    logger: logging.Logger, formatter: logging.Formatter | None
) -> None:
    """Přidej konzolový handler jen když žádný není – vhodné pro lokální skripty, NE pro HA."""
    # pokud už nějaké handlery existují (na loggeru NEBO u předků), nedělej nic
    # if logger.hasHandlers():
    #     return
    existing = [h for h in logger.handlers if getattr(h, "_bakalari_dev", False)]
    if existing:
        if formatter is not None:
            existing[0].setFormatter(formatter)
        logger.propagate = False
        configure_logging(logger.getEffectiveLevel())
        return

    h = logging.StreamHandler()  # default: stderr
    if formatter is None:
        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    h.setFormatter(formatter)
    h._bakalari_dev = True  # pyright: ignore[reportAttributeAccessIssue]

    # level nech na loggeru; handler level nenech NOTSET explicitně – zbytečné
    logger.addHandler(h)
    # Zachovej propagaci, ať se to dá přesměrovat nadřazeným loggerem, pokud se objeví.
    logger.propagate = False
    configure_logging(logger.getEffectiveLevel())


def _register_devices(
    hass: HomeAssistant, entry: ConfigEntry, children: ChildrenIndex
) -> None:
    """Register one device per child in the device registry."""
    devreg = dr.async_get(hass)
    for child in children.children:
        devreg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={device_ident(entry.entry_id, child.key)},
            manufacturer=MANUFACTURER,
            name=f"Bakaláři – {child.display_name}",
            model=MODEL,
            sw_version=SW_VERSION,
        )


def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register integration services."""

    async def _srv_mark_seen(call) -> None:
        ceid = entry.entry_id
        coord = hass.data[DOMAIN][ceid]["marks"]
        await coord.async_mark_seen(call.data["mark_id"], call.data.get("child_key"))
        await coord.async_request_refresh()

    async def _srv_refresh(call) -> None:  # noqa: ARG001
        await hass.data[DOMAIN][entry.entry_id]["marks"].async_refresh()

    async def _srv_mark_message_seen(call) -> None:
        ceid = entry.entry_id
        coord = hass.data[DOMAIN][ceid]["messages"]
        await coord.async_mark_message_seen(
            call.data["message_id"], call.data.get("child_key")
        )
        await coord.async_refresh()

    async def _srv_refresh_messages(call) -> None:  # noqa: ARG001
        await hass.data[DOMAIN][entry.entry_id]["messages"].async_refresh()

    async def _srv_refresh_timetable(call) -> None:  # noqa: ARG001
        await hass.data[DOMAIN][entry.entry_id]["timetable"].async_refresh()

    async def _srv_sign_marks(call) -> None:
        child_key = call.data["child_key"]
        coord: BakalariMarksCoordinator = hass.data[DOMAIN][entry.entry_id]["marks"]
        try:
            await coord.async_sign_marks(child_key, call.data["subjects"])
        except Exception as err:
            msg = f"Nepodařilo se podepsat známky pro {child_key}: {err}"
            raise HomeAssistantError(msg) from err
        else:
            await coord.async_refresh()

    hass.services.async_register(DOMAIN, "mark_as_seen", _srv_mark_seen)
    hass.services.async_register(DOMAIN, "refresh", _srv_refresh)
    hass.services.async_register(DOMAIN, "mark_message_as_seen", _srv_mark_message_seen)
    hass.services.async_register(DOMAIN, "refresh_messages", _srv_refresh_messages)
    hass.services.async_register(DOMAIN, "refresh_timetable", _srv_refresh_timetable)
    hass.services.async_register(DOMAIN, "sign_all_marks", _srv_sign_marks)


def _register_websocket(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register WebSocket API commands."""

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
        data = hass.data[DOMAIN][ceid]["marks"].select_marks(child_key, limit)
        connection.send_result(msg["id"], {"items": data})

    websocket_api.async_register_command(hass, ws_get_marks)

    @websocket_api.websocket_command(  # type: ignore[attr-defined]
        {
            vol.Required("type"): f"{DOMAIN}/get_messages",
            vol.Required("config_entry_id"): str,
            vol.Optional("child_key"): str,
            vol.Optional("limit", default=50): int,
        }
    )
    @websocket_api.async_response  # type: ignore[attr-defined]
    async def ws_get_messages(hass_, connection, msg):  # noqa: ANN001
        ceid = msg["config_entry_id"]
        limit = msg.get("limit", 50)
        child_key = msg.get("child_key")
        data = hass.data[DOMAIN][ceid]["messages"].select_messages(child_key, limit)
        connection.send_result(msg["id"], {"items": data})

    websocket_api.async_register_command(hass, ws_get_messages)

    @websocket_api.websocket_command(  # type: ignore[attr-defined]
        {
            vol.Required("type"): f"{DOMAIN}/get_timetable",
            vol.Required("config_entry_id"): str,
            vol.Optional("child_key"): str,
            vol.Optional("limit", default=3): int,
        }
    )
    @websocket_api.async_response  # type: ignore[attr-defined]
    async def ws_get_timetable(hass_, connection, msg):  # noqa: ANN001
        ceid = msg["config_entry_id"]
        limit = msg.get("limit", 3)
        child_key = msg.get("child_key")
        data = hass.data[DOMAIN][ceid]["timetable"].select_timetable(child_key, limit)
        connection.send_result(msg["id"], {"items": data})

    websocket_api.async_register_command(hass, ws_get_timetable)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up of Bakalari component."""

    children = ChildrenIndex.from_entry(entry)

    coord_marks = BakalariMarksCoordinator(hass, entry, children)
    coord_msgs = BakalariMessagesCoordinator(hass, entry, children)
    coord_tt = BakalariTimetableCoordinator(hass, entry, children)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "children": children,
        "marks": coord_marks,
        "messages": coord_msgs,
        "timetable": coord_tt,
    }

    # Do the first refresh in parallel
    await asyncio.gather(
        coord_marks.async_config_entry_first_refresh(),
        coord_msgs.async_config_entry_first_refresh(),
        coord_tt.async_config_entry_first_refresh(),
    )

    # Device Registry
    _register_devices(hass, entry, children)

    # Services and WebSocket API
    _register_services(hass, entry)
    _register_websocket(hass, entry)

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
