"""API module for Bakalari integration.

This module provides an interface to interact with the Bakalari ASYNC API.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
import logging
from time import time
from typing import Any, Literal, TypeVar

from async_bakalari_api import Bakalari, Komens, Marks, Timetable
from async_bakalari_api.datastructure import Credentials
from async_bakalari_api.exceptions import Ex
from async_bakalari_api.komens import MessageContainer
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
from .utils import ensure_child_record, redact_child_info

_LOGGER = logging.getLogger(__name__)
_fetch_lock: asyncio.Lock = asyncio.Lock()
_entry_update_lock: asyncio.Lock = asyncio.Lock()

_reauth_state_lock: asyncio.Lock = asyncio.Lock()
_reauth_state: dict[str, float] = {}


T = TypeVar("T")


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

        _LOGGER.debug(
            "[class=%s module=%s] Created BakalariClient instance for child_id=%s",
            self.__class__.__name__,
            __name__,
            self.child_id,
        )

    def api_call(
        *,
        label: str,
        reauth_reason: str | None = None,
        default: T,
        use_lock: bool = True,
    ) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
        """Decorate API call.

        Decorated function must have (self, lib, *args, **kwargs) -> Awaitable[T] signature.
        `lib` is Bakalari instance
        """

        def _decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
            async def _wrapper(self, *args: Any, **kwargs: Any) -> T:
                async def _callable_fn(lib) -> T:
                    return await fn(self, lib, *args, **kwargs)

                return await self._api_call(
                    label=label,
                    reauth_reason=reauth_reason,
                    default=default,
                    use_lock=use_lock,
                    callable_fn=_callable_fn,
                )

            return _wrapper

        return _decorator

    async def _api_call(
        self,
        *,
        label: str,
        reauth_reason: str | None = None,
        default: T,
        use_lock: bool = True,
        callable_fn: Callable[[Bakalari], Awaitable[T]] | None = None,
    ) -> T:
        """Wrap a single callable(lib) API operation with auth, error handling and token persistence."""

        async def _execute() -> T:
            _lib = await self._is_lib()
            if _lib is None:
                _LOGGER.error(
                    "[class=%s module=%s] Lib is not available for %s",
                    self.__class__.__name__,
                    __name__,
                    label,
                )
                await self._reset_tokens_and_client()
                await self._start_reauth(reauth_reason or "")
                return default

            try:
                if callable_fn is None:
                    raise ValueError("callable_fn must be provided")
                return await callable_fn(_lib)
            except (
                Ex.RefreshTokenRedeemd,
                Ex.RefreshTokenExpired,
                Ex.InvalidToken,
                Ex.InvalidRefreshToken,
            ) as err:
                _LOGGER.error(
                    "[class=%s module=%s] Authentication error while %s for child_id=%s: %s",
                    self.__class__.__name__,
                    __name__,
                    label,
                    self.child_id,
                    err,
                )
                await self._reset_tokens_and_client()
                await self._start_reauth(reauth_reason or "Invalid credentials")
                return default
            except Exception as e:
                _LOGGER.error(
                    "[class=%s module=%s] Failed while %s: %s",
                    self.__class__.__name__,
                    __name__,
                    label,
                    e,
                )
                _LOGGER.error(RATE_LIMIT_EXCEEDED)
                return default
            finally:
                await self._save_tokens_if_changed()

        if use_lock:
            async with _fetch_lock:
                return await _execute()
        return await _execute()

    def _current_entry(self) -> ConfigEntry:
        """Get the current config entry."""
        return (
            self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        )

    def _current_child(self) -> ChildRecord:
        """Get the current child record."""

        entry = self._current_entry()
        return entry.options[CONF_CHILDREN][self.child_id]

    def _validate_child_tokens(self, child: ChildRecord) -> bool:
        """Validate child tokens."""

        if not child.get(CONF_ACCESS_TOKEN) and not child.get(CONF_REFRESH_TOKEN):
            _LOGGER.error(
                "[class=%s module=%s] Child (child_id=%s) must have valid access and refresh tokens",
                self.__class__.__name__,
                __name__,
                child.get(CONF_USER_ID),
            )
            return False
        return True

    async def _is_lib(self) -> Bakalari | None:
        """Check if we have Bakalari initialized, otherwise create new instance of Bakalari for the child."""
        child = self._current_child()
        server = child.get(CONF_SERVER)

        if self.lib is None:
            async with self._lib_lock:
                if self.lib is None:
                    if not self._validate_child_tokens(child):
                        return None

                    cred: Credentials = Credentials.create_from_json(
                        data={
                            "user_id": child.get(CONF_USER_ID),
                            "username": child.get(CONF_USERNAME),
                            "access_token": child.get(CONF_ACCESS_TOKEN),
                            "refresh_token": child.get(CONF_REFRESH_TOKEN),
                        }
                    )

                    session = async_get_clientsession(self.hass)
                    self.lib = Bakalari(
                        server=server, credentials=cred, session=session
                    )
                    _LOGGER.debug(
                        "[class=%s module=%s] Bakalari library instance created for child_id=%s With parameters: %s",
                        self.__class__.__name__,
                        __name__,
                        self.child_id,
                        redact_child_info(child),
                    )

        self._last_tokens = self._snapshot_tokens()

        if not self._validate_child_tokens(child):
            _LOGGER.error(
                "[class=%s module=%s] Bakalari instance for child_id=%s exists, but without valid tokens provided! This should not happen!",
                self.__class__.__name__,
                __name__,
                child.get(CONF_USER_ID),
            )
            return None

        _LOGGER.debug(
            "[class=%s module=%s] Bakalari library instance already exists. Reusing current [child_id: %s, username: %s]",
            self.__class__.__name__,
            __name__,
            self.child_id,
            self.lib.credentials.username,
        )
        return self.lib

    async def _reset_tokens_and_client(self) -> None:
        """Reset stored tokens in entry and drop API client to force re-login."""
        async with _entry_update_lock:
            entry = self._current_entry()
            new_children = dict(entry.options[CONF_CHILDREN])
            child: ChildRecord = ensure_child_record(new_children, self.child_id)
            child[CONF_ACCESS_TOKEN] = ""
            child[CONF_REFRESH_TOKEN] = ""
            new_children[self.child_id] = child

            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_CHILDREN: new_children}
            )
        self._last_tokens = None
        self.lib = None
        _LOGGER.warning(
            "[class=%s module=%s] Cleared tokens and reset client for child_id=%s; reauth required.",
            self.__class__.__name__,
            __name__,
            self.child_id,
        )

    def _reauth_key(self) -> str:
        return f"{self.entry.entry_id}:{self.child_id}"

    async def _should_request_reauth(self) -> bool:
        key = self._reauth_key()
        async with _reauth_state_lock:
            last = _reauth_state.get(key)
            return last is None

    async def _mark_reauth_requested(self) -> None:
        key = self._reauth_key()
        async with _reauth_state_lock:
            _reauth_state[key] = time()

    async def _clear_reauth_flag(self) -> None:
        key = self._reauth_key()
        async with _reauth_state_lock:
            if key in _reauth_state:
                del _reauth_state[key]

    async def _start_reauth(self, reason: str) -> None:
        """Start Home Assistant reauth flow for this entry."""
        try:
            if not await self._should_request_reauth():
                _LOGGER.warning(
                    "[class=%s module=%s] Reauthentication already requested for child_id=%s, skipping duplicate (reason: %s).",
                    self.__class__.__name__,
                    __name__,
                    self.child_id,
                    reason,
                )
                return
            await self._mark_reauth_requested()
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    self.entry.domain,
                    context={"source": SOURCE_REAUTH, "entry_id": self.entry.entry_id},
                    data={
                        "entry_id": self.entry.entry_id,
                        "child_id": self.child_id,
                        "server": self._current_child().get(CONF_SERVER),
                        "username": self._current_child().get(CONF_USERNAME),
                        "displayName": f"{self._current_child().get(CONF_NAME)} {self._current_child().get(CONF_SURNAME)}",
                        "reason": reason,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "[class=%s module=%s] Failed to start reauth flow for child_id=%s",
                self.__class__.__name__,
                __name__,
                self.child_id,
            )
            await self._clear_reauth_flag()

    def _snapshot_tokens(self) -> tuple[Any, Any] | None:
        """Snapshot tokens."""

        if not self.lib or not getattr(self.lib, "credentials", None):
            _LOGGER.error(
                "[class=%s module=%s]  No library or credentials available.",
                self.__class__.__name__,
                __name__,
            )
            return None
        cred = self.lib.credentials
        _LOGGER.debug(
            "[class=%s module=%s] Snapshot tokens for child_id=%s:",
            self.__class__.__name__,
            __name__,
            self.child_id,
        )
        return (
            getattr(cred, CONF_ACCESS_TOKEN, None),
            getattr(cred, CONF_REFRESH_TOKEN, None),
        )

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

            child: ChildRecord = ensure_child_record(new_children, self.child_id)

            child[CONF_ACCESS_TOKEN] = cred.access_token or ""
            child[CONF_REFRESH_TOKEN] = cred.refresh_token or ""
            new_children[self.child_id] = child

            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_CHILDREN: new_children}
            )
            self._last_tokens = (cred.access_token or "", cred.refresh_token or "")
            _LOGGER.debug(
                "[class=%s module=%s]: Saved tokens on change for child_id=%s (%s)",
                self.__class__.__name__,
                __name__,
                self.child_id,
                redact_child_info(child),
            )
        await self._clear_reauth_flag()

    #
    #  ------ API methods -------
    #
    @api_call(label="Messages", reauth_reason="Messages", default=[], use_lock=True)
    async def async_get_messages(self, lib) -> list[MessageContainer]:
        """Get messages from Bakalari API."""

        today = datetime.today().date()

        # TODO: change to actual year, while sensors are refactored!
        start_of_school_year = datetime(year=today.year, month=10, day=1).date()

        _LOGGER.debug(
            "[class=%s module=%s] Fetching messages for child_id=%s",
            self.__class__.__name__,
            __name__,
            self.child_id,
        )

        _komens = Komens(lib)
        await _komens.fetch_messages()

        data = _komens.messages.get_messages_by_date(start_of_school_year, today)

        _LOGGER.info(
            "[class=%s module=%s] Messages for child_id %s: %s",
            self.__class__.__name__,
            __name__,
            self.child_id,
            data,
        )
        return data

    @api_call(
        label="pemanent timetable",
        reauth_reason="permanent timetable",
        default=TimetableWeek(),
    )
    async def async_get_timetable_permanent(self, lib) -> TimetableWeek:
        """Fetch permanent timetable."""
        _LOGGER.debug(
            "[class=%s module=%s] Fetching permanent timetable.",
            self.__class__.__name__,
            __name__,
        )
        _timetable = Timetable(lib)
        return await _timetable.fetch_permanent()

    @api_call(
        label="async_get_timetable_actual",
        reauth_reason="get_timetable_actual",
        default=TimetableWeek(),
    )
    async def async_get_timetable_actual(
        self,
        lib,
        for_date: datetime | date | None = None,
    ) -> TimetableWeek:
        """Fetch actual timetable for a specific date."""

        _LOGGER.debug(
            "[class=%s module=%s]: Fetching actual timetable. (for_date=%s",
            self.__class__.__name__,
            __name__,
            for_date,
        )

        _timetable = Timetable(lib)
        return await _timetable.fetch_actual(for_date)

    @api_call(
        label="get_marks_snapshot",
        default=({"subjects": {}, "marks_grouped": {}, "marks_flat": []}, {}),
        reauth_reason="get_marks_snapshoot",
    )
    async def async_get_marks_snapshot(
        self,
        lib,
        *,
        date_from: datetime | date | None = None,
        date_to: datetime | date | None = None,
        subject_id: str | None = None,
        to_dict: bool = True,
        order: Literal["asc", "desc"] = "desc",
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Get snapshot of marks (subjects, grouped, flat) using new API."""

        # Normalize date inputs to datetime (library expects datetime)
        df = None
        dt_to = None
        if date_from is not None:
            if isinstance(date_from, datetime):
                df = date_from
            else:
                df = datetime.combine(date_from, datetime.min.time())
        if date_to is not None:
            if isinstance(date_to, datetime):
                dt_to = date_to
            else:
                dt_to = datetime.combine(date_to, datetime.min.time())

        _LOGGER.debug(
            "[class=%s module=%s] Fetching marks snapshot (from=%s to=%s subject_id=%s order=%s)",
            self.__class__.__name__,
            __name__,
            df,
            dt_to,
            subject_id,
            order,
        )

        _marks = Marks(lib)
        await _marks.fetch_marks()
        _snapshot = await _marks.get_snapshot(
            date_from=df,
            date_to=dt_to,
            subject_id=subject_id,
            order=order,
            to_dict=to_dict,
        )
        _all_marks_summary = await _marks.get_all_marks_summary()

        return (dict(_snapshot), _all_marks_summary)
