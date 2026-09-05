"""Ког для управления музыкальным плеером на базе Lavalink + wavelink.

Содержит hybrid-команды (slash + префикс) play/skip/stop/pause/resume/queue/
nowplaying/remove/clear/loop/shuffle/volume/seek и слушатели событий wavelink
для синхронизации now-playing сообщения с реальным состоянием воспроизведения.
"""

from __future__ import annotations

import logging
import re

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from utils.error_handler import command_error_handler, safe_send_error
from utils.music import (
    MusicPlayer,
    NowPlayingView,
    QueueLayoutView,
    SearchLayoutView,
    added_playlist_card,
    added_to_queue_card,
    close_nodes,
    format_duration,
    now_playing_static_view,
    setup_node,
    status_card,
)
from utils.ui import colors

logger = logging.getLogger("bot.cogs.music")

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_SEARCH_PREFIX_RE = re.compile(r"^[a-z][a-z0-9]*search:", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def _shorten_error(value: object, limit: int) -> str:
    """Готовит однострочный фрагмент ошибки для Discord и компактных логов."""
    text = " ".join(str(value).split()) or "неизвестная ошибка"
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class MusicCog(commands.Cog, name="Music"):  # type: ignore[misc]
    """Управляет воспроизведением музыки через Lavalink-ноду."""

    def __init__(self, bot: commands.Bot) -> None:
        """Сохраняет ссылку на бота. Подключение к Lavalink происходит в :meth:`cog_load`."""
        self.bot: commands.Bot = bot

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------

    async def _publish_now_playing(self, player: MusicPlayer) -> None:
        """Отправляет или обновляет сообщение Components V2 "Сейчас играет"."""
        channel = player.text_channel
        if channel is None:
            return
        old_msg = player.now_playing_message
        if old_msg is not None:
            try:
                await old_msg.edit(view=NowPlayingView(player))
                return
            except (discord.NotFound, discord.HTTPException):
                player.now_playing_message = None
        try:
            player.now_playing_message = await channel.send(view=NowPlayingView(player))
        except discord.HTTPException as exc:
            logger.warning("Не удалось отправить now-playing сообщение: %s", exc)

    async def _send_status(
        self,
        ctx: commands.Context,
        title: str,
        description: str = "",
        *,
        kind: str = "info",
    ) -> None:
        """Отправляет короткий CV2-статус (пауза/скип/громкость…)."""
        accent = {
            "info": colors.INFO,
            "success": colors.SUCCESS,
            "error": colors.ERROR,
        }.get(kind, colors.NEUTRAL)
        await ctx.send(view=status_card(title, description, accent))

    async def _send_added(
        self,
        ctx: commands.Context,
        track: wavelink.Playable,
        position: int,
        player: MusicPlayer,
    ) -> None:
        """Отправляет CV2-подтверждение добавления одного трека."""
        await ctx.send(view=added_to_queue_card(track, position, player))

    async def _send_added_playlist(
        self,
        ctx: commands.Context,
        playlist: wavelink.Playlist,
        added: int,
        player: MusicPlayer,
    ) -> None:
        """Отправляет CV2-подтверждение добавления плейлиста."""
        await ctx.send(view=added_playlist_card(playlist, added, player))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        """Запускает фоновое подключение к Lavalink-ноде.

        ``setup_node`` ставит коннект в asyncio.Task и возвращает управление
        мгновенно — поэтому если Lavalink ещё не поднят (например, его только
        что добавили в docker-compose и нода стартует параллельно), бот не
        зависнет на старте, а музыкальные команды просто будут ругаться
        "нет ноды" до тех пор, пока ws-handshake не пройдёт.
        """
        await setup_node(self.bot)

    async def cog_unload(self) -> None:
        """Отключает плеер от голосового канала и закрывает Lavalink-ноду."""
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild is not None:
            vc = guild.voice_client
            if isinstance(vc, MusicPlayer):
                try:
                    await vc.disconnect()
                except Exception:  # pragma: no cover
                    pass
        await close_nodes()

    # ------------------------------------------------------------------
    # Wavelink event listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        """Логирует успешное подключение к Lavalink."""
        logger.info(
            "Lavalink-нода %s готова (resumed=%s, session_id=%s).",
            payload.node.identifier,
            payload.resumed,
            payload.session_id,
        )

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        """Отправляет/обновляет сообщение "Сейчас играет" при старте трека."""
        player = payload.player
        if not isinstance(player, MusicPlayer) or player.text_channel is None:
            return
        await self._publish_now_playing(player)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        """При завершении трека: если очередь пуста — снимает кнопки."""
        player = payload.player
        if not isinstance(player, MusicPlayer):
            return
        # Wavelink сам подхватит следующий трек из player.queue, мы только
        # снимаем интерактив, если очередь пуста и нового трека не будет.
        if player.queue.is_empty and player.current is None:
            if player.now_playing_message is not None:
                try:
                    await player.now_playing_message.edit(
                        view=status_card(
                            "⏹️ Очередь закончилась",
                            "Добавьте треки командой `/play`.",
                            colors.INFO,
                        ),
                    )
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        """Логирует ошибку Lavalink при воспроизведении и сообщает в чат."""
        player = payload.player
        exception = payload.exception
        message = exception.get("message") or exception.get("cause") or "неизвестная ошибка"
        severity = exception.get("severity", "?")
        cause = exception.get("cause", "?")
        logger.error(
            "Ошибка воспроизведения «%s»: %s (severity=%s, cause=%s)",
            payload.track.title,
            _shorten_error(message, 1500),
            severity,
            cause,
        )
        if isinstance(player, MusicPlayer) and player.text_channel is not None:
            title = "❌ Ошибка воспроизведения"
            description = (
                f"Lavalink не смог проиграть трек: `{_shorten_error(message, 700)}`. "
                "Перехожу к следующему."
            )
            try:
                await player.text_channel.send(view=status_card(title, description, colors.ERROR))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Wavelink сигналит, что плеер простаивает дольше ``inactive_timeout``."""
        if not isinstance(player, MusicPlayer):
            return
        logger.info(
            "Плеер простаивает в канале %s — отключаемся.",
            player.channel.name if player.channel else "?",
        )
        if player.text_channel is not None:
            title = "💤 Автоотключение"
            description = "Бот покинул канал из-за неактивности."
            try:
                await player.text_channel.send(view=status_card(title, description, colors.INFO))
            except discord.HTTPException:
                pass
        await player.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Если бот остался один в голосовом канале — отключаемся."""
        if member.bot:
            return
        guild = member.guild
        vc = guild.voice_client
        if not isinstance(vc, MusicPlayer) or vc.channel is None:
            return
        if before.channel != vc.channel and after.channel != vc.channel:
            return  # событие не про канал бота
        humans = [m for m in vc.channel.members if not m.bot]
        if humans:
            return
        logger.info("Бот остался один в %s — отключаемся.", vc.channel.name)
        await vc.disconnect()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_player(
        self,
        ctx: commands.Context,
    ) -> MusicPlayer | None:
        """Гарантирует, что бот подключён к голосовому каналу пользователя.

        Подключается, если ещё не подключён. Перемещается, если пользователь
        в другом канале. Возвращает текущий :class:`MusicPlayer` или ``None``
        с уведомлением в чат при ошибке.
        """
        if not isinstance(ctx.author, discord.Member):
            await safe_send_error(ctx, "Эта команда доступна только на сервере.")
            return None

        user_voice = ctx.author.voice
        if user_voice is None or user_voice.channel is None:
            await safe_send_error(
                ctx, "Вы должны быть в голосовом канале, чтобы использовать эту команду."
            )
            return None

        target_channel = user_voice.channel
        if not isinstance(target_channel, discord.VoiceChannel):
            await safe_send_error(ctx, "Бот поддерживает только обычные голосовые каналы.")
            return None

        player = ctx.guild.voice_client if ctx.guild else None
        if isinstance(player, MusicPlayer):
            if player.channel != target_channel:
                await player.move_to(target_channel)
            return player

        # Зомби-VoiceClient: на стороне discord.py остался устаревший клиент
        # (не наш MusicPlayer — значит после краха предыдущей сессии). Discord
        # не пускает в канал второй раз, пока первая сессия не закрыта явно,
        # из-за чего connect() висит до ChannelTimeoutException на 30 секундах.
        if player is not None:
            logger.warning(
                "Обнаружен зомби-VoiceClient (%s), принудительно дисконнектим",
                type(player).__name__,
            )
            try:
                await player.disconnect(force=True)
            except Exception as exc:
                logger.debug("Игнорируем ошибку при disconnect зомби-клиента: %s", exc)

        try:
            player = await target_channel.connect(cls=MusicPlayer, self_deaf=True)
        except wavelink.ChannelTimeoutException as exc:
            failed_player = ctx.guild.voice_client if ctx.guild else None
            if failed_player is not None:
                try:
                    await failed_player.disconnect(force=True)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Не удалось очистить VoiceClient после таймаута: %s",
                        cleanup_exc,
                    )
            logger.error("Таймаут Discord Voice handshake: %s", exc, exc_info=True)
            await safe_send_error(
                ctx,
                "Discord не завершил подключение к голосовому каналу. "
                "Состояние соединения очищено — повторите команду.",
            )
            return None
        except discord.ClientException as exc:
            await safe_send_error(ctx, f"Не удалось подключиться к каналу: {exc}")
            return None
        except Exception as exc:
            logger.error("Ошибка при подключении к VC: %s", exc, exc_info=True)
            await safe_send_error(ctx, "Не удалось подключиться к голосовому каналу.")
            return None

        # Сохраняем текстовый канал, чтобы события могли слать сюда now-playing.
        if isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            player.text_channel = ctx.channel

        # Применяем настройки по умолчанию.
        settings = getattr(self.bot, "settings", None)
        if settings is None:
            from config import get_settings

            settings = get_settings()
        default_vol = settings.music.lavalink.default_volume
        if player.volume != default_vol:
            await player.set_volume(default_vol)
        # включаем рекомендации по умолчанию выключено: некоторые источники
        # выдают шум; AutoPlay можно включать отдельной командой при желании.
        player.autoplay = wavelink.AutoPlayMode.partial
        return player

    def _require_same_voice(self, ctx: commands.Context) -> MusicPlayer | None:
        """Проверяет что вызывающий находится в том же VC, что и бот."""
        player = ctx.guild.voice_client if ctx.guild else None
        if not isinstance(player, MusicPlayer) or player.channel is None:
            return None
        if not isinstance(ctx.author, discord.Member) or ctx.author.voice is None:
            return None
        if ctx.author.voice.channel != player.channel:
            return None
        return player

    async def _enqueue(
        self,
        player: MusicPlayer,
        track: wavelink.Playable,
        requester: discord.Member,
    ) -> int:
        """Добавляет один трек в очередь и возвращает позицию (1-based)."""
        MusicPlayer.assign_requester(track, requester)
        position = len(player.queue) + (0 if player.playing else 1)
        await player.queue.put_wait(track)
        if not player.playing:
            next_track = player.queue.get()
            await player.play(next_track)
        return max(1, position)

    async def _enqueue_selected_track(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
        requester: discord.Member,
    ) -> None:
        """Колбэк для ``SearchLayoutView`` — добавляет выбранный трек в очередь."""
        player = interaction.guild.voice_client if interaction.guild else None
        if not isinstance(player, MusicPlayer):
            await interaction.response.send_message(
                "Сначала бот должен подключиться к голосовому каналу (/play <ссылка>).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        position = await self._enqueue(player, track, requester)
        await interaction.edit_original_response(view=added_to_queue_card(track, position, player))

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.hybrid_command(
        name="play",
        description="Воспроизвести трек или плейлист по ссылке либо текстовому запросу.",
    )
    @app_commands.describe(
        query="Ссылка (YouTube/Spotify/SoundCloud/Apple Music) или текст для поиска"
    )
    @command_error_handler
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Добавляет трек в очередь и запускает воспроизведение, если нужно.

        Поддерживает прямые ссылки на YouTube, Spotify, Apple Music, SoundCloud,
        Bandcamp, Twitch, Vimeo, а также текстовый поиск (по умолчанию через
        YouTube). Для плейлистов добавляет все треки.
        """
        await ctx.defer()

        player = await self._ensure_player(ctx)
        if player is None:
            return
        if isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            player.text_channel = ctx.channel

        query = query.strip()
        is_url = bool(_URL_RE.match(query))
        # Wavelink иначе добавляет свой префикс даже к явному scsearch:/ytmsearch:.
        source = None if _SEARCH_PREFIX_RE.match(query) else wavelink.TrackSource.YouTube
        try:
            results: wavelink.Search = await wavelink.Playable.search(query, source=source)
        except wavelink.LavalinkLoadException as exc:
            await safe_send_error(ctx, f"Lavalink не смог загрузить запрос: `{exc}`")
            return

        if not results:
            await safe_send_error(ctx, f"Ничего не найдено по запросу: `{query}`")
            return

        requester = ctx.author
        if not isinstance(requester, discord.Member):
            await safe_send_error(ctx, "Не удалось определить участника.")
            return

        # Плейлист — добавляем все треки целиком.
        if isinstance(results, wavelink.Playlist):
            for track in results.tracks:
                MusicPlayer.assign_requester(track, requester)
            added = await player.queue.put_wait(results)
            if not player.playing:
                next_track = player.queue.get()
                await player.play(next_track)
            await self._send_added_playlist(ctx, results, added, player)
            return

        # URL на один трек — добавляем сразу первый результат.
        if is_url:
            track = results[0]
            position = await self._enqueue(player, track, requester)
            await self._send_added(ctx, track, position, player)
            return

        # Текстовый поиск — показываем меню выбора.
        from config import get_settings

        limit = get_settings().music.lavalink.search_limit
        top_results = results[:limit]
        if len(top_results) == 1:
            # Единственный результат — добавляем без меню.
            track = top_results[0]
            position = await self._enqueue(player, track, requester)
            await self._send_added(ctx, track, position, player)
            return

        await ctx.send(view=SearchLayoutView(self, top_results, requester, query), ephemeral=True)

    @commands.hybrid_command(name="skip", description="Пропустить текущий трек.")
    @command_error_handler
    async def skip(self, ctx: commands.Context) -> None:
        """Пропускает текущий трек (требует прав заказчика или админа)."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if player.current is None:
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(ctx.author):
            await safe_send_error(
                ctx,
                "Пропустить трек может только администратор или тот, кто заказал этот трек.",
            )
            return
        title = player.current.title
        await player.skip(force=True)
        await self._send_status(ctx, "⏭️ Трек пропущен", f"Пропущено: **{title}**")

    @commands.hybrid_command(
        name="stop",
        description="Остановить воспроизведение, очистить очередь и покинуть канал.",
    )
    @command_error_handler
    async def stop(self, ctx: commands.Context) -> None:
        """Останавливает воспроизведение и отключается (только админ)."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(
            ctx.author, admin_only=True
        ):
            await safe_send_error(ctx, "Остановить воспроизведение может только администратор.")
            return
        player.queue.clear()
        await player.disconnect()
        await self._send_status(
            ctx,
            "⏹️ Остановлено",
            "Воспроизведение остановлено, очередь очищена, бот покинул канал.",
        )

    @commands.hybrid_command(name="pause", description="Приостановить воспроизведение.")
    @command_error_handler
    async def pause(self, ctx: commands.Context) -> None:
        """Ставит воспроизведение на паузу."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if player.current is None:
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        if player.paused:
            await safe_send_error(ctx, "Воспроизведение уже на паузе.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(ctx.author):
            await safe_send_error(
                ctx,
                "Поставить на паузу может только администратор или тот, кто заказал этот трек.",
            )
            return
        await player.pause(True)
        await self._send_status(ctx, "⏸️ Пауза")

    @commands.hybrid_command(name="resume", description="Возобновить воспроизведение.")
    @command_error_handler
    async def resume(self, ctx: commands.Context) -> None:
        """Снимает с паузы."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if not player.paused:
            await safe_send_error(ctx, "Воспроизведение не на паузе.")
            return
        await player.pause(False)
        await self._send_status(ctx, "▶️ Продолжаем", kind="success")

    @commands.hybrid_command(
        name="queue", aliases=["q"], description="Показать очередь воспроизведения."
    )
    @app_commands.describe(page="Номер страницы (по 10 треков на странице)")
    @command_error_handler
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Показывает текущую очередь с пагинацией."""
        player = ctx.guild.voice_client if ctx.guild else None
        if not isinstance(player, MusicPlayer):
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        if player.current is None and len(player.queue) == 0:
            await self._send_status(
                ctx,
                "ℹ️ Очередь пуста",
                "Используйте `/play <запрос>` чтобы добавить трек.",
            )
            return
        from config import get_settings

        page_size = get_settings().music.lavalink.queue_page_size
        await ctx.send(view=QueueLayoutView(player, page=page, page_size=page_size))

    @commands.hybrid_command(
        name="nowplaying", aliases=["np"], description="Показать текущий трек."
    )
    @command_error_handler
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Отправляет актуальную CV2-карточку текущего трека."""
        player = ctx.guild.voice_client if ctx.guild else None
        if not isinstance(player, MusicPlayer) or player.current is None:
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        await ctx.send(view=now_playing_static_view(player))

    @commands.hybrid_command(
        name="remove",
        description="Убрать трек из очереди по его номеру (см. /queue).",
    )
    @app_commands.describe(index="Номер трека в очереди (начиная с 1)")
    @command_error_handler
    async def remove(self, ctx: commands.Context, index: int) -> None:
        """Удаляет трек из очереди (требует прав заказчика или админа)."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if index < 1 or index > len(player.queue):
            await safe_send_error(ctx, f"Неверный номер. В очереди {len(player.queue)} трек(ов).")
            return
        target = player.queue.peek(index - 1)
        is_admin = isinstance(ctx.author, discord.Member) and (
            ctx.author.guild_permissions.administrator
        )
        if not is_admin:
            requester_id = MusicPlayer.get_requester_id(target)
            if requester_id != ctx.author.id:
                await safe_send_error(
                    ctx,
                    "Убрать трек может только администратор или тот, кто его заказал.",
                )
                return
        player.queue.delete(index - 1)
        await self._send_status(ctx, "🗑️ Трек убран", f"Удалено из очереди: **{target.title}**")

    @commands.hybrid_command(name="clearqueue", aliases=["cq"], description="Очистить очередь.")
    @command_error_handler
    async def clearqueue(self, ctx: commands.Context) -> None:
        """Очищает очередь (только админ).

        Имя команды — `clearqueue`, чтобы не конфликтовать с `/clear` из admin-кога,
        который чистит сообщения в чате. Для prefix-вызовов есть короткий алиас `cq`.
        """
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if (
            not isinstance(ctx.author, discord.Member)
            or not ctx.author.guild_permissions.administrator
        ):
            await safe_send_error(ctx, "Очистить очередь может только администратор.")
            return
        count = len(player.queue)
        player.queue.clear()
        await self._send_status(ctx, "🗑️ Очередь очищена", f"Убрано треков: **{count}**")

    @commands.hybrid_command(name="loop", description="Сменить режим повтора (off/track/queue).")
    @app_commands.describe(mode="Режим: off — выключить, track — повторять трек, queue — очередь")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="off — выключить", value="off"),
            app_commands.Choice(name="track — повторять трек", value="track"),
            app_commands.Choice(name="queue — повторять очередь", value="queue"),
        ]
    )
    @command_error_handler
    async def loop(self, ctx: commands.Context, mode: str = "off") -> None:
        """Устанавливает режим повтора (off/track/queue)."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(ctx.author):
            await safe_send_error(
                ctx,
                "Сменить режим повтора может только администратор или заказчик текущего трека.",
            )
            return
        mapping = {
            "off": (wavelink.QueueMode.normal, "Повтор выключен"),
            "track": (wavelink.QueueMode.loop, "Повтор: текущий трек"),
            "queue": (wavelink.QueueMode.loop_all, "Повтор: вся очередь"),
        }
        if mode not in mapping:
            await safe_send_error(ctx, "Допустимые режимы: `off`, `track`, `queue`.")
            return
        new_mode, label = mapping[mode]
        player.queue.mode = new_mode
        await self._send_status(ctx, f"🔁 {label}")

    @commands.hybrid_command(name="shuffle", description="Перемешать очередь.")
    @command_error_handler
    async def shuffle(self, ctx: commands.Context) -> None:
        """Перемешивает оставшуюся очередь."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(ctx.author):
            await safe_send_error(
                ctx,
                "Перемешать очередь может только администратор или заказчик текущего трека.",
            )
            return
        if len(player.queue) < 2:
            await safe_send_error(ctx, "В очереди слишком мало треков для перемешивания.")
            return
        player.queue.shuffle()
        await self._send_status(
            ctx,
            "🔀 Перемешано",
            f"Очередь из {len(player.queue)} треков перемешана.",
            kind="success",
        )

    @commands.hybrid_command(name="volume", description="Установить громкость (0-200).")
    @app_commands.describe(value="Громкость 0-200% (по умолчанию максимум 200%)")
    @command_error_handler
    async def volume(self, ctx: commands.Context, value: int) -> None:
        """Меняет громкость плеера (только админ)."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if (
            not isinstance(ctx.author, discord.Member)
            or not ctx.author.guild_permissions.administrator
        ):
            await safe_send_error(ctx, "Изменить громкость может только администратор.")
            return
        from config import get_settings

        max_vol = get_settings().music.lavalink.max_volume
        if value < 0 or value > max_vol:
            await safe_send_error(ctx, f"Громкость должна быть в диапазоне 0–{max_vol}.")
            return
        await player.set_volume(value)
        await self._send_status(ctx, f"🔊 Громкость: {value}%")

    @commands.hybrid_command(name="seek", description="Перемотать трек на указанную позицию.")
    @app_commands.describe(position="Позиция в формате MM:SS или HH:MM:SS, либо число секунд")
    @command_error_handler
    async def seek(self, ctx: commands.Context, position: str) -> None:
        """Перематывает текущий трек на указанную позицию."""
        player = self._require_same_voice(ctx)
        if player is None:
            await safe_send_error(ctx, "Вы должны быть в том же голосовом канале, что и бот.")
            return
        if player.current is None or not player.playing:
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        if not isinstance(ctx.author, discord.Member) or not player.can_control(ctx.author):
            await safe_send_error(
                ctx,
                "Перематывать может только администратор или заказчик трека.",
            )
            return

        seconds = self._parse_seek(position)
        if seconds is None:
            await safe_send_error(ctx, "Не могу разобрать позицию. Примеры: `1:23`, `0:42`, `90`.")
            return
        if player.current.length is not None and seconds * 1000 >= player.current.length:
            await safe_send_error(ctx, "Указанная позиция больше длительности трека.")
            return
        await player.seek(seconds * 1000)
        await self._send_status(
            ctx, "⏩ Перемотано", f"Текущая позиция: `{format_duration(seconds * 1000)}`"
        )

    @staticmethod
    def _parse_seek(value: str) -> int | None:
        """Парсит ``"1:23"`` / ``"01:02:03"`` / ``"90"`` в число секунд."""
        value = value.strip()
        if value.isdigit():
            return int(value)
        match = _TIMESTAMP_RE.match(value)
        if not match:
            return None
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        if minutes >= 60 or seconds >= 60:
            return None
        return hours * 3600 + minutes * 60 + seconds


async def setup(bot: commands.Bot) -> None:
    """Регистрирует :class:`MusicCog` у бота."""
    await bot.add_cog(MusicCog(bot))
    logger.info("Музыкальный ког подключён (Lavalink + wavelink).")
