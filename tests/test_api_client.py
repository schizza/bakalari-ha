"""Test API client."""

import asyncio
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import custom_components.bakalari.api as api_mod
from custom_components.bakalari.api import BakalariClient


class _FakeKomensMessages:
    """Minimal stub for Komens.messages used by async_get_messages."""

    def __init__(self) -> None:
        self.calls: list[tuple[dt_date, dt_date]] = []

    def get_messages_by_date(self, start: dt_date, end: dt_date):
        self.calls.append((start, end))
        return ["m1"]


class _FakeKomens:
    """Minimal stub for Komens used by async_get_messages/async_fetch_noticeboard."""

    def __init__(
        self,
        lib: Any,
        *,
        with_noticeboard: bool = True,
        noticeboard_container: Any | None = None,
    ) -> None:
        self._with_noticeboard = with_noticeboard
        self.messages = _FakeKomensMessages()
        # Keep this intentionally loose to satisfy type-checkers in tests.
        self.noticeboard_container: Any = noticeboard_container or SimpleNamespace()

    async def fetch_messages(self) -> None:
        return None

    async def fetch_noticeboard(self):
        return self.noticeboard_container


async def _direct_call_via_api_call_wrapper(
    client: BakalariClient,
    method_name: str,
    *,
    lib: Any,
):
    """Invoke a @api_call-decorated method by stubbing client._api_call to run the inner callable_fn.

    This avoids needing a real hass/config entry, while still exercising the wrapper path.
    """

    async def _api_call_stub(
        *,
        label: str,
        reauth_reason: str,
        default: Any,
        use_lock: bool,
        callable_fn,
    ):
        return await callable_fn(lib)

    client._api_call = _api_call_stub  # pyright: ignore[reportAttributeAccessIssue]

    method = getattr(client, method_name)
    return await method()


@pytest.mark.asyncio
async def test_api_call_success(monkeypatch: pytest.MonkeyPatch):
    """Test successful API call."""
    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]

    # Stub library creation and token save
    monkeypatch.setattr(client, "_is_lib", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(client, "_save_tokens_if_changed", AsyncMock(return_value=None))

    async def fn_ok(lib: Any) -> str:
        return "OK"

    # Act
    result = await client._api_call(
        label="test-success",
        reauth_reason="",
        default="DEF",
        use_lock=True,
        callable_fn=fn_ok,
    )

    # Assert
    assert result == "OK"


@pytest.mark.asyncio
async def test_api_call_lib_missing_triggers_reauth(monkeypatch: pytest.MonkeyPatch):
    """Test API call when library is missing."""
    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]

    monkeypatch.setattr(client, "_is_lib", AsyncMock(return_value=None))
    reset_mock = AsyncMock()
    reauth_mock = AsyncMock()
    save_mock = AsyncMock()
    monkeypatch.setattr(client, "_reset_tokens_and_client", reset_mock)
    monkeypatch.setattr(client, "_start_reauth", reauth_mock)
    monkeypatch.setattr(client, "_save_tokens_if_changed", save_mock)

    async def fn_never_called(lib: Any) -> str:  # should not be called
        raise AssertionError("callable_fn should not be invoked when lib is None")

    # Act
    result = await client._api_call(
        label="test-lib-missing",
        reauth_reason="need-reauth",
        default="DEF",
        use_lock=True,
        callable_fn=fn_never_called,
    )

    # Assert
    assert result == "DEF"
    reset_mock.assert_awaited()
    reauth_mock.assert_awaited()
    assert save_mock.await_count == 0  # not called when lib is missing


@pytest.mark.asyncio
async def test_api_call_auth_error_triggers_reauth(monkeypatch: pytest.MonkeyPatch):
    """Test API call when authentication error occurs."""

    # Arrange: monkeypatch Ex in module to avoid importing external package
    class DummyEx:
        class InvalidToken(Exception):
            pass

        class InvalidRefreshToken(Exception):
            pass

        class RefreshTokenExpired(Exception):
            pass

        class RefreshTokenRedeemd(Exception):
            pass

    monkeypatch.setattr(api_mod, "Ex", DummyEx, raising=True)

    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]
    monkeypatch.setattr(client, "_is_lib", AsyncMock(return_value=SimpleNamespace()))
    reset_mock = AsyncMock()
    reauth_mock = AsyncMock()
    save_mock = AsyncMock()
    monkeypatch.setattr(client, "_reset_tokens_and_client", reset_mock)
    monkeypatch.setattr(client, "_start_reauth", reauth_mock)
    monkeypatch.setattr(client, "_save_tokens_if_changed", save_mock)

    async def fn_auth_fail(lib: Any) -> str:
        raise DummyEx.InvalidToken("bad token")

    # Act
    result = await client._api_call(
        label="test-auth-error",
        reauth_reason="invalid-credentials",
        default="DEF",
        use_lock=True,
        callable_fn=fn_auth_fail,
    )

    # Assert
    assert result == "DEF"
    reset_mock.assert_awaited()
    reauth_mock.assert_awaited()
    save_mock.assert_awaited()


