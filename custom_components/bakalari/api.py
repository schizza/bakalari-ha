"""API module for Bakalari integration.

This module provides an interface to interact with the Bakalari ASYNC API.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
import logging
from typing import Any, Literal, TypedDict, TypeVar, cast

from async_bakalari_api import Bakalari, Komens, Marks, Timetable
from async_bakalari_api.datastructure import Credentials
from async_bakalari_api.exceptions import Ex
from async_bakalari_api.komens import MessageContainer
from async_bakalari_api.marks import SubjectsBase
from async_bakalari_api.timetable import TimetableWeek
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHILDREN,
    CONF_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SERVER,
    CONF_SURNAME,
    CONF_USER_ID,
    CONF_USERNAME,
    RATE_LIMIT_EXCEEDED,
    ChildRecord,
)
from .utils import redact_child_info

_LOGGER = logging.getLogger(__name__)
_fetch_lock: asyncio.Lock = asyncio.Lock()
_entry_update_lock: asyncio.Lock = asyncio.Lock()

T = TypeVar("T")


class _ChainStep(TypedDict, total=False):
    """Step in the chain of API calls."""

    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    follow_result: bool  # If true, call next step in chain if previous step was successful


class BakalariClient:
    """API client for Bakalari."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, child_id: str):
        """Initialize the BakalariClient.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            entry (ConfigEntry): The configuration entry.
            child_id (str): child id

        """

        self.hass: HomeAssistant = hass
        self.entry: ConfigEntry[Any] = entry
        self.child_id: str = child_id
        self.lib: Bakalari | None = None
        self._lib_lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
        self._last_tokens: tuple[str, str] | None = None

        _LOGGER.warning(
            "[BakalariClient.__init__] Created BakalariClient instance for child_id=%s",
            self.child_id,
        )

    def _current_entry(self) -> ConfigEntry:
        """Get the current config entry."""
        return self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry

    def _current_child(self) -> ChildRecord:
        """Get the current child record."""
        entry = self._current_entry()
        return entry.options[CONF_CHILDREN][self.child_id]

    async def _is_lib(self) -> Bakalari:
        """Check if we have Bakalari initialized, otherwise create new instance of Bakalari for the child."""
        child = self._current_child()
        server = child.get(CONF_SERVER)

        if self.lib is None:
            async with self._lib_lock:
                if self.lib is None:
                    cred: Credentials = Credentials.create_from_json(
                        data={
                            "user_id": child.get(CONF_USER_ID),
                            "username": child.get(CONF_USERNAME),
                            "access_token": child.get(CONF_ACCESS_TOKEN),
                            "refresh_token": child.get(CONF_REFRESH_TOKEN),
                        }
                    )
                    self.lib = Bakalari(server=server, credentials=cred)
                    _LOGGER.warning(
                        "Bakalari instance created for child_id=%s With parameters: %s",
                        self.child_id,
                        redact_child_info(child),
                    )

        self._last_tokens = self._snapshot_tokens()

        _LOGGER.warning(
            "Bakalari instance already exists. With parameters: user_id: %s, username: %s. Child_id is set to %s",
            self.lib.credentials.user_id,
            self.lib.credentials.username,
            self.child_id,
        )
        return self.lib

    def _snapshot_tokens(self) -> tuple[Any, Any] | None:
        """Snapshot tokens."""

        if not self.lib or not getattr(self.lib, "credentials", None):
            _LOGGER.warning("[BakalariClient._snapshot_tokens] No lib or credentials available.")
            return None
        cred = self.lib.credentials
        _LOGGER.warning(
            "[BakalariClient._snapshot_tokens] Snapshot tokens for user_id=%s:",
            cred.user_id,
        )
        return (getattr(cred, CONF_ACCESS_TOKEN, None), getattr(cred, CONF_REFRESH_TOKEN, None))

    def _tokens_changed(self) -> bool:
        """Verify token change."""

        current = self._snapshot_tokens()
        return bool(current and current != self._last_tokens)

    async def _save_tokens_if_changed(self) -> None:
        """Save tokens if changed."""

        # tokens did not change, nothing to do
        if not self._tokens_changed():
            return

        # tokens changed, use global lock to avoid race conditions
        async with _entry_update_lock:
            if not self._tokens_changed():
                return
            cred = self.lib.credentials  # use current credentials
            entry = self._current_entry()
            new_children = dict(entry.options.get(CONF_CHILDREN, {}))
            child: ChildRecord = dict(new_children[self.child_id])
            child[CONF_ACCESS_TOKEN] = cred.access_token
            child[CONF_REFRESH_TOKEN] = cred.refresh_token
            new_children[self.child_id] = child

            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_CHILDREN: new_children}
            )
            self._last_tokens = (cred.access_token or "", cred.refresh_token or "")
            _LOGGER.warning(
                "Bakalari instance saved tokens on change for child_id=%s (user_id from credentials=%s). With parameters: %s",
                self.child_id,
                cred.user_id,
                redact_child_info(child),
            )

    async def async_get_messages(self) -> list[MessageContainer]:
        """Get messages from Bakalari API."""

        async with _fetch_lock:
            lib: Bakalari = await self._is_lib()
            komens: Komens = Komens(lib)
            _LOGGER.warning(
                "Komens using lib with user_id: %s and username: %s",
                lib.credentials.user_id,
                lib.credentials.username,
            )

            # await komens.fetch_messages()
            try:
                messages: Messages = await komens.fetch_messages()
                today = datetime.today().date()
                start_of_school_year = datetime(year=today.year, month=10, day=1).date()
                data = messages.get_messages_by_date(date=start_of_school_year, to_date=today)

            except Exception as e:
                _LOGGER.error("Failed to fetch messages from Bakalari API: %s", str(e))
                _LOGGER.error(RATE_LIMIT_EXCEEDED)
                data = []

            await self._save_tokens_if_changed()

            # data = await komens.get_messages()
            # return data
            # For now, just return an empty dict or placeholder
            _LOGGER.info(
                "Messages for child_id %s: %s (username: %s)",
                lib.credentials.user_id,
                data,
                lib.credentials.username,
            )
            return data

    async def async_get_timetable_permanent(self) -> TimetableWeek:
        """Fetch timetable."""

        lib: Bakalari = await self._is_lib()

        async with _fetch_lock:
            try:
                async with Timetable(bakalari=lib) as timetable:
                    data: TimetableWeek = await timetable.fetch_permanent()
            except Exception as e:
                _LOGGER.error("Failed to fetch timetable from Bakalari API: %s", str(e))
                _LOGGER.error(RATE_LIMIT_EXCEEDED)
                data: TimetableWeek = []

        await self._save_tokens_if_changed()

        return data

    async def async_get_marks(self) -> list[SubjectsBase]:
        """Get marks from Bakalari API."""

        lib = await self._is_lib()
        marks = Marks(lib)

        await marks.fetch_marks()
        data = await marks.get_marks_all()

        await self._save_tokens_if_changed()

        # data = await marks.get_marks()
        # return data
        # For now, just return an empty dict or placeholder
        return data

    async def async_get_timetable_actual(
        self, for_date: datetime | date | None = None
    ) -> TimetableWeek:
        """Fetch actual timetable for a specific date.

        If for_date is None, the API will default to today.
        """
        lib: Bakalari = await self._is_lib()

        async with _fetch_lock:
            try:
                async with Timetable(bakalari=lib) as timetable:
                    data: TimetableWeek = await timetable.fetch_actual(for_date=for_date)
            except Exception as e:
                _LOGGER.error("Failed to fetch actual timetable from Bakalari API: %s", str(e))
                _LOGGER.error(RATE_LIMIT_EXCEEDED)
                data: TimetableWeek = []

        await self._save_tokens_if_changed()

        return data
