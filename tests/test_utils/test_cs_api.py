"""Тесты для модуля cs_api (FACEIT Data API клиент)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import utils.cs_api as cs_api_module
from utils.cs_api import (
    FaceitNonRetryable,
    FaceitNotFound,
    FaceitRateLimited,
    _parse_retry_after,
    close_session,
    faceit_get,
    faceit_get_with_retry,
)


def _make_session(response: MagicMock) -> MagicMock:
    """Собирает мок aiohttp-сессии, чей get() возвращает контекстный менеджер."""
    session = MagicMock()
    session.closed = False
    get_cm = MagicMock()
    get_cm.__aenter__.return_value = response
    get_cm.__aexit__.return_value = None
    session.get.return_value = get_cm
    return session


class TestFaceitGet:
    """Тесты функции faceit_get."""

    @pytest.fixture(autouse=True)
    def reset_session(self):
        """Сбрасывает модульную сессию и Lock между тестами."""
        cs_api_module._session = None
        cs_api_module._session_lock = None
        yield
        cs_api_module._session = None
        cs_api_module._session_lock = None

    @pytest.mark.asyncio
    async def test_success(self):
        """200 → возвращает распарсенный JSON."""
        response = AsyncMock()
        response.status = 200
        response.json.return_value = {"player_id": "abc"}
        session = _make_session(response)

        with patch("utils.cs_api.aiohttp.ClientSession", return_value=session):
            result = await faceit_get("/players", "key")
            assert result == {"player_id": "abc"}

    @pytest.mark.asyncio
    async def test_rate_limited_raises(self):
        """429 → FaceitRateLimited с Retry-After."""
        response = AsyncMock()
        response.status = 429
        response.headers = {"Retry-After": "7"}
        session = _make_session(response)

        with patch("utils.cs_api.aiohttp.ClientSession", return_value=session):
            with pytest.raises(FaceitRateLimited) as exc_info:
                await faceit_get("/players", "key")
            assert exc_info.value.retry_after == 7.0

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        """404 → FaceitNotFound."""
        response = AsyncMock()
        response.status = 404
        response.headers = {}
        session = _make_session(response)

        with patch("utils.cs_api.aiohttp.ClientSession", return_value=session):
            with pytest.raises(FaceitNotFound):
                await faceit_get("/players/missing", "key")

    @pytest.mark.asyncio
    async def test_client_error_raises_non_retryable(self):
        """401 → FaceitNonRetryable."""
        response = AsyncMock()
        response.status = 401
        response.headers = {}
        response.text.return_value = "Unauthorized"
        session = _make_session(response)

        with patch("utils.cs_api.aiohttp.ClientSession", return_value=session):
            with pytest.raises(FaceitNonRetryable):
                await faceit_get("/players", "key")

    @pytest.mark.asyncio
    async def test_server_error_returns_none(self):
        """5xx — transient, возвращаем None для retry-обёртки."""
        response = AsyncMock()
        response.status = 503
        response.headers = {}
        session = _make_session(response)

        with patch("utils.cs_api.aiohttp.ClientSession", return_value=session):
            result = await faceit_get("/players", "key")
            assert result is None

    @pytest.mark.asyncio
    async def test_close_session(self):
        """close_session закрывает и обнуляет модульную сессию."""
        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        cs_api_module._session = session

        await close_session()

        session.close.assert_called_once()
        assert cs_api_module._session is None


class TestFaceitGetWithRetry:
    """Тесты обёртки faceit_get_with_retry."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Первый успешный ответ возвращается как есть."""
        with patch("utils.cs_api.faceit_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"ok": True}
            result = await faceit_get_with_retry("/players", "key")
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        """None (transient) → повтор, затем успех."""
        with (
            patch("utils.cs_api.faceit_get", new_callable=AsyncMock) as mock_get,
            patch("utils.cs_api.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_get.side_effect = [None, {"ok": True}]
            result = await faceit_get_with_retry("/players", "key")
            assert result == {"ok": True}
            assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_rate_limit(self):
        """429 → ждём Retry-After и повторяем."""
        with (
            patch("utils.cs_api.faceit_get", new_callable=AsyncMock) as mock_get,
            patch("utils.cs_api.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_get.side_effect = [FaceitRateLimited(2.0), {"ok": True}]
            result = await faceit_get_with_retry("/players", "key")
            assert result == {"ok": True}
            mock_sleep.assert_any_await(2.0)

    @pytest.mark.asyncio
    async def test_short_circuits_not_found(self):
        """404 → сразу None, без повторов."""
        with patch("utils.cs_api.faceit_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = FaceitNotFound("missing")
            result = await faceit_get_with_retry("/players", "key", max_retries=5)
            assert result is None
            assert mock_get.call_count == 1


class TestParseRetryAfter:
    """Тесты для парсера Retry-After."""

    def test_default_when_missing(self):
        assert _parse_retry_after(None) == 5.0

    def test_default_when_invalid(self):
        assert _parse_retry_after("soon") == 5.0

    def test_parses_integer(self):
        assert _parse_retry_after("12") == 12.0

    def test_clamps_to_max(self):
        assert _parse_retry_after("9999") == 60.0

    def test_clamps_negative_to_zero(self):
        assert _parse_retry_after("-5") == 0.0
