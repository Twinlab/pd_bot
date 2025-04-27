import discord
from discord.ext import commands
import logging
import asyncio
from typing import Optional

# Новый импорт музыкального модуля
from utils.music import (
    MusicPlayer,
    Track,
    PlayerControlView,
    SearchView,
    search_youtube,
    create_embed,
    COLORS,
    logger as music_logger
)

cog_logger = logging.getLogger("bot.music.cog")

class MusicCog(commands.Cog, name="Music"):
    """Управляет воспроизведением музыки."""
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.player: MusicPlayer = MusicPlayer(bot)
        cog_logger.info("Музыкальный модуль инициализирован.")

    def cog_unload(self):
        cog_logger.info("Выгрузка музыкального модуля...")
        if self.player and hasattr(self.player, '_cleanup_task') and self.player._cleanup_task:
            self.player._cleanup_task.cancel()
            cog_logger.info("Задача очистки файлов отменена")
        if self.player:
            asyncio.create_task(self.player.disconnect())
        cog_logger.info("Музыкальный модуль выгружен.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        vc = self.player.voice_client
        if not vc or not vc.is_connected():
            return
        if before.channel == vc.channel:
            await asyncio.sleep(1)
            vc = self.player.voice_client
            if not vc or not vc.is_connected():
                return
            human_members = [m for m in vc.channel.members if not m.bot]
            if not human_members:
                cog_logger.info(f"Бот остался один в канале '{vc.channel.name}'. Отключаемся.")
                await self.player.disconnect()

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы использовать эту команду!", ephemeral=True)
            return False
        return True

    async def _connect_or_move(self, interaction: discord.Interaction) -> bool:
        user_channel = interaction.user.voice.channel
        if not await self.player.connect(user_channel):
            await interaction.response.send_message(f"Не удалось подключиться или переместиться в канал '{user_channel.name}'.", ephemeral=True)
            return False
        if not self.player.text_channel and interaction.channel:
            if isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                self.player.text_channel = interaction.channel
                cog_logger.info(f"Текстовый канал плеера установлен: #{interaction.channel.name} ({interaction.channel.id})")
            else:
                cog_logger.warning(f"Канал взаимодействия не является TextChannel или Thread: {type(interaction.channel)}")
        return True

    @discord.app_commands.command(name="play", description="Воспроизвести музыку по ссылке или поисковому запросу.")
    @discord.app_commands.describe(query="Ссылка (YouTube, SoundCloud, etc.) или текст для поиска на YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
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
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.skip(interaction)

    @discord.app_commands.command(name="stop", description="Остановить воспроизведение и покинуть канал.")
    async def stop(self, interaction: discord.Interaction):
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.stop(interaction)

    @discord.app_commands.command(name="pause", description="Приостановить воспроизведение.")
    async def pause(self, interaction: discord.Interaction):
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.pause(interaction)

    @discord.app_commands.command(name="resume", description="Возобновить воспроизведение.")
    async def resume(self, interaction: discord.Interaction):
        if not self.player.voice_client or not interaction.user.voice or interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return
        await self.player.resume(interaction)

    @discord.app_commands.command(name="queue", description="Показать очередь воспроизведения.")
    async def queue(self, interaction: discord.Interaction):
        await self.player.show_queue(interaction)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        cog_logger.error(f"Ошибка в музыкальной команде '{interaction.command.name if interaction.command else 'неизвестно'}': {error}", exc_info=error)
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
            cog_logger.error(f"Не удалось отправить сообщение об ошибке: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
    cog_logger.info("Музыкальный модуль добавлен к боту.")
