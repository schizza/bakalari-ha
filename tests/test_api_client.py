"""Test API client."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import custom_components.bakalari.api as api_mod
from custom_components.bakalari.api import BakalariClient


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
