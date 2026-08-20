"""Тесты для кога AnimeCog."""

from datetime import UTC, time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.anime import AnimeCog, AnimePost, _build_post_view


def _collect_text(view: discord.ui.LayoutView) -> str:
    """Склеивает текст всех TextDisplay внутри LayoutView (с обходом контейнеров)."""
    texts: list[str] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, discord.ui.TextDisplay):
                texts.append(item.content)
            children = getattr(item, "children", None)
            if children:
                walk(children)

    walk(view.children)
    return "\n".join(texts)


def _collect_media_urls(view: discord.ui.LayoutView) -> list[str]:
    """Собирает url всех картинок из MediaGallery внутри LayoutView."""
    urls: list[str] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, discord.ui.MediaGallery):
                urls.extend(media_item.media.url for media_item in item.items)
            children = getattr(item, "children", None)
            if children:
                walk(children)

    walk(view.children)
    return urls


def make_post(post_id=444, score=120):
    """Создаёт тестовый AnimePost."""
    return AnimePost(
        url="https://example.com/test.jpg",
        post_id=post_id,
        score=score,
        rating="s",
        source="https://example.com/source",
        artists="some artist",
        characters="some character",
    )


def create_mock_settings(channel_id=123456789):
    """Создает мок настроек для тестов."""
    mock_settings = MagicMock()
    mock_settings.channels.anime = channel_id
    mock_settings.danbooru_login = None
    mock_settings.danbooru_api_key = None
    mock_settings.anime.base_tags = ["1girl", "2girls"]
    mock_settings.anime.extra_tags = ["genshin_impact", "persona"]
    mock_settings.anime.extra_tag_chance = 0.6
    mock_settings.anime.ratings = ["g", "s"]
    mock_settings.anime.excluded_tags = ["guro", "comic"]
    mock_settings.anime.min_score = 50
    mock_settings.anime.limit = 100
    mock_settings.anime.cache_size = 10
    mock_settings.anime.schedule.morning_hour = 10
    mock_settings.anime.schedule.morning_minute = 0
    mock_settings.anime.schedule.evening_hour = 18
    mock_settings.anime.schedule.evening_minute = 0
    mock_settings.get_discord_color = MagicMock(return_value=discord.Color.blue())
    return mock_settings


class TestAnimeCogInit:
    """Тесты для инициализации и выгрузки AnimeCog."""

    def test_anime_cog_init_with_channel(self, mock_bot):
        """Тест инициализации кога с настроенным каналом."""
        mock_morning_task = MagicMock()
        mock_morning_task.change_interval = MagicMock()
        mock_morning_task.start = MagicMock()
        mock_morning_task.is_running = MagicMock(return_value=False)

        mock_evening_task = MagicMock()
        mock_evening_task.change_interval = MagicMock()
        mock_evening_task.start = MagicMock()
        mock_evening_task.is_running = MagicMock(return_value=False)

        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch("discord.ext.tasks.loop", return_value=MagicMock()),
            patch("asyncio.create_task", return_value=MagicMock()),
            patch.object(AnimeCog, "morning_post", mock_morning_task),
            patch.object(AnimeCog, "evening_post", mock_evening_task),
        ):
            anime_cog = AnimeCog(mock_bot)

            assert anime_cog.bot == mock_bot
            assert anime_cog.channel_id == 123456789

            mock_morning_task.change_interval.assert_called_once_with(time=time(10, tzinfo=UTC))
            mock_evening_task.change_interval.assert_called_once_with(time=time(18, tzinfo=UTC))

            mock_morning_task.start.assert_not_called()
            mock_evening_task.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_ready_starts_scheduled_posts_once(self, mock_bot):
        """Задачи запускаются после готовности бота и не дублируются при reconnect."""
        mock_morning_task = MagicMock()
        mock_morning_task.is_running.side_effect = [False, True]
        mock_evening_task = MagicMock()
        mock_evening_task.is_running.side_effect = [False, True]

        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch.object(AnimeCog, "morning_post", mock_morning_task),
            patch.object(AnimeCog, "evening_post", mock_evening_task),
        ):
            anime_cog = AnimeCog(mock_bot)
            await anime_cog.on_ready()
            await anime_cog.on_ready()

        mock_morning_task.start.assert_called_once_with()
        mock_evening_task.start.assert_called_once_with()


