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

from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.music import (
    COLORS,
    MusicPlayer,
    PlayerControlView,
    QueueView,
    SearchView,
    added_playlist_embed,
    added_to_queue_embed,
    close_nodes,
    create_embed,
    format_duration,
    now_playing_embed,
    queue_embed,
    setup_node,
)

logger = logging.getLogger("bot.cogs.music")

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


class MusicCog(commands.Cog, name="Music"):  # type: ignore[misc]
    """Управляет воспроизведением музыки через Lavalink-ноду."""

    def __init__(self, bot: commands.Bot) -> None:
        """Сохраняет ссылку на бота. Подключение к Lavalink происходит в :meth:`cog_load`."""
        self.bot: commands.Bot = bot

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
        for guild in self.bot.guilds:
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

        embed = now_playing_embed(player)
        view = PlayerControlView(player)

        old_msg = player.now_playing_message
        if old_msg is not None:
            try:
                await old_msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                player.now_playing_message = None

        try:
            player.now_playing_message = await player.text_channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            logger.warning("Не удалось отправить now-playing сообщение: %s", exc)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        """При завершении трека: если очередь пуста — снимает кнопки."""
        player = payload.player
        if not isinstance(player, MusicPlayer):
            return
        # Wavelink сам подхватит следующий трек из player.queue, мы только
        # очищаем кнопки если очередь пуста и нового трека не будет.
        if player.queue.is_empty and player.current is None:
            if player.now_playing_message is not None:
                try:
                    await player.now_playing_message.edit(view=None)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        """Логирует ошибку Lavalink при воспроизведении и сообщает в чат."""
        player = payload.player
        logger.error(
            "Ошибка воспроизведения трека: %s (severity=%s, cause=%s)",
            payload.exception,
            getattr(payload.exception, "severity", "?"),
            getattr(payload.exception, "cause", "?"),
        )
        if isinstance(player, MusicPlayer) and player.text_channel is not None:
            try:
                await player.text_channel.send(
                    embed=create_embed(
                        "❌ Ошибка воспроизведения",
                        f"Lavalink не смог проиграть трек: `{payload.exception}`. "
                        "Перехожу к следующему.",
                        COLORS["ERROR"],
                    )
                )
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
            try:
                await player.text_channel.send(
                    embed=create_embed(
                        "💤 Автоотключение",
                        "Бот покинул канал из-за неактивности.",
                        COLORS["INFO"],
                    )
                )
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

        try:
            player = await target_channel.connect(cls=MusicPlayer, self_deaf=True)
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
        """Колбэк для ``SearchView`` — добавляет выбранный трек в очередь."""
        player = interaction.guild.voice_client if interaction.guild else None
        if not isinstance(player, MusicPlayer):
            await interaction.response.send_message(
                "Сначала бот должен подключиться к голосовому каналу (/play <ссылка>).",
                ephemeral=True,
            )
            return
        position = await self._enqueue(player, track, requester)
        embed = added_to_queue_embed(track, position, player)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

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
        YouTube Music). Для плейлистов добавляет все треки.
        """
        await ctx.defer()

        player = await self._ensure_player(ctx)
        if player is None:
            return
        if isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            player.text_channel = ctx.channel

        is_url = bool(_URL_RE.match(query.strip()))
        try:
            results: wavelink.Search = await wavelink.Playable.search(query)
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
            await safe_send(ctx, embed=added_playlist_embed(results, added, player))
            return

        # URL на один трек — добавляем сразу первый результат.
        if is_url:
            track = results[0]
            position = await self._enqueue(player, track, requester)
            await safe_send(ctx, embed=added_to_queue_embed(track, position, player))
            return

        # Текстовый поиск — показываем меню выбора.
        from config import get_settings

        limit = get_settings().music.lavalink.search_limit
        top_results = results[:limit]
        if len(top_results) == 1:
            # Единственный результат — добавляем без меню.
            track = top_results[0]
            position = await self._enqueue(player, track, requester)
            await safe_send(ctx, embed=added_to_queue_embed(track, position, player))
            return

        view = SearchView(self, top_results, requester)
        await safe_send(
            ctx,
            embed=create_embed(
                f"🔍 Результаты поиска: «{query}»",
                f"Выберите трек из топ-{len(top_results)} результатов:",
                COLORS["DEFAULT"],
            ),
        )
        # safe_send уже отправил эмбед; теперь добавляем view отдельным
        # followup-сообщением (View нельзя добавить ретроактивно).
        if ctx.interaction:
            await ctx.interaction.followup.send(view=view, ephemeral=True)
        else:
            await ctx.send(view=view)

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
        await safe_send(
            ctx,
            embed=create_embed("⏭️ Трек пропущен", f"Пропущено: **{title}**", COLORS["INFO"]),
        )

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
        await safe_send(
            ctx,
            embed=create_embed(
                "⏹️ Остановлено",
                "Воспроизведение остановлено, очередь очищена, бот покинул канал.",
                COLORS["INFO"],
            ),
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
        await safe_send(ctx, embed=create_embed("⏸️ Пауза", "", COLORS["INFO"]))

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
        await safe_send(ctx, embed=create_embed("▶️ Продолжаем", "", COLORS["SUCCESS"]))

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
            await safe_send(
                ctx,
                embed=create_embed(
                    "ℹ️ Очередь пуста",
                    "Используйте `/play <запрос>` чтобы добавить трек.",
                    COLORS["INFO"],
                ),
            )
            return
        from config import get_settings

        page_size = get_settings().music.lavalink.queue_page_size
        embed = queue_embed(player, page=page, page_size=page_size)
        view = QueueView(player, page=page, page_size=page_size)
        await safe_send(ctx, embed=embed)
        if ctx.interaction:
            await ctx.interaction.followup.send(view=view, ephemeral=True)
        else:
            await ctx.send(view=view)

    @commands.hybrid_command(
        name="nowplaying", aliases=["np"], description="Показать текущий трек."
    )
    @command_error_handler
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Отправляет актуальный now-playing эмбед."""
        player = ctx.guild.voice_client if ctx.guild else None
        if not isinstance(player, MusicPlayer) or player.current is None:
            await safe_send_error(ctx, "Сейчас ничего не играет.")
            return
        await safe_send(ctx, embed=now_playing_embed(player))

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
        await safe_send(
            ctx,
            embed=create_embed(
                "🗑️ Трек убран",
                f"Удалено из очереди: **{target.title}**",
                COLORS["INFO"],
            ),
        )

    @commands.hybrid_command(name="clear", description="Очистить очередь.")
    @command_error_handler
    async def clear(self, ctx: commands.Context) -> None:
        """Очищает очередь (только админ)."""
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
        await safe_send(
            ctx,
            embed=create_embed(
                "🗑️ Очередь очищена",
                f"Убрано треков: **{count}**",
                COLORS["INFO"],
            ),
        )

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
        await safe_send(ctx, embed=create_embed(f"🔁 {label}", "", COLORS["INFO"]))

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
        await safe_send(
            ctx,
            embed=create_embed(
                "🔀 Перемешано",
                f"Очередь из {len(player.queue)} треков перемешана.",
                COLORS["SUCCESS"],
            ),
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
        await safe_send(
            ctx,
            embed=create_embed(f"🔊 Громкость: {value}%", "", COLORS["INFO"]),
        )

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
        await safe_send(
            ctx,
            embed=create_embed(
                "⏩ Перемотано",
                f"Текущая позиция: `{format_duration(seconds * 1000)}`",
                COLORS["INFO"],
            ),
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
