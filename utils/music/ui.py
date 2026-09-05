"""Discord Components V2 музыкального плеера.

Now-playing, поиск и очередь собраны на ``LayoutView``. Кнопки и Select-меню
используют ``custom_id`` с префиксом ``music:``, чтобы их было легко
идентифицировать в логах и при необходимости сделать persistent view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import wavelink

from utils.error_handler import safe_send_error
from utils.ui import colors

from .embeds import (
    _footer_for_player,
    _requester_mention,
    _track_source_label,
    format_duration,
    status_card,
)

if TYPE_CHECKING:
    from .player import MusicPlayer


# ---------------------------------------------------------------------------
# Search selection
# ---------------------------------------------------------------------------


class SearchSelect(discord.ui.Select):
    """Выпадающий список треков, найденных по запросу ``/play <текст>``."""

    def __init__(
        self,
        tracks: list[wavelink.Playable],
        requester_id: int,
    ) -> None:
        """Готовит SelectOption-ы из списка результатов wavelink-поиска."""
        self._tracks = tracks
        self._requester_id = requester_id

        options: list[discord.SelectOption] = []
        for idx, track in enumerate(tracks[:25]):
            label = (track.title or f"Трек {idx + 1}")[:100]
            description = (f"{track.author or 'неизвестно'} · {format_duration(track.length)}")[
                :100
            ]
            options.append(
                discord.SelectOption(label=label, description=description, value=str(idx))
            )

        super().__init__(
            placeholder="Выберите трек из результатов поиска…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="music:search_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Делегирует выбор владельцу-view, чтобы тот добавил трек в очередь."""
        if interaction.user.id != self._requester_id:
            await interaction.response.send_message(
                "Только пользователь, начавший поиск, может выбрать трек.", ephemeral=True
            )
            return
        handle_selection = getattr(self.view, "handle_selection", None)
        if handle_selection is not None:
            await handle_selection(interaction, self._tracks[int(self.values[0])])


# ---------------------------------------------------------------------------
# Components V2
# ---------------------------------------------------------------------------


def build_now_playing_container(player: MusicPlayer) -> discord.ui.Container:
    """Собирает CV2-контейнер "Сейчас играет" (без кнопок управления).

    Используется и интерактивным :class:`NowPlayingView`, и статичной карточкой
    для ``/nowplaying``. Если трека нет — возвращает контейнер с подсказкой.
    """
    track = player.current
    container: discord.ui.Container = discord.ui.Container(accent_colour=colors.NEUTRAL)
    if track is None:
        container.add_item(discord.ui.TextDisplay("## ⏹️ Сейчас ничего не играет"))
        container.add_item(
            discord.ui.TextDisplay("Используйте `/play <запрос>`, чтобы добавить трек.")
        )
        return container

    state_emoji = "⏸️" if player.paused else "▶️"
    head = (
        f"## {state_emoji} Сейчас играет\n**[{track.title}]({track.uri or 'https://discord.com'})**"
    )
    if track.author:
        head += f"\n_{track.author}_"
    if track.artwork:
        container.add_item(discord.ui.Section(head, accessory=discord.ui.Thumbnail(track.artwork)))
    else:
        container.add_item(discord.ui.TextDisplay(head))

    container.add_item(
        discord.ui.TextDisplay(
            f"**Длительность:** {format_duration(track.length)}\u2002·\u2002"
            f"**Источник:** {_track_source_label(track)}\u2002·\u2002"
            f"**Заказал:** {_requester_mention(track, player.guild)}"
        )
    )
    if len(player.queue) > 0:
        next_track = player.queue.peek(0)
        container.add_item(
            discord.ui.TextDisplay(
                f"**Следующий:** [{next_track.title}]({next_track.uri or 'https://discord.com'})"
            )
        )
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(f"-# {_footer_for_player(player)}"))
    return container


def now_playing_static_view(player: MusicPlayer) -> discord.ui.LayoutView:
    """Неинтерактивный снимок "Сейчас играет" для ответа на ``/nowplaying``."""
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    view.add_item(build_now_playing_container(player))
    return view


