"""Ког для управления воспроизведением музыки V2."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.music_v2.errors import MusicError, UserNotInVoiceChannel
from utils.music_v2.player import MusicPlayer
from utils.music_v2.track import Track
from utils.music_v2.youtube import get_track_info

logger = logging.getLogger("bot.cogs.music_v2")


class MusicV2Cog(commands.Cog, name="MusicV2"):  # type: ignore
    """Управляет воспроизведением музыки (V2)."""

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует музыкальный ког V2.

        Args:
            bot: Экземпляр discord.ext.commands.Bot.
        """
        self.bot = bot
        # Поскольку бот на одном сервере, мы можем использовать один плеер
        self.player: MusicPlayer | None = None

    def _get_player(self, guild: discord.Guild) -> MusicPlayer:
        """Получает или создает экземпляр плеера для сервера."""
        if not self.player:
            proxy_url = self.bot.settings.proxy_url
            self.player = MusicPlayer(self.bot, guild, proxy=proxy_url)
        return self.player

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Обрабатывает ошибки команд приложения."""
        original_error = getattr(error, "original", error)
        error_message = "Произошла неизвестная ошибка."

        if isinstance(original_error, MusicError):
            error_message = str(original_error)
        else:
            logger.error(
                f"Необработанная ошибка в MusicV2Cog: {original_error}", exc_info=original_error
            )

        if interaction.response.is_done():
            await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)

    @app_commands.command(name="play_v2", description="Воспроизвести музыку по ссылке (V2).")
    @app_commands.describe(url="Ссылка на YouTube")
    async def play(self, interaction: discord.Interaction, url: str) -> None:
        """Воспроизводит музыку по URL-ссылке.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
            url: URL-ссылка на трек.
        """
        await interaction.response.defer(thinking=True)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(
                "Эта команда может быть использована только на сервере."
            )
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            raise UserNotInVoiceChannel(
                "Вы должны быть в голосовом канале, чтобы использовать эту команду!"
            )

        player = self._get_player(interaction.guild)
        await player.connect(interaction.user.voice.channel)

        if player.is_playing():
            await interaction.followup.send(
                "Пока что можно добавить только один трек. Очередь будет позже."
            )
            return

        track_info = await get_track_info(url, self.bot.loop, proxy=player.proxy)
        track = Track(track_info, interaction.user)

        await player.play(track)
        await interaction.followup.send(f"▶️ Начинаю воспроизведение: **{track.title}**")

    @app_commands.command(name="stop_v2", description="Остановить воспроизведение и выйти (V2).")
    async def stop(self, interaction: discord.Interaction) -> None:
        """Останавливает музыку и отключает бота.

        Args:
            interaction: Взаимодействие, инициировавшее команду.
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "Эта команда может быть использована только на сервере.", ephemeral=True
            )
            return

        player = self._get_player(interaction.guild)
        await player.disconnect()

        await interaction.response.send_message(
            "⏹️ Воспроизведение остановлено, бот отключен.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    """Добавляет MusicV2Cog к боту."""
    await bot.add_cog(MusicV2Cog(bot))
    logger.info("Музыкальный модуль (MusicV2Cog) добавлен к боту.")