class TestAnimeCacheDatabase:
    """Тесты для интеграции кеша аниме с базой данных."""

    @pytest.mark.asyncio
    async def test_load_cache_from_db_on_first_use(self, mock_bot):
        """Тест загрузки кеша из БД при первом использовании."""
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch("discord.ext.tasks.loop", return_value=MagicMock()),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            anime_cog = AnimeCog(mock_bot)

            item1 = MagicMock()
            item1.post_id = 111
            item1.added_at = 100
            item2 = MagicMock()
            item2.post_id = 222
            item2.added_at = 200

            # БД отдаёт новые первыми (-added_at); ког пересортирует по возрастанию.
            items = [item2, item1]

            mock_query = MagicMock()
            mock_query.limit = AsyncMock(return_value=items)

            mock_all_query = MagicMock()
            mock_all_query.order_by = MagicMock(return_value=mock_query)

            mock_all = MagicMock(return_value=mock_all_query)

            fresh_post = make_post(post_id=444)
            with (
                patch("utils.models.AnimeCache.all", mock_all),
                patch.object(
                    anime_cog,
                    "_fetch_danbooru_posts",
                    AsyncMock(return_value=[fresh_post]),
                ),
            ):
                result = await anime_cog.get_anime_image()

                assert anime_cog._cache_loaded is True
                # В коде мы сортируем по возрастанию времени, так что 111 (старый) должен быть первым
                assert list(anime_cog.post_cache) == [111, 222]
                assert result == fresh_post

    @pytest.mark.asyncio
    async def test_save_cache_item_on_post(self, mock_bot, mock_text_channel):
        """Тест сохранения элемента кеша в БД при публикации."""
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch("discord.ext.tasks.loop", return_value=MagicMock()),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            anime_cog = AnimeCog(mock_bot)

            with (
                patch("utils.models.AnimeCache.create", new_callable=AsyncMock) as mock_create,
                patch.object(anime_cog, "_check_channel_exists", AsyncMock(return_value=True)),
                patch.object(
                    anime_cog,
                    "get_anime_image",
                    AsyncMock(return_value=make_post(post_id=555)),
                ),
            ):
                result = await anime_cog.post_anime_image()

                assert result is True
                mock_text_channel.send.assert_called_once()
                sent_view = mock_text_channel.send.call_args.kwargs["view"]
                assert _collect_media_urls(sent_view) == ["https://example.com/test.jpg"]
                assert "https://danbooru.donmai.us/posts/555" in _collect_text(sent_view)
                mock_create.assert_called_once()
                assert mock_create.call_args.kwargs["post_id"] == 555
                assert 555 in anime_cog.post_cache

    @pytest.mark.asyncio
    async def test_post_includes_danbooru_source_link(self, mock_bot, mock_text_channel):
        """Публикуется CV2-карточка с полной картинкой и ссылкой на пост Danbooru."""
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch("discord.ext.tasks.loop", return_value=MagicMock()),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            mock_bot.get_channel = MagicMock(return_value=mock_text_channel)
            anime_cog = AnimeCog(mock_bot)

            post = make_post(post_id=999)
            with (
                patch("utils.models.AnimeCache.create", new_callable=AsyncMock),
                patch.object(anime_cog, "_check_channel_exists", AsyncMock(return_value=True)),
                patch.object(anime_cog, "get_anime_image", AsyncMock(return_value=post)),
            ):
                result = await anime_cog.post_anime_image()

                assert result is True
                sent_view = mock_text_channel.send.call_args.kwargs["view"]
                source_url = "https://danbooru.donmai.us/posts/999"
                text = _collect_text(sent_view)
                assert _collect_media_urls(sent_view) == [post.url]
                assert source_url in text
                assert post.characters in text
                assert "Художник" in text


