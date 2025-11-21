"""Тесты для кога AnimeCog."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.anime import AnimeCog


def create_mock_settings(channel_id=123456789):
    """Создает мок настроек для тестов."""
    mock_settings = MagicMock()
    mock_settings.channels.anime = channel_id
    mock_settings.anime.tags = ["anime", "1girl", "cute"]
    mock_settings.anime.excluded_tags = ["nude", "nsfw"]
    mock_settings.anime.max_tags_per_request = 6
    mock_settings.anime.rating = "safe"
    mock_settings.anime.safebooru_limit = 100
    mock_settings.anime.cache_size = 10
    mock_settings.anime.min_tag_selection = 1
    mock_settings.anime.schedule.morning_hour = 10
    mock_settings.anime.schedule.morning_minute = 0
    mock_settings.anime.schedule.evening_hour = 18
    mock_settings.anime.schedule.evening_minute = 0
    return mock_settings


class TestAnimeCogInit:
    """Тесты для инициализации и выгрузки AnimeCog."""

    def test_anime_cog_init_with_channel(self, mock_bot):
        """Тест инициализации кога с настроенным каналом."""
        mock_morning_task = MagicMock()
        mock_morning_task.change_interval = MagicMock()
        mock_morning_task.start = MagicMock()

        mock_evening_task = MagicMock()
        mock_evening_task.change_interval = MagicMock()
        mock_evening_task.start = MagicMock()

        with patch("cogs.anime.get_settings", return_value=create_mock_settings()), patch(
            "discord.ext.tasks.loop", return_value=MagicMock()
        ), patch("asyncio.create_task", return_value=MagicMock()), patch.object(
            AnimeCog, "morning_post", mock_morning_task
        ), patch.object(
            AnimeCog, "evening_post", mock_evening_task
        ):
            anime_cog = AnimeCog(mock_bot)

            assert anime_cog.bot == mock_bot
            assert anime_cog.channel_id == 123456789

            mock_morning_task.change_interval.assert_called_once()
            mock_evening_task.change_interval.assert_called_once()

            mock_morning_task.start.assert_called_once()
            mock_evening_task.start.assert_called_once()


class TestAnimeCacheDatabase:
    """Тесты для интеграции кеша аниме с базой данных."""

    @pytest.mark.asyncio
    async def test_load_cache_from_db_on_first_use(self, mock_bot):
        """Тест загрузки кеша из БД при первом использовании."""
        with patch("cogs.anime.get_settings", return_value=create_mock_settings()), patch(
            "discord.ext.tasks.loop", return_value=MagicMock()
        ), patch("asyncio.create_task", return_value=MagicMock()):
            anime_cog = AnimeCog(mock_bot)

            # Мокируем AnimeCache.all().order_by().limit()
            mock_query = MagicMock()
            mock_limit = MagicMock()
            # Возвращаем список объектов с атрибутом post_id
            item1 = MagicMock()
            item1.post_id = 111
            item1.added_at = 100
            item2 = MagicMock()
            item2.post_id = 222
            item2.added_at = 200
            
            # limit() возвращает awaitable, который возвращает список
            # В Tortoise ORM методы возвращают QuerySet, который можно await'ить
            
            # Создаем список возвращаемых элементов
            items = [item2, item1] # Новые (222) первые
            
            # Создаем мок для результата limit()
            # Он должен быть awaitable и возвращать items
            mock_limit_result = MagicMock()
            mock_limit_result.__await__ = MagicMock(return_value=iter(items))
            
            # Настраиваем цепочку
            mock_query = MagicMock()
            mock_query.limit.return_value = items # Так как в коде await ...limit(), то limit() должен вернуть awaitable.
            # Но MagicMock по умолчанию не awaitable, если не настроить __await__.
            # Проще сделать limit асинхронным методом
            
            async def async_limit(*args, **kwargs):
                return items
            
            mock_query.limit = AsyncMock(side_effect=async_limit)
            
            mock_order_by = MagicMock()
            mock_order_by.return_value = mock_query
            
            mock_all_query = MagicMock()
            mock_all_query.order_by = mock_order_by
            
            mock_all = MagicMock(return_value=mock_all_query)

            with patch("utils.models.AnimeCache.all", mock_all), patch.object(
                anime_cog,
                "_try_get_image_with_tags",
                AsyncMock(return_value=("https://example.com/test.jpg", 444)),
            ):
                result = await anime_cog.get_anime_image()

                assert anime_cog._cache_loaded is True
                # В коде мы сортируем по возрастанию времени, так что 111 (старый) должен быть первым
                assert list(anime_cog.post_cache) == [111, 222]
                assert result == ("https://example.com/test.jpg", 444)

    @pytest.mark.asyncio
    async def test_save_cache_item_on_post(self, mock_bot, mock_text_channel):
        """Тест сохранения элемента кеша в БД при публикации."""
        with patch("cogs.anime.get_settings", return_value=create_mock_settings()), patch(
            "discord.ext.tasks.loop", return_value=MagicMock()
        ), patch("asyncio.create_task", return_value=MagicMock()):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            anime_cog = AnimeCog(mock_bot)

            with patch("utils.models.AnimeCache.create", new_callable=AsyncMock) as mock_create, patch.object(
                anime_cog, "_check_channel_exists", AsyncMock(return_value=True)
            ), patch.object(
                anime_cog,
                "get_anime_image",
                AsyncMock(return_value=("https://example.com/test.jpg", 555)),
            ):
                result = await anime_cog.post_anime_image()

                assert result is True
                mock_text_channel.send.assert_called_once_with("https://example.com/test.jpg")
                mock_create.assert_called_once()
                assert mock_create.call_args.kwargs["post_id"] == 555
                assert 555 in anime_cog.post_cache