class _NowPlayingPrimaryRow(discord.ui.ActionRow["NowPlayingView"]):
    """Первый ряд управления: пауза/возобновление, скип, стоп."""

    @discord.ui.button(
        emoji="⏸️",
        label="Пауза",
        style=discord.ButtonStyle.secondary,
        custom_id="music:pause_resume",
    )
    async def pause_resume(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self.view.handle_pause(interaction)

    @discord.ui.button(
        emoji="⏭️", label="Скип", style=discord.ButtonStyle.primary, custom_id="music:skip"
    )
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_skip(interaction)

    @discord.ui.button(
        emoji="⏹️", label="Стоп", style=discord.ButtonStyle.danger, custom_id="music:stop"
    )
    async def stop_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self.view.handle_stop(interaction)


class _NowPlayingSecondaryRow(discord.ui.ActionRow["NowPlayingView"]):
    """Второй ряд: режим повтора, перемешать, показать очередь."""

    @discord.ui.button(
        emoji="🔁",
        label="Повтор: выкл",
        style=discord.ButtonStyle.secondary,
        custom_id="music:loop",
    )
    async def loop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_loop(interaction)

    @discord.ui.button(
        emoji="🔀",
        label="Перемешать",
        style=discord.ButtonStyle.secondary,
        custom_id="music:shuffle",
    )
    async def shuffle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.handle_shuffle(interaction)

    @discord.ui.button(
        emoji="📜", label="Очередь", style=discord.ButtonStyle.blurple, custom_id="music:queue"
    )
    async def show_queue(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self.view.handle_show_queue(interaction)


class NowPlayingView(discord.ui.LayoutView):
    """Интерактивная карточка текущего трека с кнопками управления.

    Контент и кнопки управления живут в одном ``LayoutView``: при каждом действии
    вью перерисовывается целиком (как :class:`utils.profile.views.ProfileView`) и
    редактирует сообщение через ``edit_message(view=self)``.
    """

    def __init__(self, player: MusicPlayer, *, timeout: float | None = 3600.0) -> None:
        """Создаёт вью и сразу синхронизирует кнопки с состоянием плеера."""
        super().__init__(timeout=timeout)
        self.player: MusicPlayer = player
        self._primary = _NowPlayingPrimaryRow()
        self._secondary = _NowPlayingSecondaryRow()
        self._render()

    def _sync_buttons(self) -> None:
        """Пересчитывает ``disabled`` и подписи кнопок под текущее состояние."""
        has_current = self.player.current is not None
        connected = self.player.connected
        for row in (self._primary, self._secondary):
            for child in row.children:
                if not isinstance(child, discord.ui.Button):
                    continue
                cid = child.custom_id or ""
                if cid == "music:pause_resume":
                    child.disabled = not has_current
                    if self.player.paused:
                        child.label = "Продолжить"
                        child.emoji = "▶️"
                        child.style = discord.ButtonStyle.success
                    else:
                        child.label = "Пауза"
                        child.emoji = "⏸️"
                        child.style = discord.ButtonStyle.secondary
                elif cid == "music:skip":
                    child.disabled = not has_current
                elif cid == "music:stop":
                    child.disabled = not connected
                elif cid == "music:loop":
                    emoji, label = {
                        wavelink.QueueMode.normal: ("🔁", "Повтор: выкл"),
                        wavelink.QueueMode.loop: ("🔂", "Повтор: трек"),
                        wavelink.QueueMode.loop_all: ("🔁", "Повтор: очередь"),
                    }.get(self.player.queue.mode, ("🔁", "Повтор: ?"))
                    child.emoji = emoji
                    child.label = label
                elif cid == "music:shuffle":
                    child.disabled = len(self.player.queue) < 2
                elif cid == "music:queue":
                    child.disabled = self.player.current is None and len(self.player.queue) == 0

    def _render(self) -> None:
        """Пересобирает ``LayoutView`` под текущее состояние плеера."""
        self.clear_items()
        container = build_now_playing_container(self.player)
        self._sync_buttons()
        container.add_item(self._primary)
        container.add_item(self._secondary)
        self.add_item(container)

    async def _validate(
        self,
        interaction: discord.Interaction,
        *,
        admin_only: bool = False,
        require_current_track: bool = True,
    ) -> bool:
        """Проверка перед действием по кнопке (тот же канал + права)."""
        member = interaction.user
        if not isinstance(member, discord.Member):
            await safe_send_error(interaction, "Эта команда доступна только на сервере.")
            return False
        vc = self.player.channel
        user_voice = member.voice
        if vc is None or user_voice is None or user_voice.channel != vc:
            await safe_send_error(
                interaction, "Вы должны быть в том же голосовом канале, что и бот."
            )
            return False
        if require_current_track and self.player.current is None:
            await safe_send_error(interaction, "Сейчас ничего не играет.")
            return False
        if not self.player.can_control(member, admin_only=admin_only):
            await safe_send_error(
                interaction,
                "Это действие может выполнить только администратор"
                + ("." if admin_only else " или заказчик текущего трека."),
            )
            return False
        return True

    async def _edit(self, interaction: discord.Interaction) -> None:
        """Перерисовывает now-playing сообщение под актуальное состояние."""
        self._render()
        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)

    async def handle_pause(self, interaction: discord.Interaction) -> None:
        """Пауза / возобновление воспроизведения."""
        if not await self._validate(interaction):
            return
        await interaction.response.defer()
        await self.player.pause(not self.player.paused)
        await self._edit(interaction)

    async def handle_skip(self, interaction: discord.Interaction) -> None:
        """Пропуск текущего трека (сообщение обновит ``on_wavelink_track_start``)."""
        if not await self._validate(interaction):
            return
        await interaction.response.defer()
        await self.player.skip(force=True)

    async def handle_stop(self, interaction: discord.Interaction) -> None:
        """Полная остановка: очистка очереди и отключение (только админ)."""
        if not await self._validate(interaction, admin_only=True, require_current_track=False):
            return
        await interaction.response.defer()
        self.player.queue.clear()
        await self.player.disconnect()
        self.stop()
        try:
            await interaction.edit_original_response(
                view=status_card(
                    "⏹️ Воспроизведение остановлено",
                    "Бот покинул голосовой канал, очередь очищена.",
                    colors.INFO,
                )
            )
        except discord.HTTPException:
            pass

    async def handle_loop(self, interaction: discord.Interaction) -> None:
        """Циклит режим повтора: off → track → queue → off."""
        if not await self._validate(interaction, require_current_track=False):
            return
        next_mode = {
            wavelink.QueueMode.normal: wavelink.QueueMode.loop,
            wavelink.QueueMode.loop: wavelink.QueueMode.loop_all,
            wavelink.QueueMode.loop_all: wavelink.QueueMode.normal,
        }
        self.player.queue.mode = next_mode.get(self.player.queue.mode, wavelink.QueueMode.normal)
        await self._edit(interaction)

    async def handle_shuffle(self, interaction: discord.Interaction) -> None:
        """Перемешивает оставшуюся очередь."""
        if not await self._validate(interaction, require_current_track=False):
            return
        if len(self.player.queue) < 2:
            await safe_send_error(interaction, "В очереди слишком мало треков для перемешивания.")
            return
        self.player.queue.shuffle()
        await self._edit(interaction)

    async def handle_show_queue(self, interaction: discord.Interaction) -> None:
        """Показывает очередь эфемерным CV2-сообщением."""
        from config import get_settings

        page_size = get_settings().music.lavalink.queue_page_size
        view = QueueLayoutView(self.player, page=1, page_size=page_size)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def on_timeout(self) -> None:
        """По таймауту убираем кнопки, оставив снимок плеера."""
        if self.player.now_playing_message is None:
            return
        try:
            await self.player.now_playing_message.edit(view=now_playing_static_view(self.player))
        except discord.HTTPException:
            pass


class SearchLayoutView(discord.ui.LayoutView):
    """CV2-меню выбора трека из результатов ``/play <текст>`` (одно сообщение)."""

    def __init__(
        self,
        cog: object,
        tracks: list[wavelink.Playable],
        requester: discord.Member,
        query: str,
        *,
        timeout: float = 60.0,
    ) -> None:
        """Собирает контейнер с заголовком поиска и Select-меню результатов."""
        super().__init__(timeout=timeout)
        self._cog = cog
        self._requester = requester
        container: discord.ui.Container = discord.ui.Container(accent_colour=colors.NEUTRAL)
        container.add_item(discord.ui.TextDisplay(f"## 🔍 Результаты поиска: «{query}»"))
        container.add_item(
            discord.ui.TextDisplay(f"Выберите трек из топ-{len(tracks)} результатов:")
        )
        row: discord.ui.ActionRow = discord.ui.ActionRow()
        row.add_item(SearchSelect(tracks, requester.id))
        container.add_item(row)
        self.add_item(container)

    async def handle_selection(
        self, interaction: discord.Interaction, track: wavelink.Playable
    ) -> None:
        """Передаёт выбранный трек в ког для добавления в очередь."""
        handler = getattr(self._cog, "_enqueue_selected_track", None)
        if handler is None:
            await safe_send_error(interaction, "Не удалось обработать выбор: внутренняя ошибка.")
            return
        await handler(interaction, track, self._requester)
        self.stop()


class _QueuePager(discord.ui.ActionRow["QueueLayoutView"]):
    """Ряд пагинации очереди: назад / обновить / вперёд."""

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="music:queue_prev")
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.change_page(interaction, -1)

    @discord.ui.button(
        label="🔄", style=discord.ButtonStyle.secondary, custom_id="music:queue_refresh"
    )
    async def refresh_page(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self.view.change_page(interaction, 0)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="music:queue_next")
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.view.change_page(interaction, 1)


