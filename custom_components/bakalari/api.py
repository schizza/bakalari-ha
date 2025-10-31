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

    def api_call(
        *,
        label: str,
        reauth_reason: str | None = None,
        default: T,
        use_lock: bool = True,
    ) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
        """Decorate API call.

        Decoreated function must have (self, lib, *args, **kwargs) -> Awaitable[T] signature.
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
                    mode="callable",
                    callable_fn=_callable_fn,
                )

            return _wrapper

        return _decorator

    async def _api_call(  # noqa: C901
        self,
        *,
        label: str,
        reauth_reason: str | None = None,
        default: T,
        use_lock: bool = True,
        mode: Literal["single", "chain", "callable"] = "single",
        module: type | None = None,
        method: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        chain_module: type | None = None,
        chain: list[_ChainStep] | None = None,
        callable_fn: Callable[[Bakalari], Awaitable[T]] | None = None,
    ) -> T:
        """Wrap API call for Bakalari.

        label: str - label for logging and error messages
        reauth_reason: str | None - reason for reauthentication if auth fails
        default: T - default return value
        mode: Literal["single", "chain", "callable"] - mode of API call
        module: type | None - module for single API call (Komens, Timetable, ...)
        method: str | None - method for single API call (method of module to call)
        args: tuple[Any, ...] - arguments for single API call
        kwargs: dict[str, Any] | None - keyword arguments for single API call
        chain_module: type | None - module for chain of API calls
        chain: list[_ChainStep] | None - chain of API calls
        callable_fn: Callable[[Bakalari], Awaitable[T]] | None - custom callable function

        - mode: single - single API call - module + method (args, kwargs)
        - mode: chain - chain of API calls - chain_module + chain([...])
        - mode: callable - custom callable function - callable_fn(lib) -> Awaitable[T]
        """

        if kwargs is None:
            kwargs = {}

        async def _execute() -> T:  # noqa: C901 # type: ignore[reportReturnType]
            """Execute."""

            _lib = await self._is_lib()
            if _lib is None:
                _LOGGER.error("Lib is not available for %s", label)
                await self._reset_tokens_and_client()
                await self._start_reauth(reauth_reason or "")
                return default

            try:
                if mode == "single":
                    target = _lib if module is None else module(_lib)
                    func = getattr(target, method)  # type: ignore[arg-type]
                    result = func(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        result = await result
                    return result

                if mode == "chain":
                    if chain is None:
                        raise ValueError("chain cannot be None in 'chian' mode.")
                    target: Any = _lib if chain_module is None else chain_module(_lib)
                    current: Any = target
                    for step in chain:
                        step_args = step.get("args", ())
                        step_kwargs = step.get("kwargs", {})
                        func = getattr(current, step["method"])
                        out = func(*step_args, **step_kwargs)
                        current = await out if asyncio.iscoroutine(out) else out
                        if step.get("follow_result", False):
                            pass
                        else:
                            current = target
                elif mode == "callable":
                    if callable_fn is None:
                        raise ValueError("callable_fn cannot be None in 'callable' mode.")
                    return await callable_fn(_lib)

                else:
                    raise ValueError(f"Unsupported mode: {mode}")
            except (Ex.RefreshTokenRedeemd, Ex.InvalidToken) as err:
                _LOGGER.error(
                    "Authentication error while %s for child_id=%s: %s", label, self.child_id, err
                )
                await self._reset_tokens_and_client()
                await self._start_reauth(reauth_reason or "")
                return default

            except Exception as e:
                _LOGGER.error("Failed while %s: %s", label, e)
                _LOGGER.error(RATE_LIMIT_EXCEEDED)
                return default

            finally:
                await self._save_tokens_if_changed()

        if mode == "chain":

            async def _chain_exec() -> T:
                _lib = await self._is_lib()
                if _lib is None:
                    _LOGGER.error("Lib is not available for %s", label)
                    await self._reset_tokens_and_client()
                    await self._start_reauth(reauth_reason or "")
                    return default
                try:
                    target: Any = _lib if chain_module is None else chain_module(_lib)
                    current: Any = target
                    last_out: Any = None
                    for step in chain or []:
                        step_args = step.get("args", ())
                        step_kwargs = step.get("kwargs", {})
                        func = getattr(current, step["method"])
                        out = func(*step_args, **step_kwargs)
                        last_out = await out if asyncio.iscoroutine(out) else out
                        current = last_out if step.get("follow_result", False) else target
                    return last_out  # type: ignore[return-value]
                except (Ex.RefreshTokenExpired, Ex.RefreshTokenRedeemd, Ex.InvalidToken) as err:
                    _LOGGER.error(
                        "Auth error while %s for child_id=%s: %s", label, self.child_id, err
                    )
                    await self._reset_tokens_and_client()
                    await self._start_reauth(reauth_reason or "")
                    return default

                except Exception as e:
                    _LOGGER.error("Failed while %s: %s", label, str(e))
                    _LOGGER.error(RATE_LIMIT_EXCEEDED)
                    return default
                finally:
                    await self._save_tokens_if_changed()

            if use_lock:
                async with _fetch_lock:
                    return await _chain_exec()
            return await _chain_exec()
        if use_lock:
            async with _fetch_lock:
                return await _execute()
        return await _execute()

    def _current_entry(self) -> ConfigEntry:
        """Get the current config entry."""
        return self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry

    def _current_child(self) -> ChildRecord:
        """Get the current child record."""
        entry = self._current_entry()
        return entry.options[CONF_CHILDREN][self.child_id]

    def _validate_child_tokens(self, child: ChildRecord) -> bool:
        """Validate child tokens."""

        if not child.get(CONF_ACCESS_TOKEN) and not child.get(CONF_REFRESH_TOKEN):
            _LOGGER.error(
                "Child (child_id=%s) must have valid access and refresh tokens",
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
                    self.lib = Bakalari(server=server, credentials=cred, session=session)
                    _LOGGER.warning(
                        "Bakalari instance created for child_id=%s With parameters: %s",
                        self.child_id,
                        redact_child_info(child),
                    )

        self._last_tokens = self._snapshot_tokens()

        if not self._validate_child_tokens(child):
            _LOGGER.error(
                "Bakalari instance for child_id=%s exists, but without valid tokens provided! This should not happen!",
                child.get(CONF_USER_ID),
            )
            return None

        _LOGGER.warning(
            "Bakalari instance already exists. With parameters: user_id: %s, username: %s. Child_id is set to %s",
            self.lib.credentials.user_id,
            self.lib.credentials.username,
            self.child_id,
        )
        return self.lib

    async def _reset_tokens_and_client(self) -> None:
        """Reset stored tokens in entry and drop API client to force re-login."""
        async with _entry_update_lock:
            entry = self._current_entry()
            new_children = dict(entry.options.get(CONF_CHILDREN, {}))
            child: ChildRecord = cast(ChildRecord, new_children.get(self.child_id, {}))
            child[CONF_ACCESS_TOKEN] = ""
            child[CONF_REFRESH_TOKEN] = ""
            new_children[self.child_id] = child

            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_CHILDREN: new_children}
            )
        self._last_tokens = None
        self.lib = None
        _LOGGER.warning(
            "Cleared tokens and reset client for child_id=%s; reauth required.",
            self.child_id,
        )

    async def _start_reauth(self, reason: str) -> None:
        """Start Home Assistant reauth flow for this entry."""
        try:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    self.entry.domain,
                    context={"source": SOURCE_REAUTH},
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
            _LOGGER.exception("Failed to start reauth flow for child_id=%s", self.child_id)

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
            child: ChildRecord = cast(ChildRecord, new_children[self.child_id])
            child[CONF_ACCESS_TOKEN] = cred.access_token or ""
            child[CONF_REFRESH_TOKEN] = cred.refresh_token or ""
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

        today = datetime.today().date()

        # TODO: change to actual year, while sensors are refactored!
        start_of_school_year = datetime(year=today.year, month=10, day=1).date()

        _LOGGER.debug("Fetching messages for child_id=%s", self.child_id)
        data = await self._api_call(
            label="fetching_messages",
            reauth_reason="messages",
            default=[],
            use_lock=True,
            mode="chain",
            chain_module=Komens,
            chain=[
                {"method": "fetch_messages", "args": (), "kwargs": {}, "follow_result": True},
                {
                    "method": "get_messages_by_date",
                    "args": (start_of_school_year,),
                    "kwargs": {"to_date": today},
                },
            ],
        )
        _LOGGER.info("Messages for child_id %s: %s", self.child_id, data)
        return data

    async def async_get_timetable_permanent(self) -> TimetableWeek:
        """Fetch permanent timetable."""
        default: TimetableWeek = TimetableWeek()

        return await self._api_call(
            label="fetching permanent timetable",
            reauth_reason="timetable_permanent",
            default=default,
            mode="single",
            module=Timetable,
            method="fetch_permanent",
        )

    async def async_get_timetable_actual(
        self,
        for_date: datetime | date | None = None,
    ) -> TimetableWeek:
        """Fetch actual timetable for a specific date."""

        default: TimetableWeek = TimetableWeek()
        return await self._api_call(
            label="fetching actual timetable",
            reauth_reason="timetable_actual",
            default=default,
            mode="single",
            module=Timetable,
            method="fetch_actual",
            kwargs={"for_date": for_date},
        )

    async def async_get_marks(self) -> list[SubjectsBase]:
        """Get marks from Bakalari API."""

        default: list[SubjectsBase] = []

        return await self._api_call(
            label="fetching marks",
            reauth_reason="marks",
            default=default,
            mode="chain",
            chain_module=Marks,
            chain=[
                {"method": "fetch_marks", "follow_result": False},
                {"method": "get_marks_all", "follow_result": True},
            ],
        )