@pytest.mark.asyncio
async def test_async_get_messages_filters_from_start_of_school_year_edge_before_start(
    monkeypatch: pytest.MonkeyPatch,
):
    """Messages should be fetched from start of the current school year (edge: ref day before 1.9.)."""

    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]

    # Fix "today" to before Sep 1 => school year start should be previous year 9/1.
    fixed_today = dt_date(2024, 8, 31)

    class _FixedDatetime:
        @classmethod
        def today(cls):
            return dt_datetime.combine(fixed_today, dt_datetime.min.time())

    monkeypatch.setattr(api_mod, "datetime", _FixedDatetime, raising=True)

    fake_komens = _FakeKomens(lib=None)

    def _komens_factory(lib: Any):
        return fake_komens

    monkeypatch.setattr(api_mod, "Komens", _komens_factory, raising=True)

    # Act (go through @api_call wrapper, but stub _api_call to execute callable_fn directly)
    res = await _direct_call_via_api_call_wrapper(
        client,
        "async_get_messages",
        lib=SimpleNamespace(),
    )

    # Assert
    assert res == ["m1"]
    assert fake_komens.messages.calls == [(dt_date(2023, 9, 1), fixed_today)]


@pytest.mark.asyncio
async def test_async_get_messages_filters_from_start_of_school_year_edge_on_start_day(
    monkeypatch: pytest.MonkeyPatch,
):
    """Messages should be fetched from 1.9. when today is exactly 1.9."""

    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]

    fixed_today = dt_date(2024, 9, 1)

    class _FixedDatetime:
        @classmethod
        def today(cls):
            return dt_datetime.combine(fixed_today, dt_datetime.min.time())

    monkeypatch.setattr(api_mod, "datetime", _FixedDatetime, raising=True)

    fake_komens = _FakeKomens(lib=None)

    def _komens_factory(lib: Any):
        return fake_komens

    monkeypatch.setattr(api_mod, "Komens", _komens_factory, raising=True)

    # Act (go through @api_call wrapper, but stub _api_call to execute callable_fn directly)
    res = await _direct_call_via_api_call_wrapper(
        client,
        "async_get_messages",
        lib=SimpleNamespace(),
    )

    # Assert
    assert res == ["m1"]
    assert fake_komens.messages.calls == [(dt_date(2024, 9, 1), fixed_today)]


@pytest.mark.asyncio
async def test_async_fetch_noticeboard_filters_when_messages_present_edge_before_start(
    monkeypatch: pytest.MonkeyPatch,
):
    """Noticeboard should be date-filtered from school-year start when it has messages (edge: before 1.9.)."""

    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]
    fixed_today = dt_date(2024, 8, 31)

    class _FixedDatetime:
        @classmethod
        def today(cls):
            return dt_datetime.combine(fixed_today, dt_datetime.min.time())

    monkeypatch.setattr(api_mod, "datetime", _FixedDatetime, raising=True)

    # container returned by fetch_noticeboard()
    calls: list[tuple[dt_date, dt_date]] = []

    class _NoticeboardContainer:
        def count_messages(self) -> int:
            return 1

        def get_messages_by_date(self, start: dt_date, end: dt_date):
            calls.append((start, end))
            return ["n1"]

    fake_komens = _FakeKomens(lib=None, noticeboard_container=_NoticeboardContainer())

    def _komens_factory(lib: Any):
        return fake_komens

    monkeypatch.setattr(api_mod, "Komens", _komens_factory, raising=True)

    # Act (go through @api_call wrapper, but stub _api_call to execute callable_fn directly)
    res = await _direct_call_via_api_call_wrapper(
        client,
        "async_fetch_noticeboard",
        lib=SimpleNamespace(),
    )

    # Assert
    assert res == ["n1"]
    assert calls == [(dt_date(2023, 9, 1), fixed_today)]


