import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.twitch_data_manager import TwitchDataManager
from utils.models import TwitchStreamer


@pytest.fixture
def twitch_manager():
    """Фикстура для создания экземпляра TwitchDataManager."""
    return TwitchDataManager()


class TestTwitchDataManager:
    """Тесты для класса TwitchDataManager."""

    @pytest.mark.asyncio
    async def test_initialize_table_success(self, twitch_manager):
        """Тест успешной инициализации таблицы."""
        result = await twitch_manager.initialize_table()
        assert result is True

    @pytest.mark.asyncio
    async def test_add_streamer_new(self, twitch_manager):
        """Тест добавления нового стримера."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.update_or_create", new_callable=AsyncMock
        ) as mock_update_or_create:
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="testuser", twitch_id="123456"
            )

            assert result is True
            mock_update_or_create.assert_called_once_with(
                guild_id=1,
                twitch_username="testuser",
                defaults={
                    "channel_id": 2,
                    "twitch_id": "123456",
                },
            )

    @pytest.mark.asyncio
    async def test_add_streamer_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.update_or_create", new_callable=AsyncMock
        ) as mock_update_or_create:
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="TestUser", twitch_id="123456"
            )

            assert result is True
            mock_update_or_create.assert_called_once()
            assert mock_update_or_create.call_args[1]["twitch_username"] == "testuser"

    @pytest.mark.asyncio
    async def test_add_streamer_exception(self, twitch_manager):
        """Тест обработки исключения при добавлении стримера."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.update_or_create",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.add_streamer(
                guild_id=1, channel_id=2, twitch_username="testuser", twitch_id="123456"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_remove_streamer_success(self, twitch_manager):
        """Тест успешного удаления стримера."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=1)
            mock_filter.return_value.delete = mock_delete

            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")

            assert result is True
            mock_filter.assert_called_once_with(guild_id=1, twitch_username="testuser")
            mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_streamer_not_found(self, twitch_manager):
        """Тест удаления несуществующего стримера."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=0)
            mock_filter.return_value.delete = mock_delete

            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")

            assert result is False

    @pytest.mark.asyncio
    async def test_remove_streamer_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру при удалении."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_delete = AsyncMock(return_value=1)
            mock_filter.return_value.delete = mock_delete

            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="TestUser")

            assert result is True
            mock_filter.assert_called_once_with(guild_id=1, twitch_username="testuser")

    @pytest.mark.asyncio
    async def test_remove_streamer_exception(self, twitch_manager):
        """Тест обработки исключения при удалении стримера."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.filter",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.remove_streamer(guild_id=1, twitch_username="testuser")

            assert result is False

    @pytest.mark.asyncio
    async def test_get_streamers_success(self, twitch_manager):
        """Тест успешного получения списка стримеров для сервера."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_streamer1 = MagicMock(
                guild_id=1,
                channel_id=2,
                twitch_username="user1",
                twitch_id="123",
                is_live=False,
                last_stream_id=None,
                last_notification_time=0,
            )
            mock_streamer2 = MagicMock(
                guild_id=1,
                channel_id=3,
                twitch_username="user2",
                twitch_id="456",
                is_live=True,
                last_stream_id="s1",
                last_notification_time=100,
            )

            # Имитируем awaitable результат filter()
            mock_filter_result = AsyncMock()
            mock_filter_result.__iter__ = MagicMock(
                return_value=iter([mock_streamer1, mock_streamer2])
            )
            # Для await filter()
            mock_filter.return_value = [mock_streamer1, mock_streamer2]
            # Но в коде: streamer_objs = await TwitchStreamer.filter(guild_id=guild_id)
            # filter() возвращает QuerySet, который awaitable и возвращает список

            # Правильный мок для Tortoise QuerySet:
            # await TwitchStreamer.filter(...) -> list
            mock_filter.return_value = [mock_streamer1, mock_streamer2]
            # Но filter() возвращает объект, который нужно await.
            # AsyncMock возвращает awaitable.
            # Поэтому mock_filter должен быть обычным Mock, который возвращает AsyncMock (или объект с __await__)

            # В тесте выше мы использовали patch("...filter") as mock_filter
            # Если mock_filter это MagicMock, то mock_filter(...) возвращает MagicMock.
            # Если мы хотим чтобы await mock_filter(...) работал, возвращаемое значение должно быть awaitable.

            # Исправляем мок:
            future = asyncio.Future()
            future.set_result([mock_streamer1, mock_streamer2])
            mock_filter.return_value = future

            result = await twitch_manager.get_streamers(guild_id=1)

            assert len(result) == 2
            assert result[0]["twitch_username"] == "user1"
            assert result[1]["twitch_username"] == "user2"
            mock_filter.assert_called_once_with(guild_id=1)

    @pytest.mark.asyncio
    async def test_get_streamers_empty(self, twitch_manager):
        """Тест получения пустого списка стримеров."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            future = asyncio.Future()
            future.set_result([])
            mock_filter.return_value = future

            result = await twitch_manager.get_streamers(guild_id=1)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_streamers_exception(self, twitch_manager):
        """Тест обработки исключения при получении списка стримеров."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.filter",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.get_streamers(guild_id=1)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_all_streamers_success(self, twitch_manager):
        """Тест успешного получения списка всех стримеров."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.all", new_callable=AsyncMock
        ) as mock_all:
            mock_streamer1 = MagicMock(
                guild_id=1,
                channel_id=2,
                twitch_username="user1",
                twitch_id="123",
                is_live=False,
                last_stream_id=None,
                last_notification_time=0,
            )
            mock_streamer2 = MagicMock(
                guild_id=2,
                channel_id=3,
                twitch_username="user2",
                twitch_id="456",
                is_live=True,
                last_stream_id="s1",
                last_notification_time=100,
            )
            mock_all.return_value = [mock_streamer1, mock_streamer2]

            result = await twitch_manager.get_all_streamers()

            assert len(result) == 2
            assert result[0]["twitch_username"] == "user1"
            assert result[1]["twitch_username"] == "user2"

    @pytest.mark.asyncio
    async def test_get_all_streamers_empty(self, twitch_manager):
        """Тест получения пустого списка всех стримеров."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.all", new_callable=AsyncMock
        ) as mock_all:
            mock_all.return_value = []

            result = await twitch_manager.get_all_streamers()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_all_streamers_exception(self, twitch_manager):
        """Тест обработки исключения при получении списка всех стримеров."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.all", side_effect=Exception("Test DB Error")
        ):
            result = await twitch_manager.get_all_streamers()

            assert result == []

    @pytest.mark.asyncio
    async def test_update_streamer_status_online(self, twitch_manager):
        """Тест обновления статуса стримера на онлайн."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_streamer_status(
                twitch_username="testuser", is_live=True, stream_id="stream123"
            )

            assert result is True
            mock_filter.assert_called_once_with(twitch_username="testuser")
            mock_update.assert_called_once_with(is_live=True, last_stream_id="stream123")

    @pytest.mark.asyncio
    async def test_update_streamer_status_offline(self, twitch_manager):
        """Тест обновления статуса стримера на оффлайн."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_streamer_status(
                twitch_username="testuser", is_live=False
            )

            assert result is True
            mock_filter.assert_called_once_with(twitch_username="testuser")
            mock_update.assert_called_once_with(is_live=False)

    @pytest.mark.asyncio
    async def test_update_streamer_status_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру при обновлении статуса."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_streamer_status(
                twitch_username="TestUser", is_live=True
            )

            mock_filter.assert_called_once_with(twitch_username="testuser")
            assert result is True

    @pytest.mark.asyncio
    async def test_update_streamer_status_exception(self, twitch_manager):
        """Тест обработки исключения при обновлении статуса стримера."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.filter",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.update_streamer_status(
                twitch_username="testuser", is_live=True
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_update_notification_time_with_stream_id(self, twitch_manager):
        """Тест обновления времени уведомления с ID стрима."""
        with (
            patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter,
            patch("time.time", return_value=1234567890),
        ):
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_notification_time(
                twitch_username="testuser", guild_id=1, stream_id="stream123"
            )

            assert result is True
            mock_filter.assert_called_once_with(twitch_username="testuser", guild_id=1)
            mock_update.assert_called_once_with(
                last_notification_time=1234567890, last_stream_id="stream123"
            )

    @pytest.mark.asyncio
    async def test_update_notification_time_without_stream_id(self, twitch_manager):
        """Тест обновления времени уведомления без ID стрима."""
        with (
            patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter,
            patch("time.time", return_value=1234567890),
        ):
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_notification_time(
                twitch_username="testuser", guild_id=1
            )

            assert result is True
            mock_filter.assert_called_once_with(twitch_username="testuser", guild_id=1)
            mock_update.assert_called_once_with(last_notification_time=1234567890)

    @pytest.mark.asyncio
    async def test_update_notification_time_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру при обновлении времени уведомления."""
        with (
            patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter,
            patch("time.time", return_value=1234567890),
        ):
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_notification_time(
                twitch_username="TestUser", guild_id=1
            )

            mock_filter.assert_called_once_with(twitch_username="testuser", guild_id=1)
            assert result is True

    @pytest.mark.asyncio
    async def test_update_notification_time_exception(self, twitch_manager):
        """Тест обработки исключения при обновлении времени уведомления."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.filter",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.update_notification_time(
                twitch_username="testuser", guild_id=1
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_update_twitch_id_success(self, twitch_manager):
        """Тест успешного обновления Twitch ID."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_twitch_id(
                twitch_username="testuser", twitch_id="123456789"
            )

            assert result is True
            mock_filter.assert_called_once_with(twitch_username="testuser")
            mock_update.assert_called_once_with(twitch_id="123456789")

    @pytest.mark.asyncio
    async def test_update_twitch_id_lowercase(self, twitch_manager):
        """Тест приведения имени пользователя к нижнему регистру при обновлении Twitch ID."""
        with patch("utils.twitch_data_manager.TwitchStreamer.filter") as mock_filter:
            mock_update = AsyncMock()
            mock_filter.return_value.update = mock_update

            result = await twitch_manager.update_twitch_id(
                twitch_username="TestUser", twitch_id="123456789"
            )

            mock_filter.assert_called_once_with(twitch_username="testuser")
            assert result is True

    @pytest.mark.asyncio
    async def test_update_twitch_id_exception(self, twitch_manager):
        """Тест обработки исключения при обновлении Twitch ID."""
        with patch(
            "utils.twitch_data_manager.TwitchStreamer.filter",
            side_effect=Exception("Test DB Error"),
        ):
            result = await twitch_manager.update_twitch_id(
                twitch_username="testuser", twitch_id="123456789"
            )

            assert result is False
