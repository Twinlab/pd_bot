"""Тесты для модуля dota_api."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import utils.dota_api as dota_api_module
from utils.dota_api import (
    StratzNonRetryable,
    StratzRateLimited,
    _parse_retry_after,
    close_session,
    fetch_items_data,
    get_cached_response,
    query_api,
    query_api_with_retry,
    save_to_cache,
)


class TestDotaAPI:
    """Тесты для функций взаимодействия с API Dota 2."""

    @pytest.fixture(autouse=True)
    def reset_session(self):
        """Сбрасывает модульную сессию между тестами."""
        dota_api_module._session = None
        yield
        dota_api_module._session = None

    @pytest.mark.asyncio
    async def test_get_cached_response_found(self):
        """Тест получения данных из кэша (найдено)."""
        mock_entry = MagicMock()
        mock_entry.data = {"test": "data"}
        mock_entry.timestamp = 1000000000
        mock_entry.ttl = 300

        with patch("utils.models.APICache.get_or_none", new_callable=AsyncMock) as mock_get, patch(
            "time.time", return_value=1000000000
        ):
            mock_get.return_value = mock_entry
            result = await get_cached_response("test_key")
            assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_get_cached_response_expired(self):
        """Тест получения данных из кэша (истек срок действия)."""
        mock_entry = MagicMock()
        mock_entry.timestamp = 1000
        mock_entry.ttl = 300
        mock_entry.delete = AsyncMock()

        with patch("utils.models.APICache.get_or_none", new_callable=AsyncMock) as mock_get, patch(
            "time.time", return_value=2000
        ):
            mock_get.return_value = mock_entry
            result = await get_cached_response("test_key")
            assert result is None
            mock_entry.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_to_cache(self):
        """Тест сохранения данных в кэш."""
        with patch(
            "utils.models.APICache.update_or_create", new_callable=AsyncMock
        ) as mock_update:
            await save_to_cache("test_key", {"data": 1})
            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_api_success(self):
        """Тест успешного запроса к API."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"data": {"hero": "Pudge"}}

        mock_session = MagicMock()
        mock_session.closed = False

        # post возвращает контекстный менеджер
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None

        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session):
            result = await query_api("query", "url", {})
            assert result == {"hero": "Pudge"}

    @pytest.mark.asyncio
    async def test_query_api_reuses_session(self):
        """Тест переиспользования сессии между запросами."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"data": {"hero": "Pudge"}}

        mock_session = MagicMock()
        mock_session.closed = False

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None

        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session) as mock_cls:
            await query_api("query1", "url", {})
            await query_api("query2", "url", {})
            # Сессия создаётся только один раз
            mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Тест закрытия модульной сессии."""
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        dota_api_module._session = mock_session

        await close_session()

        mock_session.close.assert_called_once()
        assert dota_api_module._session is None

    @pytest.mark.asyncio
    async def test_close_session_already_closed(self):
        """Тест закрытия уже закрытой сессии."""
        mock_session = MagicMock()
        mock_session.closed = True
        dota_api_module._session = mock_session

        await close_session()

        assert dota_api_module._session is None

    @pytest.mark.asyncio
    async def test_query_api_with_retry_success(self):
        """Тест успешного запроса с повторными попытками."""
        with patch("utils.dota_api.query_api", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = [None, {"data": "success"}]
            result = await query_api_with_retry("query", "url", {})
            assert result == {"data": "success"}
            assert mock_query.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_items_data_cached(self):
        """Тест получения предметов из кэша."""
        cached_data = {"1": {"name": "blink"}}
        with patch(
            "utils.dota_api.get_cached_response", new_callable=AsyncMock
        ) as mock_get_cache:
            mock_get_cache.return_value = cached_data
            result = await fetch_items_data("url", {})
            assert result == {1: {"name": "blink"}}

    @pytest.mark.asyncio
    async def test_query_api_raises_rate_limited(self):
        """Тест: 429 пробрасывается как StratzRateLimited с Retry-After."""
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.headers = {"Retry-After": "7"}
        mock_response.text.return_value = "Too Many Requests"

        mock_session = MagicMock()
        mock_session.closed = False
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(StratzRateLimited) as exc_info:
                await query_api("query", "url", {})
            assert exc_info.value.retry_after == 7.0

    @pytest.mark.asyncio
    async def test_query_api_raises_non_retryable_on_4xx(self):
        """Тест: 4xx (например, 401) сразу даёт StratzNonRetryable."""
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.headers = {}
        mock_response.text.return_value = "Unauthorized"

        mock_session = MagicMock()
        mock_session.closed = False
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(StratzNonRetryable):
                await query_api("query", "url", {})

    @pytest.mark.asyncio
    async def test_query_api_raises_non_retryable_on_graphql_errors(self):
        """Тест: GraphQL errors → StratzNonRetryable, не транзиентная ошибка."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"errors": [{"message": "bad query"}]}

        mock_session = MagicMock()
        mock_session.closed = False
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(StratzNonRetryable):
                await query_api("query", "url", {})

    @pytest.mark.asyncio
    async def test_query_api_returns_none_on_5xx(self):
        """Тест: 5xx — transient, возвращаем None для retry-обёртки."""
        mock_response = AsyncMock()
        mock_response.status = 503
        mock_response.headers = {}
        mock_response.text.return_value = "Service Unavailable"

        mock_session = MagicMock()
        mock_session.closed = False
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        mock_session.post.return_value = mock_post_cm

        with patch("utils.dota_api.aiohttp.ClientSession", return_value=mock_session):
            result = await query_api("query", "url", {})
            assert result is None

    @pytest.mark.asyncio
    async def test_query_api_with_retry_handles_rate_limit(self):
        """Тест: при 429 ретрай-обёртка ждёт Retry-After и повторяет запрос."""
        with (
            patch("utils.dota_api.query_api", new_callable=AsyncMock) as mock_query,
            patch("utils.dota_api.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_query.side_effect = [
                StratzRateLimited(2.0),
                {"hero": "Pudge"},
            ]
            result = await query_api_with_retry("q", "url", {})
            assert result == {"hero": "Pudge"}
            assert mock_query.call_count == 2
            mock_sleep.assert_any_await(2.0)

    @pytest.mark.asyncio
    async def test_query_api_with_retry_short_circuits_non_retryable(self):
        """Тест: на StratzNonRetryable сразу None, без повторных попыток."""
        with patch("utils.dota_api.query_api", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = StratzNonRetryable("bad")
            result = await query_api_with_retry("q", "url", {}, max_retries=5)
            assert result is None
            assert mock_query.call_count == 1


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
