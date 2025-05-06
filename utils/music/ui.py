"""Модуль, содержащий классы для элементов пользовательского интерфейса музыкального плеера (кнопки, выборы)."""
import discord
from typing import List, Dict, Optional, TYPE_CHECKING

# Локальный импорт для избежания циклических зависимостей при проверке типов
if TYPE_CHECKING:
    from .player import MusicPlayer # pragma: no cover

from .embeds import format_duration # create_embed не используется в этом файле
from .config import logger # Импортируем логгер

class PlayerControlView(discord.ui.View):
    """
    View с кнопками управления музыкальным плеером (пауза/продолжить, пропустить, стоп, очередь).
    Автоматически обновляет состояние кнопок и удаляется по таймауту.
    """
    def __init__(self, player: 'MusicPlayer', timeout: Optional[float] = 600):
        """
        Инициализирует View для управления плеером.

        Args:
            player: Экземпляр MusicPlayer, которым будет управлять эта View.
            timeout: Время в секундах, после которого View станет неактивной.
        """
        super().__init__(timeout=timeout)
        self.player: 'MusicPlayer' = player
        self._update_buttons()

    def _update_buttons(self):
        """Обновляет состояние кнопок (активность, метки) в зависимости от текущего состояния плеера."""
        vc = self.player.voice_client
        can_control = vc is not None and self.player.current_track is not None
        pause_resume_button = discord.utils.get(self.children, custom_id="music:pause_resume")
        if pause_resume_button:
            pause_resume_button.disabled = not can_control
            if self.player.is_paused:
                pause_resume_button.label = "▶️ Продолжить"
                pause_resume_button.style = discord.ButtonStyle.green
            else:
                pause_resume_button.label = "⏸️ Пауза"
                pause_resume_button.style = discord.ButtonStyle.secondary
        skip_button = discord.utils.get(self.children, custom_id="music:skip")
        if skip_button:
            skip_button.disabled = not can_control
        stop_button = discord.utils.get(self.children, custom_id="music:stop")
        if stop_button:
            stop_button.disabled = vc is None
        queue_button = discord.utils.get(self.children, custom_id="music:queue")
        if queue_button:
            queue_button.disabled = False

    async def _check_voice_channel(self, interaction: discord.Interaction) -> bool:
        """
        Проверяет, находится ли пользователь, вызвавший взаимодействие, в голосовом канале
        и, если бот уже в канале, то в том же самом.

        Args:
            interaction: Взаимодействие от пользователя.

        Returns:
            True, если проверки пройдены, иначе False (и отправляет сообщение пользователю).
        """
        if not isinstance(interaction.user, discord.Member): # Должно быть всегда True для кнопок на сервере
            logger.warning("_check_voice_channel: interaction.user не является discord.Member.")
            return False
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы управлять плеером!", ephemeral=True)
            return False
        if self.player.voice_client and self.player.voice_client.channel and \
           interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот, для управления плеером!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary, custom_id="music:pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Обработчик кнопки "Пауза/Продолжить".
        Приостанавливает или возобновляет воспроизведение.

        Args:
            interaction: Взаимодействие от нажатия кнопки.
            button: Экземпляр кнопки, которая была нажата.
        """
        if not await self._check_voice_channel(interaction):
            return
        if self.player.is_paused:
            await self.player.resume(interaction)
        else:
            await self.player.pause(interaction)
        self._update_buttons()
        if not interaction.response.is_done():
            await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.primary, custom_id="music:skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Обработчик кнопки "Пропустить".
        Пропускает текущий трек.

        Args:
            interaction: Взаимодействие от нажатия кнопки.
            button: Экземпляр кнопки, которая была нажата.
        """
        if not await self._check_voice_channel(interaction):
            return
        await self.player.skip(interaction)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Обработчик кнопки "Стоп".
        Останавливает воспроизведение и отключает бота.

        Args:
            interaction: Взаимодействие от нажатия кнопки.
            button: Экземпляр кнопки, которая была нажата.
        """
        if not await self._check_voice_channel(interaction):
            return
        await self.player.stop(interaction)

    @discord.ui.button(label="📜 Очередь", style=discord.ButtonStyle.blurple, custom_id="music:queue", row=0)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Обработчик кнопки "Очередь".
        Показывает текущую очередь воспроизведения.

        Args:
            interaction: Взаимодействие от нажатия кнопки.
            button: Экземпляр кнопки, которая была нажата.
        """
        await self.player.show_queue(interaction)
        # Ответ уже должен быть отправлен внутри show_queue,
        # но если он там deferred, то здесь ничего делать не нужно.
        # Если show_queue не отвечает, то нужно interaction.response.defer() или send_message.
        # Текущая реализация show_queue в MusicPlayer уже отправляет ответ.

    async def on_timeout(self):
        """Вызывается при истечении времени ожидания View. Удаляет кнопки из сообщения."""
        logger.debug(f"PlayerControlView для сообщения {self.player.now_playing_message.id if self.player.now_playing_message else 'Неизвестно'} истек.")
        if self.player.now_playing_message:
            try:
                await self.player.now_playing_message.edit(view=None)
                logger.debug(f"Кнопки удалены из сообщения {self.player.now_playing_message.id} по таймауту.")
            except discord.NotFound:
                logger.warning(f"Сообщение {self.player.now_playing_message.id} не найдено при попытке удалить View по таймауту.")
            except discord.HTTPException as e:
                logger.error(f"Ошибка HTTP при удалении View по таймауту для сообщения {self.player.now_playing_message.id}: {e}")
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при удалении View по таймауту для {self.player.now_playing_message.id}: {e}", exc_info=True)
        super().stop() # Важно вызвать для внутренней очистки View

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Проверка перед выполнением колбэка элемента View.
        В данном случае всегда возвращает True, разрешая любое взаимодействие.
        Может быть переопределена для более сложных проверок (например, прав пользователя).
        """
        return True

class SearchResultSelect(discord.ui.Select):
    """Выпадающий список для выбора одного трека из результатов поиска YouTube."""
    def __init__(self, player: 'MusicPlayer', interaction: discord.Interaction, entries: List[Dict]):
        """
        Инициализирует выпадающий список результатов поиска.

        Args:
            player: Экземпляр MusicPlayer.
            interaction: Исходное взаимодействие, инициировавшее поиск.
            entries: Список словарей с результатами поиска от yt-dlp.
        """
        self.player: 'MusicPlayer' = player
        self.original_interaction: discord.Interaction = interaction # Сохраняем для использования в callback
        self.entries: List[Dict] = entries
        options: List[discord.SelectOption] = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            label = entry.get('title', f'Неизвестное название {i+1}')
            if len(label) > 100:
                label = label[:97] + "..."
            desc = f"Автор: {entry.get('uploader', 'Н/Д')} | {format_duration(entry.get('duration'))}"
            if len(desc) > 100:
                desc = desc[:97] + "..."
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))
        if not options:
            options.append(discord.SelectOption(label="Ничего не найдено", value="-1", description="Попробуйте другой запрос"))
        super().__init__(placeholder="Выберите трек для добавления...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        """
        Обрабатывает выбор пользователя из выпадающего списка.
        Добавляет выбранный трек в очередь плеера.

        Args:
            interaction: Взаимодействие от выбора элемента.
        """
        selected_index = int(self.values[0])

        # Пытаемся удалить исходное сообщение с результатами поиска (где был этот Select)
        # Это делается для чистоты интерфейса, чтобы не оставалось старых сообщений.
        if interaction.message:
            try:
                await interaction.message.delete()
                logger.debug(f"Сообщение с результатами поиска (ID: {interaction.message.id}) удалено.")
            except discord.NotFound:
                logger.warning(f"Не удалось удалить сообщение с результатами поиска (ID: {interaction.message.id if interaction.message else 'None'}): Не найдено.")
            except discord.HTTPException as e:
                logger.error(f"Ошибка HTTP при удалении сообщения с результатами поиска (ID: {interaction.message.id if interaction.message else 'None'}): {e}")
            except Exception as e: # Ловим другие возможные ошибки
                logger.error(f"Непредвиденная ошибка при удалении сообщения с результатами поиска (ID: {interaction.message.id if interaction.message else 'None'}): {e}", exc_info=True)
        
        if selected_index == -1: # Опция "Ничего не найдено" или отмена
            # Отправляем эфемерный ответ, так как исходное сообщение удалено
            await interaction.response.send_message("Поиск отменен или ничего не выбрано.", ephemeral=True, delete_after=10)
            return
        if not (0 <= selected_index < len(self.entries)):
            await interaction.response.send_message("Неверный выбор.", ephemeral=True, delete_after=10)
            return
        selected_entry = self.entries[selected_index]
        url = selected_entry.get('webpage_url', selected_entry.get('original_url', selected_entry.get('url')))
        if not url:
            await interaction.response.send_message("❌ Ошибка: Не удалось получить URL для выбранного трека.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы добавить трек!", ephemeral=True)
            return
        connected = await self.player.connect(interaction.user.voice.channel)
        if not connected:
            await interaction.response.send_message("Не удалось подключиться к вашему голосовому каналу.", ephemeral=True)
            return
        requester = self.original_interaction.user
        await interaction.response.send_message(f"⏳ Добавляем '{selected_entry.get('title', 'выбранный трек')}'...", ephemeral=True)
        await self.player.queue_track(url, requester, interaction)

class SearchView(discord.ui.View):
    """View, содержащая выпадающий список SearchResultSelect для выбора трека из результатов поиска."""
    def __init__(self, player: 'MusicPlayer', interaction: discord.Interaction, entries: List[Dict], timeout: float = 60.0):
        """
        Инициализирует View для отображения результатов поиска.

        Args:
            player: Экземпляр MusicPlayer.
            interaction: Исходное взаимодействие, инициировавшее поиск.
            entries: Список результатов поиска.
            timeout: Время в секундах, после которого View станет неактивной.
        """
        super().__init__(timeout=timeout)
        self.player: 'MusicPlayer' = player
        self.original_interaction: discord.Interaction = interaction
        self.add_item(SearchResultSelect(player, self.original_interaction, entries)) # Передаем original_interaction

    async def on_timeout(self):
        """Вызывается при истечении времени ожидания View. Редактирует исходное сообщение о поиске."""
        logger.debug(f"SearchView для взаимодействия {self.original_interaction.id} истек.")
        try:
            # Пытаемся отредактировать исходное сообщение, чтобы убрать View и показать сообщение о таймауте
            await self.original_interaction.edit_original_response(
                content="⏱️ Время выбора трека истекло. Пожалуйста, выполните поиск снова, если это необходимо.",
                view=None,
                embed=None
            )
            logger.debug(f"Сообщение о поиске (взаимодействие {self.original_interaction.id}) отредактировано по таймауту.")
        except discord.NotFound:
            logger.warning(f"Исходное сообщение для SearchView (взаимодействие {self.original_interaction.id}) не найдено при таймауте.")
        except discord.HTTPException as e:
            logger.error(f"Ошибка HTTP при редактировании сообщения SearchView по таймауту (взаимодействие {self.original_interaction.id}): {e}")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обработке таймаута SearchView для {self.original_interaction.id}: {e}", exc_info=True)
        self.stop() # Важно вызвать для внутренней очистки View

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Проверяет, что взаимодействие с этим View (выбор из списка) исходит от того же пользователя,
        который изначально инициировал поиск.
        """
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Только пользователь, запустивший поиск, может выбрать трек.", ephemeral=True)
            return False
        return True
