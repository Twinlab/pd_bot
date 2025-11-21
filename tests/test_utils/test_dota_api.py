"""Тесты для модуля dota_api."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.dota_api import (
    fetch_items_data,
    get_cached_response,
    query_api,
    query_api_with_retry,
    save_to_cache,
)


class TestDotaAPI:
    """Тесты для функций взаимодействия с API Dota 2."""

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

        mock_session = MagicMock() # MagicMock, так как __aenter__ должен быть awaitable
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        
        # post возвращает контекстный менеджер, а не корутину
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__.return_value = mock_response
        mock_post_cm.__aexit__.return_value = None
        
        mock_session.post.return_value = mock_post_cm

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await query_api("query", "url", {})
            assert result == {"hero": "Pudge"}

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
