import discord
from discord.ext import commands, tasks # Убедимся, что commands импортирован
import logging
import asyncio
from typing import Optional

# Импортируем новый плеер и утилиты
from utils.music_utils import (
    MusicPlayer,
    Track,
    SearchView,
    search_youtube,
    create_embed,
    COLORS,
    logger as music_logger # Используем логгер из модуля
)
# Импортируем обработчик ошибок (если он еще используется)
# from utils.error_handler import command_error_handler # Пока не используем, добавим позже если нужно

# --- Настройка логирования для кога ---
cog_logger = logging.getLogger("cog.music")
cog_logger.setLevel(logging.INFO)
# Добавляем handler если еще не настроен глобально
if not cog_logger.handlers and not music_logger.handlers:
     handler = logging.StreamHandler()
     formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
     handler.setFormatter(formatter)
     cog_logger.addHandler(handler)
     # Можно добавить и в music_logger, если он тоже не имеет handler'а
     # music_logger.addHandler(handler)


# --- Класс Кога Музыки ---

class MusicCog(commands.Cog, name="Music"):
    """Управляет воспроизведением музыки."""

    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        # Создаем единственный экземпляр плеера, т.к. бот на одном сервере
        self.player: MusicPlayer = MusicPlayer(bot)
        cog_logger.info("Music Cog initialized.")
        # Запускаем фоновую задачу для автоотключения (опционально)
        # self.auto_disconnect_task.start()

    def cog_unload(self):
        """Вызывается при выгрузке кога."""
        cog_logger.info("Unloading Music Cog...")
        # Останавливаем фоновую задачу, если она есть
        # self.auto_disconnect_task.cancel()
        # Очищаем плеер асинхронно
        # Важно: cog_unload - синхронная функция, поэтому используем create_task
        if self.player:
            asyncio.create_task(self.player.disconnect())
        cog_logger.info("Music Cog unloaded.")

    # --- Обработчики событий ---

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Отслеживает изменения в голосовых каналах для автоотключения."""
        if member.bot: # Игнорируем других ботов и самого себя
            return

        vc = self.player.voice_client
        if not vc or not vc.is_connected():
            return # Бот не в голосовом канале

        # Проверяем канал, из которого вышел пользователь
        if before.channel == vc.channel:
            # Считаем, сколько реальных пользователей осталось в канале бота
            # Добавляем небольшую задержку, чтобы Discord успел обновить состояние
            await asyncio.sleep(1)
            # Перепроверяем voice_client на случай, если бот отключился за эту секунду
            vc = self.player.voice_client
            if not vc or not vc.is_connected(): return

            human_members = [m for m in vc.channel.members if not m.bot]
            if not human_members:
                cog_logger.info(f"Bot is alone in '{vc.channel.name}'. Disconnecting.")
                await self.player.disconnect() # Вызываем метод плеера для отключения и очистки

    # --- Вспомогательные методы ---

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """Проверяет, находится ли пользователь в голосовом канале."""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы использовать эту команду!", ephemeral=True)
            return False
        return True

    async def _connect_or_move(self, interaction: discord.Interaction) -> bool:
        """Подключает или перемещает бота в канал пользователя."""
        user_channel = interaction.user.voice.channel
        if not await self.player.connect(user_channel):
            await interaction.response.send_message(f"Не удалось подключиться или переместиться в канал '{user_channel.name}'.", ephemeral=True)
            return False
        # Устанавливаем текстовый канал для сообщений плеера, если еще не установлен
        if not self.player.text_channel and interaction.channel:
             # Проверяем тип канала (TextChannel или Thread)
             if isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                 self.player.text_channel = interaction.channel
                 cog_logger.info(f"Player text channel set to: #{interaction.channel.name} ({interaction.channel.id})")
             else:
                  cog_logger.warning(f"Interaction channel is not a TextChannel or Thread: {type(interaction.channel)}")
        return True

    # --- Команды ---

    @discord.app_commands.command(name="play", description="Воспроизвести музыку по ссылке или поисковому запросу.")
    @discord.app_commands.describe(query="Ссылка (YouTube, SoundCloud, etc.) или текст для поиска на YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        """Воспроизводит музыку или добавляет в очередь."""
        await interaction.response.defer(thinking=True, ephemeral=False) # Отвечаем сразу, что команда принята

        if not await self._ensure_voice(interaction):
            # Сообщение об ошибке уже отправлено в _ensure_voice
            # Нужно отредактировать defer-ответ
            await interaction.edit_original_response(content="Вы должны быть в голосовом канале!")
            return

        if not await self._connect_or_move(interaction):
             # Сообщение об ошибке уже отправлено в _connect_or_move
             await interaction.edit_original_response(content="Не удалось подключиться к голосовому каналу.")
             return

        # Определяем, ссылка это или поисковый запрос
        if query.startswith(('http://', 'https://')):
            # Это ссылка, сразу добавляем в очередь
            await interaction.edit_original_response(content=f"🔗 Добавляем трек по ссылке...")
            # queue_track сама отправит сообщение о результате/ошибке
            await self.player.queue_track(query, interaction.user, interaction)
        else:
            # Это поисковый запрос
            await interaction.edit_original_response(content=f"🔍 Ищем '{query}' на YouTube...")
            search_results = await search_youtube(query)

            if not search_results:
                await interaction.edit_original_response(content=None, embed=create_embed("❌ Поиск не дал результатов", f"Не найдено треков по запросу: `{query}`", COLORS['ERROR']))
                return

            # Показываем результаты с помощью View
            search_view = SearchView(self.player, interaction, search_results)
            embed = create_embed(f"🔍 Результаты поиска для '{query}'", "Выберите трек из списка ниже:")
            await interaction.edit_original_response(content=None, embed=embed, view=search_view)


    @discord.app_commands.command(name="skip", description="Пропустить текущий трек.")
    async def skip(self, interaction: discord.Interaction):
        """Пропускает текущий трек."""
        # Проверка канала не нужна здесь, т.к. skip вызывается из View, которая уже проверила
        # Но если делать как slash-команду, проверка нужна:
        # if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
        #     await interaction.response.send_message("Вы должны быть в том же канале, что и бот!", ephemeral=True)
        #     return

        # skip сама отправит ответ через interaction
        await self.player.skip(interaction)

    @discord.app_commands.command(name="stop", description="Остановить воспроизведение и покинуть канал.")
    async def stop(self, interaction: discord.Interaction):
        """Останавливает плеер и отключает бота."""
        # Проверка канала не нужна здесь, т.к. stop вызывается из View
        # Но если делать как slash-команду, проверка нужна.

        # stop сама отправит ответ через interaction
        await self.player.stop(interaction)

    @discord.app_commands.command(name="pause", description="Приостановить воспроизведение.")
    async def pause(self, interaction: discord.Interaction):
        """Ставит текущий трек на паузу."""
        # Проверка канала не нужна здесь, т.к. pause вызывается из View
        await self.player.pause(interaction)

    @discord.app_commands.command(name="resume", description="Возобновить воспроизведение.")
    async def resume(self, interaction: discord.Interaction):
        """Возобновляет воспроизведение после паузы."""
        # Проверка канала не нужна здесь, т.к. resume вызывается из View
        await self.player.resume(interaction)

    @discord.app_commands.command(name="queue", description="Показать очередь воспроизведения.")
    async def queue(self, interaction: discord.Interaction):
        """Показывает текущий трек и очередь."""
        # Голосовой канал не важен для просмотра очереди
        await self.player.show_queue(interaction)

    @discord.app_commands.command(name="volume", description="Установить громкость воспроизведения (0-200%).")
    @discord.app_commands.describe(level="Уровень громкости от 0 до 200")
    async def volume(self, interaction: discord.Interaction, level: discord.app_commands.Range[int, 0, 200]):
        """Устанавливает громкость плеера."""
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
             await interaction.response.send_message("Вы должны быть в том же канале, что и бот, чтобы менять громкость!", ephemeral=True)
             return

        volume_float = float(level) / 100.0
        await self.player.set_volume(volume_float, interaction)

    # --- Глобальный обработчик ошибок для команд кога (пример) ---
    # @commands.Cog.listener()
    # async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
    #      # Обработка ошибок, специфичных для этого кога
    #      if isinstance(error, commands.CheckFailure):
    #          await ctx.send("У вас нет прав для этой команды.", ephemeral=True)
    #      elif isinstance(error, commands.MissingRequiredArgument):
    #           await ctx.send(f"Не хватает аргумента: {error.param.name}", ephemeral=True)
    #      else:
    #           cog_logger.error(f"Unhandled command error in Music Cog: {error}", exc_info=error)
    #           await ctx.send(f"Произошла ошибка: {error}", ephemeral=True)

    # Обработчик ошибок для slash-команд
    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
         cog_logger.error(f"Error in Music Cog slash command '{interaction.command.name if interaction.command else 'unknown'}': {error}", exc_info=error)
         error_message = f"Произошла ошибка при выполнении команды: `{error}`"
         if isinstance(error, discord.app_commands.CheckFailure):
              error_message = "У вас нет прав для выполнения этой команды."
         elif isinstance(error, discord.app_commands.CommandInvokeError):
              # Показываем исходную ошибку, если она есть
              error_message = f"Произошла внутренняя ошибка: `{error.original}`"

         if interaction.response.is_done():
              await interaction.followup.send(error_message, ephemeral=True)
         else:
              await interaction.response.send_message(error_message, ephemeral=True)


# --- Функция setup для загрузки кога ---
async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
    cog_logger.info("Music Cog added to bot.")
