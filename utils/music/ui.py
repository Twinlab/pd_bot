"""Discord UI компоненты музыкального плеера.

* :class:`PlayerControlView` — кнопки управления под сообщением "Сейчас играет".
* :class:`SearchView` — Select-меню для выбора трека из результатов поиска ``/play <текст>``.
* :class:`QueueView` — пагинация очереди.

Кнопки и Select-меню используют ``custom_id`` с префиксом ``music:`` — это
позволяет легко идентифицировать их в логах и в будущем сделать persistent
view, если потребуется переживать рестарт бота.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import wavelink

from .config import COLORS, logger
from .embeds import create_embed, format_duration, now_playing_embed, queue_embed

if TYPE_CHECKING:
    from .player import MusicPlayer


# ---------------------------------------------------------------------------
# PlayerControlView
# ---------------------------------------------------------------------------


class PlayerControlView(discord.ui.View):
    """View с кнопками управления плеером под now-playing сообщением.

    Содержит кнопки: ⏯ pause/resume, ⏭ skip, ⏹ stop, 🔁 loop, 🔀 shuffle, 📜 queue.
    Активность кнопок и подпись pause/resume пересчитываются методом
    :meth:`refresh`.
    """

    def __init__(self, player: MusicPlayer, *, timeout: float | None = 3600) -> None:
        """Создаёт view и сразу синхронизирует состояние кнопок с плеером."""
        super().__init__(timeout=timeout)
        self.player: MusicPlayer = player
        self.refresh()

    # -- helpers -----------------------------------------------------------

    def refresh(self) -> None:
        """Обновляет ``disabled`` и подписи кнопок под текущее состояние плеера."""
        has_current = self.player.current is not None
        connected = self.player.connected

        for child in self.children:
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
                mode_labels = {
                    wavelink.QueueMode.normal: ("🔁", "Повтор: выкл"),
                    wavelink.QueueMode.loop: ("🔂", "Повтор: трек"),
                    wavelink.QueueMode.loop_all: ("🔁", "Повтор: очередь"),
                }
                emoji, label = mode_labels.get(self.player.queue.mode, ("🔁", "Повтор: ?"))
                child.emoji = emoji
                child.label = label
            elif cid == "music:shuffle":
                child.disabled = len(self.player.queue) < 2
            elif cid == "music:queue":
                child.disabled = self.player.current is None and len(self.player.queue) == 0

    async def _validate(
        self,
        interaction: discord.Interaction,
        *,
        admin_only: bool = False,
        require_current_track: bool = True,
    ) -> bool:
        """Универсальная проверка перед выполнением действия по кнопке."""
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Эта команда доступна только на сервере.", ephemeral=True
            )
            return False

        vc = self.player.channel
        user_voice = member.voice
        if vc is None or user_voice is None or user_voice.channel != vc:
            await interaction.response.send_message(
                "Вы должны быть в том же голосовом канале, что и бот.",
                ephemeral=True,
            )
            return False

        if require_current_track and self.player.current is None:
            await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)
            return False

        if not self.player.can_control(member, admin_only=admin_only):
            await interaction.response.send_message(
                "Это действие может выполнить только администратор"
                + ("." if admin_only else " или заказчик текущего трека."),
                ephemeral=True,
            )
            return False
        return True

    async def _refresh_message(self, interaction: discord.Interaction) -> None:
        """Перерисовывает now-playing сообщение под актуальное состояние."""
        self.refresh()
        try:
            await interaction.response.edit_message(embed=now_playing_embed(self.player), view=self)
        except discord.InteractionResponded:
            # Если на взаимодействие уже ответили — редактируем через followup.
            if self.player.now_playing_message is not None:
                try:
                    await self.player.now_playing_message.edit(
                        embed=now_playing_embed(self.player), view=self
                    )
                except discord.HTTPException:
                    logger.debug("Не удалось обновить now-playing сообщение.")

    # -- buttons -----------------------------------------------------------

    @discord.ui.button(
        label="Пауза",
        emoji="⏸️",
        style=discord.ButtonStyle.secondary,
        custom_id="music:pause_resume",
        row=0,
    )
    async def pause_resume(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        """Пауза / возобновление воспроизведения."""
        if not await self._validate(interaction):
            return
        await self.player.pause(not self.player.paused)
        await self._refresh_message(interaction)

    @discord.ui.button(
        label="Скип",
        emoji="⏭️",
        style=discord.ButtonStyle.primary,
        custom_id="music:skip",
        row=0,
    )
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Пропуск текущего трека."""
        if not await self._validate(interaction):
            return
        await self.player.skip(force=True)
        # После skip wavelink инициирует следующий трек, наш track_start event
        # обновит сообщение. Здесь просто подтверждаем нажатие.
        await interaction.response.defer()

    @discord.ui.button(
        label="Стоп",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="music:stop",
        row=0,
    )
    async def stop_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        """Полная остановка: очистка очереди и отключение."""
        if not await self._validate(interaction, admin_only=True, require_current_track=False):
            return
        self.player.queue.clear()
        await self.player.disconnect()
        try:
            await interaction.response.edit_message(
                content=None,
                embed=create_embed(
                    "⏹️ Воспроизведение остановлено",
                    "Бот покинул голосовой канал, очередь очищена.",
                    COLORS["INFO"],
                ),
                view=None,
            )
        except discord.HTTPException:
            pass
        self.stop()

    @discord.ui.button(
        label="Повтор: выкл",
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        custom_id="music:loop",
        row=1,
    )
    async def loop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Циклит режим повтора: off → track → queue → off."""
        if not await self._validate(interaction, require_current_track=False):
            return
        next_mode = {
            wavelink.QueueMode.normal: wavelink.QueueMode.loop,
            wavelink.QueueMode.loop: wavelink.QueueMode.loop_all,
            wavelink.QueueMode.loop_all: wavelink.QueueMode.normal,
        }
        self.player.queue.mode = next_mode.get(self.player.queue.mode, wavelink.QueueMode.normal)
        await self._refresh_message(interaction)

    @discord.ui.button(
        label="Перемешать",
        emoji="🔀",
        style=discord.ButtonStyle.secondary,
        custom_id="music:shuffle",
        row=1,
    )
    async def shuffle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Перемешивает оставшуюся очередь."""
        if not await self._validate(interaction, require_current_track=False):
            return
        if len(self.player.queue) < 2:
            await interaction.response.send_message(
                "В очереди слишком мало треков для перемешивания.", ephemeral=True
            )
            return
        self.player.queue.shuffle()
        await self._refresh_message(interaction)

    @discord.ui.button(
        label="Очередь",
        emoji="📜",
        style=discord.ButtonStyle.blurple,
        custom_id="music:queue",
        row=1,
    )
    async def show_queue(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        """Показывает текущую очередь (эфемерным сообщением)."""
        # Размер страницы берём из настроек.
        from config import get_settings

        page_size = get_settings().music.lavalink.queue_page_size
        embed = queue_embed(self.player, page=1, page_size=page_size)
        view = QueueView(self.player, page=1, page_size=page_size)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_timeout(self) -> None:  # type: ignore[override]
        """По таймауту убираем view с сообщения (если оно ещё живо)."""
        if self.player.now_playing_message is None:
            return
        try:
            await self.player.now_playing_message.edit(view=None)
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------------------
# SearchView
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
        view = self.view
        if isinstance(view, SearchView):
            await view.handle_selection(interaction, self._tracks[int(self.values[0])])


class SearchView(discord.ui.View):
    """View, оборачивающий :class:`SearchSelect` для выбора трека."""

    def __init__(
        self,
        cog: object,
        tracks: list[wavelink.Playable],
        requester: discord.Member,
        *,
        timeout: float = 60.0,
    ) -> None:
        """Сохраняет ссылку на ког, чтобы вызвать его метод добавления трека."""
        super().__init__(timeout=timeout)
        self._cog = cog
        self._requester = requester
        self.add_item(SearchSelect(tracks, requester.id))

    async def handle_selection(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
    ) -> None:
        """Передаёт выбранный трек в ког для добавления в очередь."""
        handler = getattr(self._cog, "_enqueue_selected_track", None)
        if handler is None:
            await interaction.response.send_message(
                "Не удалось обработать выбор: внутренняя ошибка.", ephemeral=True
            )
            return
        await handler(interaction, track, self._requester)
        self.stop()


# ---------------------------------------------------------------------------
# QueueView (pagination)
# ---------------------------------------------------------------------------


class QueueView(discord.ui.View):
    """Пагинация эмбеда очереди — кнопки prev/next."""

    def __init__(
        self,
        player: MusicPlayer,
        *,
        page: int = 1,
        page_size: int = 10,
        timeout: float = 120.0,
    ) -> None:
        """Создаёт view с текущей страницей."""
        super().__init__(timeout=timeout)
        self.player = player
        self.page = page
        self.page_size = page_size
        self._refresh_buttons()

    @property
    def _total_pages(self) -> int:
        total = len(self.player.queue)
        return max(1, (total + self.page_size - 1) // self.page_size)

    def _refresh_buttons(self) -> None:
        """Включает/отключает кнопки prev/next в зависимости от страницы."""
        total = self._total_pages
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            cid = child.custom_id or ""
            if cid == "music:queue_prev":
                child.disabled = self.page <= 1
            elif cid == "music:queue_next":
                child.disabled = self.page >= total
            elif cid == "music:queue_refresh":
                child.disabled = False

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="music:queue_prev")
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Предыдущая страница очереди."""
        self.page = max(1, self.page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=queue_embed(self.player, page=self.page, page_size=self.page_size),
            view=self,
        )

    @discord.ui.button(
        label="🔄", style=discord.ButtonStyle.secondary, custom_id="music:queue_refresh"
    )
    async def refresh_page(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        """Обновить текущую страницу (если очередь изменилась)."""
        self.page = min(self.page, self._total_pages)
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=queue_embed(self.player, page=self.page, page_size=self.page_size),
            view=self,
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="music:queue_next")
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        """Следующая страница очереди."""
        self.page = min(self._total_pages, self.page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(
            embed=queue_embed(self.player, page=self.page, page_size=self.page_size),
            view=self,
        )
