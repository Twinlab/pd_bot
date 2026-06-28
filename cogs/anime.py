"""Ког для автоматической и ручной публикации SFW аниме-изображений.

Изображения берутся с Danbooru. В отличие от безфильтрового safebooru, здесь
качество отбирается по полю ``score`` поста (см. ``anime.min_score`` в конфиге) —
это отсекает низкосортный арт, оставляя отобранные работы.

Рейтинг (``g``/``s``/``q``/``e``) задаётся в конфиге и может быть переопределён
вручную параметром команды ``/post_anime``.

Кеширование:
- Модуль ведёт кеш опубликованных постов, чтобы не повторяться.
- Кеш хранится в памяти (deque) и в БД (таблица anime_cache); при старте подгружается из БД.
"""

import logging
import random
from collections import deque
from datetime import time
from time import time as unix_now
from typing import Any, Literal, NamedTuple

import aiohttp
import discord
from discord.ext import commands, tasks

from config import get_settings
from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.models import AnimeCache
from utils.ui import image_card

logger: logging.Logger = logging.getLogger("bot.cogs.anime")

DANBOORU_API_URL = "https://danbooru.donmai.us/posts.json"
DANBOORU_POST_URL = "https://danbooru.donmai.us/posts/{post_id}"
ALLOWED_RATINGS: tuple[str, ...] = ("g", "s", "q", "e")
IMAGE_EXTENSIONS: frozenset[str] = frozenset({"jpg", "jpeg", "png", "gif", "webp"})
USER_AGENT = "pd_bot (Discord anime poster)"

MAX_RETRIES = 5


class AnimePost(NamedTuple):
    """Минимальное описание поста Danbooru, нужное для публикации."""

    url: str
    post_id: int
    score: int
    rating: str
    source: str
    artists: str
    characters: str


RATING_LABELS: dict[str, str] = {
    "g": "general",
    "s": "sensitive",
    "q": "questionable",
    "e": "explicit",
}


def _format_tag_names(tag_string: str) -> str:
    """Преобразует ``tag_string`` Danbooru в человекочитаемый список через запятую."""
    names = [name.replace("_", " ") for name in tag_string.split() if name]
    return ", ".join(names)


def _build_post_view(post: AnimePost, color: discord.Color) -> discord.ui.LayoutView:
    """Собирает «карточку» поста на Components V2.

    Картинка идёт через ``MediaGallery`` — показывается целиком, без обрезки. Имя
    персонажа (или запасной текст) служит кликабельной ссылкой на исходный пост
    Danbooru. Художник и метаданные (score/rating) — отдельными ``TextDisplay``.

    Args:
        post: Пост Danbooru для публикации.
        color: Цвет акцентной полосы контейнера.

    Returns:
        Готовый ``LayoutView`` с контейнером, картинкой и метаданными.
    """
    source_url = DANBOORU_POST_URL.format(post_id=post.post_id)
    title = post.characters[:256] if post.characters else "Открыть на Danbooru"
    rating_label = RATING_LABELS.get(post.rating, post.rating or "—")

    meta_lines: list[str] = []
    if post.artists:
        meta_lines.append(f"**Художник:** {post.artists[:1000]}")
    meta_lines.append(f"-# score: {post.score} · rating: {rating_label}")

    return image_card(
        media=post.url,
        accent=color,
        text_above=[f"### [{title}]({source_url})"],
        text_below=["\n".join(meta_lines)],
        timeout=None,
    )


