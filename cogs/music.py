"""Ког для управления воспроизведением музыки в Discord."""
import discord
from discord.ext import commands
import asyncio
from typing import Optional

from utils.music import (
    MusicPlayer,
    # Track, # Track не используется напрямую в этом файле, только в MusicPlayer
    PlayerControlView,
    SearchView,
    search_youtube,
    create_embed,
    COLORS,
    logger as music_logger
)

class MusicCog(commands.Cog, name="Music"):
    """
    Управляет воспроизведением музыки.
    Предоставляет команды для поиска, добавления в очередь, воспроизведения и управления треками.
    """
    def __init__(self, bot: commands.Bot):
        """
        Инициализирует музыкальный ког.

        Args:
            bot: Экземпляр discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        self.player: MusicPlayer = MusicPlayer(bot)
        music_logger.info("Музыкальный модуль инициализирован.")

    def cog_unload(self):
        """
        Вызывается при выгрузке кога.
        Отменяет задачу очистки файлов и отключает плеер.
        """
        music_logger.info("Выгрузка музыкального модуля...")
        if self.player and hasattr(self.player, '_cleanup_task') and self.player._cleanup_task:
            self.player._cleanup_task.cancel()
            music_logger.info("Задача очистки файлов отменена")
        if self.player:
            # Используем asyncio.create_task для асинхронного отключения,
            # чтобы не блокировать процесс выгрузки кога.
            asyncio.create_task(self.player.disconnect())
        music_logger.info("Музыкальный модуль выгружен.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Событие, отслеживающее изменения состояния голосового канала участников.
        Если бот остается один в голосовом канале, он автоматически отключается.

        Args:
            member: Участник, чье состояние изменилось.
            before: Состояние голосового канала до изменения.
            after: Состояние голосового канала после изменения.
        """
        if member.bot: # Игнорируем изменения состояния других ботов
            return

        vc = self.player.voice_client
        if not vc or not vc.is_connected(): # Если бот не в голосовом канале, ничего не делаем
            return

        # Проверяем, был ли участник в том же канале, что и бот, и вышел ли он,
        # или если бот остался один после того, как кто-то вышел из его канала.
        # Условие before.channel == vc.channel означает, что событие связано с каналом бота.
        if before.channel == vc.channel and after.channel != vc.channel or \
           (before.channel == vc.channel and after.channel == vc.channel and len(vc.channel.members) == 1 and vc.channel.members[0] == self.bot.user):
            # Небольшая задержка, чтобы убедиться, что состояние канала стабилизировалось
            # await asyncio.sleep(1) # Удалено, т.к. может быть излишним и приводить к задержкам.
                                     # Если будут проблемы с преждевременным выходом, можно вернуть с комментарием.
            
            # Повторно получаем voice_client, так как он мог измениться
            current_vc = self.player.voice_client
            if not current_vc or not current_vc.is_connected():
                return

            # Проверяем количество "живых" пользователей в текущем канале бота
            human_members = [m for m in current_vc.channel.members if not m.bot]
            if not human_members:
                music_logger.info(f"Бот остался один в канале '{current_vc.channel.name}'. Отключаемся.")
                await self.player.disconnect()

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """
        Проверяет, находится ли пользователь, вызвавший команду, в голосовом канале.

        Args:
            interaction: Взаимодействие, инициировавшее команду.

        Returns:
            True, если пользователь в голосовом канале, иначе False.
        """
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            message = "Вы должны быть в голосовом канале, чтобы использовать эту команду!"
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    async def _connect_or_move(self, interaction: discord.Interaction) -> bool:
        """
        Подключает бота к голосовому каналу пользователя или перемещает его,
        если он уже подключен к другому каналу. Также устанавливает текстовый канал для плеера.

        Args:
            interaction: Взаимодействие, инициировавшее команду.

        Returns:
            True, если подключение/перемещение успешно, иначе False.
        """
        if not interaction.user.voice or not interaction.user.voice.channel: # Дополнительная проверка
            # _ensure_voice должен был это покрыть, но для надежности
            await interaction.response.send_message("Не удалось определить ваш голосовой канал.", ephemeral=True)
            return False
            
        user_channel = interaction.user.voice.channel
        if not await self.player.connect(user_channel):
            await interaction.response.send_message(f"Не удалось подключиться или переместиться в канал '{user_channel.name}'.", ephemeral=True)
            return False
        
        # Устанавливаем текстовый канал для сообщений плеера, если он еще не установлен
        if not self.player.text_channel and interaction.channel:
            if isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                self.player.text_channel = interaction.channel
                music_logger.info(f"Текстовый канал плеера установлен: #{interaction.channel.name} ({interaction.channel.id})")
            else:
                # Логируем, если канал не текстовый, но не прерываем операцию
                music_logger.warning(f"Канал взаимодействия '{interaction.channel.name}' (тип: {type(interaction.channel)}) не является TextChannel или Thread. Сообщения плеера могут не отображаться.")
        return True

    @discord.app_commands.command(name="play", description="Воспроизвести музыку по ссылке или поисковому запросу.")
    @discord.app_commands.describe(query="Ссылка (YouTube, SoundCloud, etc.) или текст для поиска на YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        """
        Воспроизводит музыку по URL-ссылке или выполняет поиск на YouTube по текстовому запросу.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
            query: URL-ссылка на трек или поисковый запрос для YouTube.
        """
        await interaction.response.defer(thinking=True, ephemeral=False)
        if not await self._ensure_voice(interaction):
            await interaction.edit_original_response(content="Вы должны быть в голосовом канале!")
            return
        if not await self._connect_or_move(interaction):
            await interaction.edit_original_response(content="Не удалось подключиться к голосовому каналу.")
            return
        if query.startswith(('http://', 'https://')):
            await interaction.edit_original_response(content=f"🔗 Добавляем трек по ссылке...")
            await self.player.queue_track(query, interaction.user, interaction)
        else:
            await interaction.edit_original_response(content=f"🔍 Ищем '{query}' на YouTube...")
            search_results = await search_youtube(query)
            if not search_results:
                await interaction.edit_original_response(content=None, embed=create_embed("❌ Поиск не дал результатов", f"Не найдено треков по запросу: `{query}`", COLORS['ERROR']))
                return
            search_view = SearchView(self.player, interaction, search_results)
            embed = create_embed(f"🔍 Результаты поиска для '{query}'", "Выберите трек из списка ниже:")
            await interaction.edit_original_response(content=None, embed=embed, view=search_view)

    @discord.app_commands.command(name="skip", description="Пропустить текущий трек.")
    async def skip(self, interaction: discord.Interaction):
        """
        Пропускает текущий воспроизводимый трек и запускает следующий из очереди, если он есть.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not self.player.voice_client or not interaction.user.voice or \
           (self.player.voice_client and interaction.user.voice.channel != self.player.voice_client.channel):
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.skip(interaction)

    @discord.app_commands.command(name="stop", description="Остановить воспроизведение и покинуть канал.")
    async def stop(self, interaction: discord.Interaction):
        """
        Останавливает воспроизведение музыки, очищает очередь и отключает бота от голосового канала.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.stop(interaction)

    @discord.app_commands.command(name="pause", description="Приостановить воспроизведение.")
    async def pause(self, interaction: discord.Interaction):
        """
        Приостанавливает воспроизведение текущего трека.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.pause(interaction)

    @discord.app_commands.command(name="resume", description="Возобновить воспроизведение.")
    async def resume(self, interaction: discord.Interaction):
        """
        Возобновляет воспроизведение приостановленного трека.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.resume(interaction)

    @discord.app_commands.command(name="queue", description="Показать очередь воспроизведения.")
    async def queue(self, interaction: discord.Interaction):
        """
        Показывает текущую очередь воспроизведения, включая играющий трек.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        await self.player.show_queue(interaction)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        """
        Обрабатывает ошибки, возникающие при выполнении команд приложения в этом коге.

        Args:
            interaction: Взаимодействие, где произошла ошибка.
            error: Объект ошибки.
        """
        music_logger.error(f"Ошибка в музыкальной команде '{interaction.command.name if interaction.command else 'неизвестно'}': {error}", exc_info=error)
        error_message = f"Произошла ошибка при выполнении команды: `{error}`"
        if isinstance(error, discord.app_commands.CheckFailure):
            error_message = "У вас нет прав для выполнения этой команды."
        elif isinstance(error, discord.app_commands.CommandInvokeError):
            original = error.original
            if isinstance(original, asyncio.TimeoutError):
                error_message = "Превышено время ожидания ответа от сервера. Пожалуйста, попробуйте еще раз."
            elif "Cannot connect to host" in str(original):
                error_message = "Не удалось подключиться к серверу YouTube. Проверьте ваше интернет-соединение."
            elif "HTTP Error 403" in str(original):
                error_message = "Доступ к ресурсу запрещен. Возможно, видео недоступно в вашем регионе."
            elif "HTTP Error 404" in str(original):
                error_message = "Ресурс не найден. Возможно, видео было удалено."
            else:
                error_message = f"Произошла внутренняя ошибка: `{original}`"
        elif isinstance(error, discord.app_commands.CommandNotFound):
            error_message = "Команда не найдена. Используйте /help для просмотра доступных команд."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            error_message = "У бота недостаточно прав для выполнения этой команды."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
        except Exception as e:
            music_logger.error(f"Не удалось отправить сообщение об ошибке: {e}")

async def setup(bot: commands.Bot):
    """
    Добавляет MusicCog к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(MusicCog(bot))
    music_logger.info("Музыкальный модуль (MusicCog) добавлен к боту.")