@pytest.mark.asyncio
async def test_async_get_messages_filters_from_start_of_school_year_edge_jan_1(
    monkeypatch: pytest.MonkeyPatch,
):
    """Jan 1 must fall into school year that started previous Sep 1 (1.1.2026 -> 1.9.2025)."""

    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]

    fixed_today = dt_date(2026, 1, 1)

    class _FixedDatetime:
        @classmethod
        def today(cls):
            return dt_datetime.combine(fixed_today, dt_datetime.min.time())

    monkeypatch.setattr(api_mod, "datetime", _FixedDatetime, raising=True)

    fake_komens = _FakeKomens(lib=None)

    def _komens_factory(lib: Any):
        return fake_komens

    monkeypatch.setattr(api_mod, "Komens", _komens_factory, raising=True)

    # Act (go through @api_call wrapper, but stub _api_call to execute callable_fn directly)
    res = await _direct_call_via_api_call_wrapper(
        client,
        "async_get_messages",
        lib=SimpleNamespace(),
    )

    # Assert
    assert res == ["m1"]
    assert fake_komens.messages.calls == [(dt_date(2025, 9, 1), fixed_today)]


@pytest.mark.asyncio
async def test_async_fetch_noticeboard_returns_empty_when_no_messages(
    monkeypatch: pytest.MonkeyPatch,
):
    """Noticeboard should return [] when count_messages() is 0 (no filtering call)."""

    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]
    fixed_today = dt_date(2024, 10, 10)

    class _FixedDatetime:
        @classmethod
        def today(cls):
            return dt_datetime.combine(fixed_today, dt_datetime.min.time())

    monkeypatch.setattr(api_mod, "datetime", _FixedDatetime, raising=True)

    calls: list[tuple[dt_date, dt_date]] = []

    class _NoticeboardContainer:
        def count_messages(self) -> int:
            return 0

        def get_messages_by_date(self, start: dt_date, end: dt_date):
            calls.append((start, end))
            return ["should-not-be-returned"]

    fake_komens = _FakeKomens(lib=None, noticeboard_container=_NoticeboardContainer())

    def _komens_factory(lib: Any):
        return fake_komens

    monkeypatch.setattr(api_mod, "Komens", _komens_factory, raising=True)

    # Act (go through @api_call wrapper, but stub _api_call to execute callable_fn directly)
    res = await _direct_call_via_api_call_wrapper(
        client,
        "async_fetch_noticeboard",
        lib=SimpleNamespace(),
    )

    # Assert
    assert res == []
    assert calls == []


@pytest.mark.asyncio
async def test_api_call_generic_error_returns_default(monkeypatch: pytest.MonkeyPatch):
    """Test API call when generic error occurs."""
    # Arrange
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]
    monkeypatch.setattr(client, "_is_lib", AsyncMock(return_value=SimpleNamespace()))
    save_mock = AsyncMock()
    monkeypatch.setattr(client, "_save_tokens_if_changed", save_mock)

    async def fn_boom(lib: Any) -> str:
        raise RuntimeError("boom")

    # Act
    result = await client._api_call(
        label="test-generic-error",
        reauth_reason="",
        default="DEF",
        use_lock=True,
        callable_fn=fn_boom,
    )

    # Assert
    assert result == "DEF"
    save_mock.assert_awaited()


@pytest.mark.asyncio
async def test_api_call_lock_serialization(monkeypatch: pytest.MonkeyPatch):
    """Test API call when lock serialization occurs."""
    # Arrange: ensure concurrent calls are serialized by the internal fetch lock
    client = BakalariClient(hass=object(), entry=object(), child_id="c1")  # pyright: ignore[]
    monkeypatch.setattr(client, "_is_lib", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(client, "_save_tokens_if_changed", AsyncMock(return_value=None))

    active = 0
    max_active = 0

    async def worker(lib: Any, delay: float) -> str:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        # simulate IO
        await asyncio.sleep(delay)
        active -= 1
        return "done"

    # Launch two calls "concurrently"
    t1 = asyncio.create_task(
        client._api_call(
            label="lock-1",
            reauth_reason="",
            default="",
            use_lock=True,
            callable_fn=lambda lib: worker(lib, 0.05),
        )
    )
    t2 = asyncio.create_task(
        client._api_call(
            label="lock-2",
            reauth_reason="",
            default="",
            use_lock=True,
            callable_fn=lambda lib: worker(lib, 0.05),
        )
    )

    res1, res2 = await asyncio.gather(t1, t2)
    assert res1 == "done" and res2 == "done"
    # The critical assertion: the lock ensured no overlap
    assert max_active == 1