class AnimeCog(commands.Cog):
    """Ког для публикации SFW аниме-изображений с Danbooru.

    Автоматически (по расписанию) и вручную публикует случайные изображения
    в заданный канал. Качество фильтруется по ``score``, рейтинг и теги — через
    ``config/bot_settings.yaml`` (секция ``anime``).
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког, читает настройки и запускает фоновые задачи.

        Args:
            bot: Экземпляр discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        self._session: aiohttp.ClientSession | None = None
        settings = get_settings()
        self.channel_id: int | None = settings.channels.anime
        self.cache_size: int = settings.anime.cache_size
        self.post_cache: deque[int] = deque(maxlen=self.cache_size)
        self._cache_loaded: bool = False

        if not self.channel_id:
            logger.error("Канал для публикации аниме не настроен или не найден.")
            return

        morning_time = time(
            hour=settings.anime.schedule.morning_hour, minute=settings.anime.schedule.morning_minute
        )
        evening_time = time(
            hour=settings.anime.schedule.evening_hour, minute=settings.anime.schedule.evening_minute
        )

        self.morning_post.change_interval(time=morning_time)
        self.evening_post.change_interval(time=evening_time)

        self.morning_post.start()
        self.evening_post.start()

    def _get_session(self) -> aiohttp.ClientSession:
        """Возвращает переиспользуемую aiohttp-сессию с User-Agent для Danbooru."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        return self._session

    async def _load_cache_from_db(self) -> None:
        """Загружает кеш из базы данных при первом использовании."""
        if self._cache_loaded:
            return

        try:
            last_items = await AnimeCache.all().order_by("-added_at").limit(self.cache_size)
            sorted_items = sorted(last_items, key=lambda x: x.added_at)

            for item in sorted_items:
                self.post_cache.append(item.post_id)

            self._cache_loaded = True
            logger.info(f"Кеш аниме загружен из БД: {len(sorted_items)} элементов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке кеша из БД: {e}", exc_info=True)
            self._cache_loaded = True

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога, останавливает задачи и закрывает сессию."""
        logger.info("Остановка задач публикации аниме...")
        self.morning_post.cancel()
        self.evening_post.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_anime_image(
        self, *, rating: str | None = None, tag: str | None = None
    ) -> AnimePost | None:
        """Возвращает случайный отобранный по качеству пост, которого нет в кеше.

        Сначала пробует франшиза-запрос (с вероятностью ``extra_tag_chance``), при неудаче
        (и если тег не задан явно) — fallback на базовый тег через ``order:rank``.

        Args:
            rating: Рейтинг ``g``/``s``/``q``/``e``. При ``None`` берётся случайный из
                ``settings.anime.ratings`` на каждую попытку.
            tag: Явный тег франшизы. Если задан, fallback не применяется.

        Returns:
            ``AnimePost`` или ``None``, если ничего подходящего не нашлось.
        """
        await self._load_cache_from_db()

        settings = get_settings()

        if tag is not None:
            return await self._search_by_explicit_tag(settings, rating=rating, tag=tag)

        for attempt in range(MAX_RETRIES):
            logger.info(f"Попытка {attempt + 1}/{MAX_RETRIES} (основной запрос)...")
            posts = await self._fetch_danbooru_posts(
                settings, rating=self._pick_rating(settings, rating), tag=tag, use_extra=True
            )
            candidate = self._pick_fresh(posts)
            if candidate:
                logger.info(
                    f"Найден новый пост (ID: {candidate.post_id}, score: {candidate.score})"
                )
                return candidate

        if tag is None:
            for attempt in range(MAX_RETRIES):
                logger.info(
                    f"Попытка {attempt + 1}/{MAX_RETRIES} (fallback: базовый тег, order:rank)..."
                )
                posts = await self._fetch_danbooru_posts(
                    settings, rating=self._pick_rating(settings, rating), tag=None, use_extra=False
                )
                candidate = self._pick_fresh(posts)
                if candidate:
                    logger.info(f"Найден новый пост в fallback (ID: {candidate.post_id})")
                    return candidate

        logger.error("Не удалось найти новый подходящий пост после всех попыток.")
        return None

    @staticmethod
    def _pick_rating(settings: Any, override: str | None) -> str:
        """Возвращает рейтинг: явный override или случайный из ``settings.anime.ratings``."""
        if override:
            return override
        ratings = settings.anime.ratings or ["s"]
        return str(random.choice(ratings))

    def _pick_fresh(self, posts: list[AnimePost]) -> AnimePost | None:
        """Выбирает случайный пост, которого ещё нет в кеше."""
        candidates = [p for p in posts if p.post_id not in self.post_cache]
        return random.choice(candidates) if candidates else None

    async def _fetch_danbooru_posts(
        self, settings: Any, *, rating: str, tag: str | None, use_extra: bool
    ) -> list[AnimePost]:
        """Запрашивает посты с Danbooru и фильтрует их по качеству, рейтингу и тегам.

        Из-за лимита Member (2 «обычных» тега; ``order:`` считается, ``rating:``/``score:``
        — нет) применяются две стратегии:

        - Франшиза (``use_extra`` сработал или задан ``tag``): ``<франшиза> order:random
          rating:X score:>=N`` — истинный рандом; «девочка» проверяется по тегам поста.
        - Базовый тег: ``<1girl|2girls> order:rank rating:X`` — ранг = качество, надёжно
          даже на тяжёлом теге (страницы/``order:random`` на нём таймаутят на 3-сек лимите).

        Args:
            settings: Объект настроек бота.
            rating: Конкретный рейтинг для этого запроса.
            tag: Явный тег франшизы; иначе берётся случайный из ``extra_tags``.
            use_extra: Разрешить уйти в франшиза-запрос (с вероятностью ``extra_tag_chance``).

        Returns:
            Список подходящих постов (может быть пустым).
        """
        franchise = tag
        if franchise is None and use_extra and settings.anime.extra_tags:
            if random.random() < settings.anime.extra_tag_chance:
                franchise = random.choice(settings.anime.extra_tags)

        require_girl = franchise is not None
        if franchise is not None:
            search_tags = [
                franchise,
                "order:random",
                f"rating:{rating}",
                f"score:>={settings.anime.min_score}",
            ]
        else:
            base = random.choice(settings.anime.base_tags) if settings.anime.base_tags else "1girl"
            search_tags = [base, "order:rank", f"rating:{rating}"]

        status, data = await self._request_danbooru(
            settings,
            {"tags": " ".join(search_tags), "limit": str(settings.anime.limit)},
        )
        if status != 200:
            return []
        return self._parse_posts(data, settings, rating, require_girl=require_girl)

    async def _request_danbooru(
        self, settings: Any, params: dict[str, str]
    ) -> tuple[int, list[Any]]:
        """Выполняет GET к Danbooru и возвращает ``(http_status, сырые посты)``.

        При не-200 (или сетевой ошибке — тогда status=0) список пустой. Логин/ключ
        подставляются автоматически, если заданы в настройках.
        """
        if settings.danbooru_login and settings.danbooru_api_key:
            params = {
                **params,
                "login": settings.danbooru_login,
                "api_key": settings.danbooru_api_key,
            }

        session = self._get_session()
        try:
            async with session.get(DANBOORU_API_URL, params=params) as response:
                if response.status != 200:
                    logger.warning(f"Danbooru вернул HTTP {response.status}")
                    return response.status, []
                data = await response.json()
        except Exception as e:
            logger.warning(f"Ошибка запроса к Danbooru: {e}")
            return 0, []

        if not isinstance(data, list):
            logger.debug("Ответ Danbooru не является списком постов")
            return 200, []
        return 200, data

    async def _search_by_explicit_tag(
        self, settings: Any, *, rating: str | None, tag: str
    ) -> AnimePost | None:
        """Ищет пост по явному тегу для ручной команды ``/post_anime``.

        Фильтры автопостинга (``excluded_tags``/``base_tags``/require_girl) НЕ применяются —
        они только для авто-публикаций. Берётся любой пост с этим тегом, заданным рейтингом
        и ``score >= min_score``.

        ``order:random`` на сверхпопулярных тегах (миллионы постов, напр. ``1girl``) Danbooru
        отвечает HTTP 500, поэтому при 500 делается фолбэк на ``order:rank``.

        Args:
            settings: Объект настроек бота.
            rating: Рейтинг ``g``/``s``/``q``/``e`` или ``None`` (тогда случайный из конфига).
            tag: Явный тег Danbooru.

        Returns:
            ``AnimePost`` или ``None``, если ничего подходящего не нашлось.
        """
        chosen_rating = self._pick_rating(settings, rating)
        score_filter = f"score:>={settings.anime.min_score}"
        limit = str(settings.anime.limit)

        for attempt in range(MAX_RETRIES):
            logger.info(f"Попытка {attempt + 1}/{MAX_RETRIES} (ручной тег '{tag}')...")
            posts: list[AnimePost] = []
            for order in ("order:random", "order:rank"):
                status, data = await self._request_danbooru(
                    settings,
                    {
                        "tags": f"{tag} {order} rating:{chosen_rating} {score_filter}",
                        "limit": limit,
                    },
                )
                if status == 200:
                    posts = self._parse_posts(
                        data, settings, chosen_rating, require_girl=False, apply_excluded=False
                    )
                    break
                if status != 500:
                    break

            candidate = self._pick_fresh(posts)
            if candidate:
                logger.info(
                    f"Найден пост по тегу '{tag}' (ID: {candidate.post_id}, score: {candidate.score})"
                )
                return candidate

        logger.error(f"Не удалось найти пост по тегу '{tag}' после всех попыток.")
        return None

    def _parse_posts(
        self,
        data: list[Any],
        settings: Any,
        rating: str,
        *,
        require_girl: bool,
        apply_excluded: bool = True,
    ) -> list[AnimePost]:
        """Отбирает из сырого ответа Danbooru пригодные для публикации посты.

        Args:
            data: Сырой список постов от API.
            settings: Объект настроек бота.
            rating: Ожидаемый рейтинг (пост с другим отбрасывается).
            require_girl: Требовать наличие базового тега (``1girl``/``2girls``) в посте —
                нужно для франшиза-запроса, где базовый тег не входит в сам запрос.
            apply_excluded: Применять чёрный список ``excluded_tags``. Для ручного поиска
                по явному тегу выключается (конфиг — только для автопостов).
        """
        excluded = set(settings.anime.excluded_tags) if apply_excluded else set()
        base_tags = set(settings.anime.base_tags)
        min_score = settings.anime.min_score
        result: list[AnimePost] = []

        for post in data:
            if not isinstance(post, dict):
                continue
            post_id = post.get("id")
            if post_id is None:
                continue
            if (post.get("file_ext") or "").lower() not in IMAGE_EXTENSIONS:
                continue
            url = post.get("file_url") or post.get("large_file_url")
            if not url:
                continue
            if post.get("rating") != rating:
                continue
            score = int(post.get("score") or 0)
            if score < min_score:
                continue
            tag_set = set((post.get("tag_string") or "").split())
            if tag_set & excluded:
                continue
            if require_girl and not (tag_set & base_tags):
                continue

            result.append(
                AnimePost(
                    url=str(url),
                    post_id=int(post_id),
                    score=score,
                    rating=str(post.get("rating") or ""),
                    source=str(post.get("source") or ""),
                    artists=_format_tag_names(post.get("tag_string_artist") or ""),
                    characters=_format_tag_names(post.get("tag_string_character") or ""),
                )
            )

        return result

    async def post_anime_image(self, *, rating: str | None = None, tag: str | None = None) -> bool:
        """Получает и публикует пост в настроенный канал.

        Args:
            rating: Переопределение рейтинга для этой публикации.
            tag: Переопределение содержательного тега.

        Returns:
            ``True`` при успешной публикации, иначе ``False``.
        """
        try:
            if not await self._check_channel_exists():
                return False

            channel = self.bot.get_channel(self.channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.error(
                    "Канал %s не найден или не является текстовым на момент публикации.",
                    self.channel_id,
                )
                return False

            post = await self.get_anime_image(rating=rating, tag=tag)
            if not post:
                logger.error("Не удалось получить новый пост для публикации")
                return False

            view = _build_post_view(post, get_settings().get_discord_color("default"))
            await channel.send(view=view)
            self.post_cache.append(post.post_id)
            try:
                await AnimeCache.create(post_id=post.post_id, added_at=int(unix_now()))
            except Exception as e:
                logger.error(f"Ошибка при сохранении поста {post.post_id} в БД: {e}", exc_info=True)

            logger.info(
                "Пост опубликован в #%s | Danbooru #%s | score=%s rating=%s | "
                "художник=%s | персонажи=%s | источник=%s | post=%s | кэш=%s/%s",
                channel.name,
                post.post_id,
                post.score,
                post.rating,
                post.artists or "—",
                post.characters or "—",
                post.source or "—",
                DANBOORU_POST_URL.format(post_id=post.post_id),
                len(self.post_cache),
                self.cache_size,
            )
            return True

        except Exception as e:
            logger.error(f"Ошибка в post_anime_image: {e}", exc_info=True)
            return False

    # --- Фоновые задачи ---

    @tasks.loop(time=time(hour=10, minute=0))
    async def morning_post(self) -> None:
        """Ежедневная утренняя публикация."""
        logger.info("Запуск утренней публикации аниме...")
        await self.post_anime_image()

    @tasks.loop(time=time(hour=18, minute=0))
    async def evening_post(self) -> None:
        """Ежедневная вечерняя публикация."""
        logger.info("Запуск вечерней публикации аниме...")
        await self.post_anime_image()

    @morning_post.before_loop
    async def before_morning_post(self) -> None:
        """Ожидает готовности бота перед первым запуском утренней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача morning_post готова к запуску.")

    @evening_post.before_loop
    async def before_evening_post(self) -> None:
        """Ожидает готовности бота перед первым запуском вечерней задачи."""
        await self.bot.wait_until_ready()
        logger.info("Задача evening_post готова к запуску.")

    # --- Команды ---

    @commands.hybrid_command(description="Опубликовать случайное аниме-изображение сейчас")
    @discord.app_commands.describe(
        rating="Рейтинг: g (general), s (sensitive), q (questionable), e (explicit)",
        tag="Конкретный тег Danbooru (например, genshin_impact)",
    )
    @discord.app_commands.default_permissions(administrator=True)
    @discord.app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def post_anime(
        self,
        ctx: commands.Context,
        rating: Literal["g", "s", "q", "e"] | None = None,
        tag: str | None = None,
    ) -> None:
        """Ручная публикация поста с возможностью выбрать рейтинг и тег.

        Доступно администраторам. Публикует в настроенный канал.

        Args:
            ctx: Контекст команды.
            rating: Рейтинг публикации. По умолчанию — из конфига.
            tag: Конкретный тег Danbooru для поиска.
        """
        # Поиск поста занимает до ~15 c (ретраи Danbooru), а токен слэш-команды живёт 3 c —
        # без defer ответ упрётся в 404 Unknown interaction. Откладываем сразу.
        await ctx.defer(ephemeral=True)

        settings = get_settings()
        if not await self._check_channel_exists():
            await safe_send_error(ctx, settings.messages.errors["anime_channel_not_configured"])
            return

        success = await self.post_anime_image(rating=rating, tag=tag)

        if success:
            channel = self.bot.get_channel(self.channel_id)
            channel_label = channel.name if isinstance(channel, discord.TextChannel) else "?"
            await safe_send(
                ctx,
                f"Аниме-изображение успешно опубликовано в канале #{channel_label}!",
                ephemeral=True,
            )
        else:
            await safe_send_error(
                ctx,
                "Не удалось опубликовать аниме-изображение. Проверьте логи для подробностей.",
            )

    async def _check_channel_exists(self) -> bool:
        """Проверяет существование настроенного канала для публикации.

        Returns:
            ``True``, если канал существует и доступен, иначе ``False``.
        """
        if not self.channel_id:
            logger.error("ID канала для публикации аниме не настроен.")
            return False

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.error(f"Канал с ID {self.channel_id} не найден")
            return False

        return True


async def setup(bot: commands.Bot) -> None:
    """Загружает ког AnimeCog в бота.

    Args:
        bot: Экземпляр бота Discord.
    """
    await bot.add_cog(AnimeCog(bot))
    logger.info("Ког AnimeCog успешно загружен.")
