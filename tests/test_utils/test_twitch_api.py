"""Тесты для модуля utils.twitch_api."""

import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from utils.twitch_api import TwitchAPI


class TestTwitchAPI:
    """Тесты для класса TwitchAPI."""

    @pytest.fixture
    def twitch_api(self) -> TwitchAPI:
        """Создает экземпляр TwitchAPI для тестов."""
        return TwitchAPI(client_id="test_client_id", client_secret="test_client_secret")

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Создает мок сессии aiohttp."""
        session = MagicMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.close = AsyncMock()
        return session

    @pytest.fixture
    def mock_response(self) -> MagicMock:
        """Создает мок ответа HTTP."""
        response = MagicMock()
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        return response

    def test_init(self, twitch_api: TwitchAPI) -> None:
        """Тестирует инициализацию TwitchAPI."""
        assert twitch_api.client_id == "test_client_id"
        assert twitch_api.client_secret == "test_client_secret"
        assert twitch_api.access_token is None
        assert twitch_api.token_expires_at == 0
        assert twitch_api.base_url == "https://api.twitch.tv/helix"
        assert twitch_api.auth_url == "https://id.twitch.tv/oauth2/token"
        assert twitch_api.session is None

    @pytest.mark.asyncio
    async def test_initialize(self, twitch_api: TwitchAPI, mock_session: MagicMock) -> None:
        """Тестирует инициализацию сессии и получение токена."""
        with patch("aiohttp.ClientSession", return_value=mock_session), patch.object(
            twitch_api, "get_access_token", new_callable=AsyncMock
        ) as mock_get_token:
            mock_get_token.return_value = True

            await twitch_api.initialize()

            assert twitch_api.session == mock_session
            mock_get_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_session(self, twitch_api: TwitchAPI, mock_session: MagicMock) -> None:
        """Тестирует закрытие сессии когда она существует."""
        twitch_api.session = mock_session

        await twitch_api.close()

        mock_session.close.assert_called_once()
        assert twitch_api.session is None

    @pytest.mark.asyncio
    async def test_close_without_session(self, twitch_api: TwitchAPI) -> None:
        """Тестирует закрытие когда сессия не существует."""
        twitch_api.session = None

        await twitch_api.close()

        # Не должно быть исключений
        assert twitch_api.session is None

    @pytest.mark.asyncio
    async def test_get_access_token_valid_token(self, twitch_api: TwitchAPI) -> None:
        """Тестирует возврат существующего валидного токена."""
        twitch_api.access_token = "valid_token"
        twitch_api.token_expires_at = time.time() + 3600  # Токен действителен еще час

        result = await twitch_api.get_access_token()

        assert result is True
        assert twitch_api.access_token == "valid_token"

    @pytest.mark.asyncio
    async def test_get_access_token_success(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует успешное получение нового токена."""
        # Настройка мока ответа
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"access_token": "new_token", "expires_in": 3600}
        )
        mock_session.post.return_value = mock_response

        with patch("aiohttp.ClientSession", return_value=mock_session), patch("time.time", return_value=1000):
            result = await twitch_api.get_access_token()

            assert result is True
            assert twitch_api.access_token == "new_token"
            assert twitch_api.token_expires_at == 1000 + 3600 - 600  # С запасом 10 минут
            mock_session.post.assert_called_once_with(
                twitch_api.auth_url,
                params={
                    "client_id": "test_client_id",
                    "client_secret": "test_client_secret",
                    "grant_type": "client_credentials",
                },
            )

    @pytest.mark.asyncio
    async def test_get_access_token_http_error(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует обработку HTTP ошибки при получении токена."""
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")
        mock_session.post.return_value = mock_response

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await twitch_api.get_access_token()

            assert result is False
            assert twitch_api.access_token is None

    @pytest.mark.asyncio
    async def test_get_access_token_exception(self, twitch_api: TwitchAPI, mock_session: MagicMock) -> None:
        """Тестирует обработку исключения при получении токена."""
        mock_session.post.side_effect = Exception("Network error")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await twitch_api.get_access_token()

            assert result is False
            assert twitch_api.access_token is None

    @pytest.mark.asyncio
    async def test_get_access_token_creates_session_if_none(self, twitch_api: TwitchAPI) -> None:
        """Тестирует создание сессии если она не существует."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"access_token": "token", "expires_in": 3600}
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_response

        twitch_api.session = None

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await twitch_api.get_access_token()

            assert result is True
            assert twitch_api.session == mock_session

    @pytest.mark.asyncio
    async def test_ensure_session_recreates_closed_session(self, twitch_api: TwitchAPI) -> None:
        """Тестирует пересоздание сессии если она закрыта."""
        old_session = MagicMock(spec=aiohttp.ClientSession)
        old_session.closed = True
        twitch_api.session = old_session

        new_session = MagicMock(spec=aiohttp.ClientSession)
        new_session.closed = False

        with patch("aiohttp.ClientSession", return_value=new_session):
            result = twitch_api._ensure_session()

            assert result == new_session
            assert twitch_api.session == new_session

    def test_ensure_session_reuses_open_session(self, twitch_api: TwitchAPI) -> None:
        """Тестирует переиспользование открытой сессии."""
        existing_session = MagicMock(spec=aiohttp.ClientSession)
        existing_session.closed = False
        twitch_api.session = existing_session

        result = twitch_api._ensure_session()

        assert result == existing_session

    @pytest.mark.asyncio
    async def test_make_request_no_token(self, twitch_api: TwitchAPI) -> None:
        """Тестирует запрос когда не удается получить токен."""
        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token:
            mock_get_token.return_value = False

            result = await twitch_api._make_request("test_endpoint")

            assert result is None
            mock_get_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_success(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует успешный запрос к API."""
        # Настройка токена
        twitch_api.access_token = "valid_token"

        # Настройка мока ответа
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": [{"id": "123", "login": "test_user"}]})
        mock_session.get.return_value = mock_response

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            mock_get_token.return_value = True

            result = await twitch_api._make_request("users", {"login": ["test_user"]})

            assert result == {"data": [{"id": "123", "login": "test_user"}]}
            mock_session.get.assert_called_once_with(
                "https://api.twitch.tv/helix/users",
                headers={"Client-ID": "test_client_id", "Authorization": "Bearer valid_token"},
                params={"login": ["test_user"]},
            )

    @pytest.mark.asyncio
    async def test_make_request_invalid_json_response(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует обработку невалидного JSON ответа."""
        twitch_api.access_token = "valid_token"
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value="not_a_dict")  # Невалидный ответ
        mock_session.get.return_value = mock_response

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            mock_get_token.return_value = True

            result = await twitch_api._make_request("users")

            assert result is None


    @pytest.mark.asyncio
    async def test_make_request_token_expired_retry_failed(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует неудачный повторный запрос после истечения токена."""
        twitch_api.access_token = "expired_token"
        mock_response.status = 401
        mock_session.get.return_value = mock_response

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            # Первый вызов возвращает True, второй - False (не удалось получить новый токен)
            mock_get_token.side_effect = [True, False]

            result = await twitch_api._make_request("users")

            assert result is None
            assert twitch_api.access_token is None

    @pytest.mark.asyncio
    async def test_make_request_http_error(
        self, twitch_api: TwitchAPI, mock_session: MagicMock, mock_response: MagicMock
    ) -> None:
        """Тестирует обработку HTTP ошибки в запросе."""
        twitch_api.access_token = "valid_token"
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_session.get.return_value = mock_response

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            mock_get_token.return_value = True

            result = await twitch_api._make_request("users")

            assert result is None

    @pytest.mark.asyncio
    async def test_make_request_exception(self, twitch_api: TwitchAPI, mock_session: MagicMock) -> None:
        """Тестирует обработку исключения в запросе."""
        twitch_api.access_token = "valid_token"
        mock_session.get.side_effect = Exception("Network error")

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            mock_get_token.return_value = True

            result = await twitch_api._make_request("users")

            assert result is None

    @pytest.mark.asyncio
    async def test_make_request_creates_session_if_none(self, twitch_api: TwitchAPI) -> None:
        """Тестирует создание сессии в _make_request если она не существует."""
        twitch_api.access_token = "valid_token"
        twitch_api.session = None

        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": []})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.get.return_value = mock_response

        with patch.object(twitch_api, "get_access_token", new_callable=AsyncMock) as mock_get_token, patch(
            "aiohttp.ClientSession", return_value=mock_session
        ):
            mock_get_token.return_value = True

            result = await twitch_api._make_request("users")

            assert result == {"data": []}
            assert twitch_api.session == mock_session

    @pytest.mark.asyncio
    async def test_get_users_empty_list(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_users с пустым списком пользователей."""
        result = await twitch_api.get_users([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_users_single_chunk(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_users с одним чанком пользователей."""
        usernames = ["user1", "user2", "user3"]
        expected_response = {
            "data": [
                {"id": "123", "login": "user1", "display_name": "User1"},
                {"id": "456", "login": "user2", "display_name": "User2"},
                {"id": "789", "login": "user3", "display_name": "User3"},
            ]
        }

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = expected_response

            result = await twitch_api.get_users(usernames)

            assert result == expected_response["data"]
            mock_request.assert_called_once_with("users", {"login": usernames})

    @pytest.mark.asyncio
    async def test_get_users_multiple_chunks(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_users с несколькими чанками пользователей."""
        # Создаем список из 150 пользователей (больше лимита в 100)
        usernames = [f"user{i}" for i in range(150)]
        
        # Ответы для двух чанков
        response1 = {"data": [{"id": f"{i}", "login": f"user{i}"} for i in range(100)]}
        response2 = {"data": [{"id": f"{i}", "login": f"user{i}"} for i in range(100, 150)]}

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [response1, response2]

            result = await twitch_api.get_users(usernames)

            assert len(result) == 150
            assert result == response1["data"] + response2["data"]
            assert mock_request.call_count == 2
            
            # Проверяем параметры вызовов
            calls = mock_request.call_args_list
            assert calls[0][0] == ("users", {"login": usernames[:100]})
            assert calls[1][0] == ("users", {"login": usernames[100:]})

    @pytest.mark.asyncio
    async def test_get_users_api_error(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_users при ошибке API."""
        usernames = ["user1", "user2"]

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = None  # Ошибка API

            result = await twitch_api.get_users(usernames)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_users_no_data_field(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_users когда в ответе нет поля data."""
        usernames = ["user1"]

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"error": "Something went wrong"}  # Нет поля data

            result = await twitch_api.get_users(usernames)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_streams_empty_list(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_streams с пустым списком ID пользователей."""
        result = await twitch_api.get_streams([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_streams_single_chunk(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_streams с одним чанком пользователей."""
        user_ids = ["123", "456", "789"]
        expected_response = {
            "data": [
                {"id": "stream1", "user_id": "123", "user_name": "user1", "game_name": "Game1"},
                {"id": "stream2", "user_id": "456", "user_name": "user2", "game_name": "Game2"},
            ]
        }

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = expected_response

            result = await twitch_api.get_streams(user_ids)

            assert result == expected_response["data"]
            mock_request.assert_called_once_with("streams", {"user_id": user_ids})

    @pytest.mark.asyncio
    async def test_get_streams_multiple_chunks(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_streams с несколькими чанками пользователей."""
        # Создаем список из 150 ID пользователей
        user_ids = [str(i) for i in range(150)]
        
        # Ответы для двух чанков
        response1 = {"data": [{"id": f"stream{i}", "user_id": str(i)} for i in range(50)]}
        response2 = {"data": [{"id": f"stream{i}", "user_id": str(i)} for i in range(100, 120)]}

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [response1, response2]

            result = await twitch_api.get_streams(user_ids)

            assert len(result) == 70  # 50 + 20
            assert result == response1["data"] + response2["data"]
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_streams_api_error(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_streams при ошибке API."""
        user_ids = ["123", "456"]

        with patch.object(twitch_api, "_make_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = None

            result = await twitch_api.get_streams(user_ids)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_user_by_username_found(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_user_by_username когда пользователь найден."""
        username = "test_user"
        expected_user = {"id": "123", "login": "test_user", "display_name": "Test User"}

        with patch.object(twitch_api, "get_users", new_callable=AsyncMock) as mock_get_users:
            mock_get_users.return_value = [expected_user]

            result = await twitch_api.get_user_by_username(username)

            assert result == expected_user
            mock_get_users.assert_called_once_with([username])

    @pytest.mark.asyncio
    async def test_get_user_by_username_not_found(self, twitch_api: TwitchAPI) -> None:
        """Тестирует get_user_by_username когда пользователь не найден."""
        username = "nonexistent_user"

        with patch.object(twitch_api, "get_users", new_callable=AsyncMock) as mock_get_users:
            mock_get_users.return_value = []

            result = await twitch_api.get_user_by_username(username)

            assert result is None
            mock_get_users.assert_called_once_with([username])

    @pytest.mark.asyncio
    async def test_is_user_live_online(self, twitch_api: TwitchAPI) -> None:
        """Тестирует is_user_live когда пользователь онлайн."""
        user_id = "123"
        stream_data = {"id": "stream123", "user_id": "123", "user_name": "test_user"}

        with patch.object(twitch_api, "get_streams", new_callable=AsyncMock) as mock_get_streams:
            mock_get_streams.return_value = [stream_data]

            is_live, stream_info = await twitch_api.is_user_live(user_id)

            assert is_live is True
            assert stream_info == stream_data
            mock_get_streams.assert_called_once_with([user_id])

    @pytest.mark.asyncio
    async def test_is_user_live_offline(self, twitch_api: TwitchAPI) -> None:
        """Тестирует is_user_live когда пользователь оффлайн."""
        user_id = "123"

        with patch.object(twitch_api, "get_streams", new_callable=AsyncMock) as mock_get_streams:
            mock_get_streams.return_value = []

            is_live, stream_info = await twitch_api.is_user_live(user_id)

            assert is_live is False
            assert stream_info is None
            mock_get_streams.assert_called_once_with([user_id])


# Дополнительные интеграционные тесты
class TestTwitchAPIIntegration:
    """Интеграционные тесты для TwitchAPI."""

    @pytest.mark.asyncio
    async def test_full_workflow_success(self) -> None:
        """Тестирует полный рабочий процесс: инициализация -> запрос -> закрытие."""
        api = TwitchAPI("test_id", "test_secret")

        # Мокаем все HTTP запросы
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        mock_session.close = AsyncMock()

        # Мок для получения токена
        token_response = MagicMock()
        token_response.status = 200
        token_response.json = AsyncMock(return_value={"access_token": "token", "expires_in": 3600})
        token_response.__aenter__ = AsyncMock(return_value=token_response)
        token_response.__aexit__ = AsyncMock(return_value=None)

        # Мок для запроса пользователей
        users_response = MagicMock()
        users_response.status = 200
        users_response.json = AsyncMock(return_value={"data": [{"id": "123", "login": "test"}]})
        users_response.__aenter__ = AsyncMock(return_value=users_response)
        users_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.post.return_value = token_response
        mock_session.get.return_value = users_response

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Инициализация
            await api.initialize()
            assert api.session == mock_session
            assert api.access_token == "token"

            # Запрос пользователей
            users = await api.get_users(["test"])
            assert users == [{"id": "123", "login": "test"}]

            # Закрытие
            await api.close()
            mock_session.close.assert_called_once()
            assert api.session is None

    @pytest.mark.asyncio
    async def test_token_refresh_during_request(self) -> None:
        """Тестирует обновление токена во время запроса."""
        api = TwitchAPI("test_id", "test_secret")
        
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        
        # Первый запрос возвращает 401 (токен истек)
        expired_response = MagicMock()
        expired_response.status = 401
        expired_response.__aenter__ = AsyncMock(return_value=expired_response)
        expired_response.__aexit__ = AsyncMock(return_value=None)
        
        # Запрос нового токена
        token_response = MagicMock()
        token_response.status = 200
        token_response.json = AsyncMock(return_value={"access_token": "new_token", "expires_in": 3600})
        token_response.__aenter__ = AsyncMock(return_value=token_response)
        token_response.__aexit__ = AsyncMock(return_value=None)
        
        # Повторный запрос с новым токеном
        success_response = MagicMock()
        success_response.status = 200
        success_response.json = AsyncMock(return_value={"data": [{"id": "123"}]})
        success_response.__aenter__ = AsyncMock(return_value=success_response)
        success_response.__aexit__ = AsyncMock(return_value=None)
        
        mock_session.get.side_effect = [expired_response, success_response]
        mock_session.post.return_value = token_response

        with patch("aiohttp.ClientSession", return_value=mock_session), patch("time.time", return_value=1000):
            api.session = mock_session
            api.access_token = "old_token"
            api.token_expires_at = 999  # Токен уже истек
            
            result = await api._make_request("users")
            
            assert result == {"data": [{"id": "123"}]}
            assert api.access_token == "new_token"
            assert mock_session.get.call_count == 2
            # Может быть вызван дважды: один раз при проверке токена, второй при обновлении
            assert mock_session.post.call_count >= 1