class QueueLayoutView(discord.ui.LayoutView):
    """Очередь воспроизведения с CV2-пагинацией в одном сообщении."""

    def __init__(
        self,
        player: MusicPlayer,
        *,
        page: int = 1,
        page_size: int = 10,
        timeout: float = 120.0,
    ) -> None:
        """Создаёт вью с текущей страницей очереди."""
        super().__init__(timeout=timeout)
        self.player = player
        self.page = page
        self.page_size = page_size
        self._pager = _QueuePager()
        self._render()

    @property
    def _total_pages(self) -> int:
        total = len(self.player.queue)
        return max(1, (total + self.page_size - 1) // self.page_size)

    def _update_buttons(self) -> None:
        """Включает/отключает кнопки prev/next под текущую страницу."""
        total = self._total_pages
        for child in self._pager.children:
            if not isinstance(child, discord.ui.Button):
                continue
            cid = child.custom_id or ""
            if cid == "music:queue_prev":
                child.disabled = self.page <= 1
            elif cid == "music:queue_next":
                child.disabled = self.page >= total

    def _build_container(self) -> discord.ui.Container:
        """Собирает CV2-контейнер для текущей страницы очереди."""
        container: discord.ui.Container = discord.ui.Container(accent_colour=colors.NEUTRAL)
        container.add_item(discord.ui.TextDisplay("## 🎵 Очередь воспроизведения"))

        tracks = list(self.player.queue)
        total = len(tracks)
        start = (self.page - 1) * self.page_size
        chunk = tracks[start : start + self.page_size]

        lines: list[str] = []
        if self.player.current is not None:
            state_emoji = "⏸️" if self.player.paused else "▶️"
            lines.append(
                f"{state_emoji} **Сейчас:** [{self.player.current.title}]"
                f"({self.player.current.uri or 'https://discord.com'}) "
                f"`{format_duration(self.player.current.length)}`"
            )
            lines.append("")
        if not chunk:
            lines.append("_Очередь пуста._")
        else:
            lines.append("**В очереди:**")
            for idx, track in enumerate(chunk, start=start + 1):
                lines.append(
                    f"`{idx}.` [{track.title}]"
                    f"({track.uri or 'https://discord.com'}) "
                    f"`{format_duration(track.length)}`"
                )
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))

        total_ms = sum(int(t.length or 0) for t in tracks)
        if self.player.current and self.player.current.length:
            total_ms += int(self.player.current.length)
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                f"-# Страница {self.page}/{self._total_pages} · "
                f"всего треков: {total + (1 if self.player.current else 0)} · "
                f"общая длительность: {format_duration(total_ms)}"
            )
        )
        return container

    def _render(self) -> None:
        """Пересобирает ``LayoutView`` под текущую страницу."""
        self.clear_items()
        self.page = max(1, min(self.page, self._total_pages))
        container = self._build_container()
        if self._total_pages > 1:
            container.add_item(self._pager)
            self._update_buttons()
        self.add_item(container)

    async def change_page(self, interaction: discord.Interaction, delta: int) -> None:
        """Сдвигает страницу на ``delta`` (``0`` — просто перечитать очередь)."""
        self.page += delta
        self._render()
        await interaction.response.edit_message(view=self)