def _build_cog():
    """Создаёт экземпляр AnimeCog с замоканными фоновыми задачами."""
    mock_bot = MagicMock()
    with (
        patch("cogs.anime.get_settings", return_value=create_mock_settings()),
        patch("discord.ext.tasks.loop", return_value=MagicMock()),
        patch("asyncio.create_task", return_value=MagicMock()),
    ):
        return AnimeCog(mock_bot)


class TestParsePosts:
    """Тесты фильтрации постов Danbooru по качеству, рейтингу и тегам."""

    def _raw(self, **overrides):
        post = {
            "id": 1,
            "file_ext": "jpg",
            "file_url": "https://cdn.donmai.us/x.jpg",
            "rating": "s",
            "score": 100,
            "tag_string": "1girl smile",
            "tag_string_artist": "artist_name",
            "tag_string_character": "char_name",
            "source": "https://pixiv.net/x",
        }
        post.update(overrides)
        return post

    def test_keeps_valid_post(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts([self._raw()], settings, "s", require_girl=False)
        assert len(result) == 1
        assert result[0].post_id == 1
        assert result[0].artists == "artist name"
        assert result[0].characters == "char name"

    def test_drops_low_score(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts([self._raw(score=5)], settings, "s", require_girl=False)
        assert result == []

    def test_drops_excluded_tag(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts(
            [self._raw(tag_string="1girl guro")], settings, "s", require_girl=False
        )
        assert result == []

    def test_drops_non_image_ext(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts([self._raw(file_ext="mp4")], settings, "s", require_girl=False)
        assert result == []

    def test_drops_rating_mismatch(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts([self._raw(rating="e")], settings, "s", require_girl=False)
        assert result == []

    def test_drops_post_without_url(self):
        cog = _build_cog()
        settings = create_mock_settings()
        raw = self._raw()
        del raw["file_url"]
        result = cog._parse_posts([raw], settings, "s", require_girl=False)
        assert result == []

    def test_require_girl_drops_post_without_base_tag(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts(
            [self._raw(tag_string="scenery no_humans")], settings, "s", require_girl=True
        )
        assert result == []

    def test_require_girl_keeps_post_with_base_tag(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts(
            [self._raw(tag_string="1girl smile")], settings, "s", require_girl=True
        )
        assert len(result) == 1

    def test_apply_excluded_false_keeps_post_with_excluded_tag(self):
        cog = _build_cog()
        settings = create_mock_settings()
        result = cog._parse_posts(
            [self._raw(tag_string="1boy guro")],
            settings,
            "s",
            require_girl=False,
            apply_excluded=False,
        )
        assert len(result) == 1


class _FakeResp:
    status = 200

    async def json(self):
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self):
        self.captured = {}

    def get(self, url, params=None):
        self.captured["url"] = url
        self.captured["params"] = params
        return _FakeResp()


class TestFetchDanbooruParams:
    """Тесты построения запроса к Danbooru для двух стратегий."""

    @pytest.mark.asyncio
    async def test_franchise_query(self):
        cog = _build_cog()
        settings = create_mock_settings()
        session = _FakeSession()
        with patch.object(cog, "_get_session", return_value=session):
            await cog._fetch_danbooru_posts(
                settings, rating="s", tag="genshin_impact", use_extra=True
            )
        tags = session.captured["params"]["tags"]
        assert "genshin_impact" in tags
        assert "order:random" in tags
        assert "rating:s" in tags
        assert "score:>=50" in tags
        assert "page" not in session.captured["params"]

    @pytest.mark.asyncio
    async def test_base_query(self):
        cog = _build_cog()
        settings = create_mock_settings()
        session = _FakeSession()
        with patch.object(cog, "_get_session", return_value=session):
            await cog._fetch_danbooru_posts(settings, rating="g", tag=None, use_extra=False)
        tags = session.captured["params"]["tags"]
        assert "order:rank" in tags
        assert "rating:g" in tags
        assert ("1girl" in tags) or ("2girls" in tags)
        assert "score:" not in tags


class TestSearchByExplicitTag:
    """Тесты ручного поиска по явному тегу (/post_anime tag:...)."""

    def _raw(self, **overrides):
        post = {
            "id": 1,
            "file_ext": "jpg",
            "file_url": "https://cdn.donmai.us/x.jpg",
            "rating": "s",
            "score": 100,
            "tag_string": "1boy guro",
            "tag_string_artist": "artist_name",
            "tag_string_character": "char_name",
            "source": "https://pixiv.net/x",
        }
        post.update(overrides)
        return post

    @pytest.mark.asyncio
    async def test_explicit_tag_ignores_excluded_and_require_girl(self):
        """Явный тег: фильтры автопостинга не применяются, order:random в первом запросе."""
        cog = _build_cog()
        cog._cache_loaded = True
        req = AsyncMock(return_value=(200, [self._raw()]))
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch.object(cog, "_request_danbooru", req),
        ):
            result = await cog.get_anime_image(rating="s", tag="1boy")

        assert result is not None
        assert result.post_id == 1
        first_params = req.await_args_list[0].args[1]
        assert "1boy" in first_params["tags"]
        assert "order:random" in first_params["tags"]
        assert "score:>=50" in first_params["tags"]

    @pytest.mark.asyncio
    async def test_falls_back_to_order_rank_on_500(self):
        """При HTTP 500 на order:random делается повтор с order:rank."""
        cog = _build_cog()
        cog._cache_loaded = True
        req = AsyncMock(side_effect=[(500, []), (200, [self._raw()])])
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch.object(cog, "_request_danbooru", req),
        ):
            result = await cog.get_anime_image(rating="s", tag="1girl")

        assert result is not None
        assert req.await_count == 2
        assert "order:random" in req.await_args_list[0].args[1]["tags"]
        assert "order:rank" in req.await_args_list[1].args[1]["tags"]


class TestGetAnimeImageRatingOverride:
    """Тесты переопределения рейтинга при получении изображения."""

    @pytest.mark.asyncio
    async def test_explicit_rating_passed_to_fetch(self):
        cog = _build_cog()
        cog._cache_loaded = True
        fetch_mock = AsyncMock(return_value=[make_post(post_id=777)])
        with (
            patch("cogs.anime.get_settings", return_value=create_mock_settings()),
            patch.object(cog, "_fetch_danbooru_posts", fetch_mock),
        ):
            result = await cog.get_anime_image(rating="g")

            assert result.post_id == 777
            assert fetch_mock.await_args.kwargs["rating"] == "g"


class TestBuildPostView:
    """Тесты сборки CV2-карточки поста."""

    def test_full_card_has_image_source_and_meta(self):
        post = make_post(post_id=42, score=321)
        view = _build_post_view(post, discord.Color.blue())

        source_url = "https://danbooru.donmai.us/posts/42"
        text = _collect_text(view)
        assert _collect_media_urls(view) == [post.url]
        assert source_url in text
        assert post.characters in text
        assert post.artists in text
        assert "321" in text
        assert "sensitive" in text
        assert "#" not in text.replace("-# ", "").replace("### ", "")

    def test_no_characters_uses_fallback_title_but_keeps_source(self):
        post = AnimePost(
            url="https://example.com/x.jpg",
            post_id=7,
            score=55,
            rating="g",
            source="",
            artists="",
            characters="",
        )
        view = _build_post_view(post, discord.Color.blue())

        text = _collect_text(view)
        assert "Открыть на Danbooru" in text
        assert "https://danbooru.donmai.us/posts/7" in text
        assert _collect_media_urls(view) == [post.url]
        assert "Художник" not in text
        assert "general" in text
