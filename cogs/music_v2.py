"""Тестовый музыкальный модуль на основе Wavelink."""

import logging
from typing import Optional, cast

import discord
import wavelink
from discord.ext import commands

from config.settings import get_settings

# Создаем логгер с иерархическим именем
logger = logging.getLogger("bot.cogs.music_v2")


class MusicV2Cog(commands.Cog, name="MusicV2"):
    """Тестовый музыкальный модуль на Wavelink.

    Предоставляет базовые команды для тестирования производительности Wavelink
    по сравнению с текущим музыкальным модулем.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует тестовый музыкальный ког.

        Args:
            bot: Экземпляр discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot
        logger.info("Музыкальный модуль V2 (Wavelink) инициализирован.")

    async def cog_load(self) -> None:
        """Подключение к Lavalink при загрузке кога."""
        try:
            settings = get_settings()
            lavalink_config = settings.music.lavalink

            node = wavelink.Node(
                uri=f"http://{lavalink_config.host}:{lavalink_config.port}",
                password=lavalink_config.password,
                identifier=lavalink_config.identifier,
                region=lavalink_config.region,
            )

            await wavelink.Pool.connect(client=self.bot, nodes=[node])
            logger.info(
                f"Подключение к Lavalink серверу установлено: {lavalink_config.host}:{lavalink_config.port}"
            )

        except Exception as e:
            logger.error(f"Ошибка подключения к Lavalink: {e}", exc_info=True)
            raise

    async def cog_unload(self) -> None:
        """Отключение от Lavalink при выгрузке кога."""
        try:
            await wavelink.Pool.close()
            logger.info("Отключение от Lavalink сервера выполнено.")
        except Exception as e:
            logger.warning(f"Ошибка при отключении от Lavalink: {e}")

    async def _ensure_voice_connection(
        self, interaction: discord.Interaction
    ) -> Optional[wavelink.Player]:
        """Проверяет и устанавливает голосовое соединение.

        Args:
            interaction: Взаимодействие Discord.

        Returns:
            Wavelink плеер или None при ошибке.
        """
        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(
                "❌ Команда доступна только на сервере!", ephemeral=True
            )
            return None

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ Вы должны быть в голосовом канале!", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        player: Optional[wavelink.Player] = cast(
            Optional[wavelink.Player], interaction.guild.voice_client
        )

        if not player:
            try:
                player = await channel.connect(cls=wavelink.Player)
                logger.info(f"Подключение к голосовому каналу: {channel.name}")
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Ошибка подключения к каналу: {e}", ephemeral=True
                )
                logger.error(f"Ошибка подключения к голосовому каналу {channel.name}: {e}")
                return None

        return player

    @discord.app_commands.command(
        name="play_v2", description="[ТЕСТ] Воспроизвести музыку через Wavelink"
    )
    @discord.app_commands.describe(query="Поисковый запрос или URL для воспроизведения")
    async def play_v2(self, interaction: discord.Interaction, query: str) -> None:
        """Тестовая команда воспроизведения через Wavelink.

        Args:
            interaction: Взаимодействие Discord.
            query: Поисковый запрос или URL.
        """
        await interaction.response.defer()
        start_time = interaction.created_at.timestamp()

        try:
            # Проверка и подключение к голосовому каналу
            player = await self._ensure_voice_connection(interaction)
            if not player:
                return

            # Поиск трека
            logger.info(f"Поиск трека через Wavelink: {query}")
            search_start = interaction.created_at.timestamp()

            tracks = await wavelink.Playable.search(query)
            search_time = interaction.created_at.timestamp() - search_start

            if not tracks:
                await interaction.followup.send("❌ Треки не найдены!")
                logger.warning(f"Треки не найдены для запроса: {query}")
                return

            track = tracks[0]

            # Воспроизведение
            play_start = interaction.created_at.timestamp()
            await player.play(track)
            play_time = interaction.created_at.timestamp() - play_start
            total_time = interaction.created_at.timestamp() - start_time

            # Создание эмбеда с информацией о треке и производительности
            embed = discord.Embed(
                title="🎵 Воспроизведение начато (Wavelink V2)",
                description=f"**{track.title}**",
                color=0x00FF00,
            )

            if track.author:
                embed.add_field(name="Автор", value=track.author, inline=True)

            # Форматирование длительности
            if track.length:
                duration_minutes = track.length // 60000
                duration_seconds = (track.length % 60000) // 1000
                embed.add_field(
                    name="Длительность",
                    value=f"{duration_minutes}:{duration_seconds:02d}",
                    inline=True,
                )

            embed.add_field(name="Источник", value=track.source.title(), inline=True)
            embed.add_field(name="Запросил", value=interaction.user.mention, inline=True)

            # Метрики производительности
            embed.add_field(
                name="⚡ Производительность",
                value=f"Поиск: {search_time:.2f}с\nЗапуск: {play_time:.2f}с\nВсего: {total_time:.2f}с",
                inline=False,
            )

            if track.uri:
                embed.add_field(name="URL", value=f"[Ссылка]({track.uri})", inline=False)

            await interaction.followup.send(embed=embed)
            logger.info(
                f"Воспроизведение начато через Wavelink: {track.title} (общее время: {total_time:.2f}с)"
            )

        except wavelink.LavalinkException as e:
            await interaction.followup.send(f"❌ Ошибка Lavalink: {e}")
            logger.error(f"Ошибка Lavalink в play_v2: {e}", exc_info=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка воспроизведения: {e}")
            logger.error(f"Ошибка в play_v2: {e}", exc_info=True)

    @discord.app_commands.command(
        name="stop_v2", description="[ТЕСТ] Остановить воспроизведение Wavelink"
    )
    async def stop_v2(self, interaction: discord.Interaction) -> None:
        """Тестовая команда остановки Wavelink.

        Args:
            interaction: Взаимодействие Discord.
        """
        try:
            player: Optional[wavelink.Player] = cast(
                Optional[wavelink.Player], interaction.guild.voice_client
            )

            if not player:
                await interaction.response.send_message(
                    "❌ Бот не подключен к голосовому каналу!", ephemeral=True
                )
                return

            # Проверка прав пользователя
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    "❌ Команда доступна только на сервере!", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Остановить музыку может только администратор.", ephemeral=True
                )
                return

            channel_name = player.channel.name if player.channel else "неизвестный канал"
            await player.disconnect()

            embed = discord.Embed(
                title="⏹️ Воспроизведение остановлено (Wavelink V2)",
                description=f"Бот отключен от канала **{channel_name}**",
                color=0xFF0000,
            )
            embed.add_field(name="Остановил", value=interaction.user.mention, inline=True)

            await interaction.response.send_message(embed=embed)
            logger.info(f"Воспроизведение остановлено через Wavelink в канале: {channel_name}")

        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка остановки: {e}", ephemeral=True)
            logger.error(f"Ошибка в stop_v2: {e}", exc_info=True)

    @discord.app_commands.command(
        name="status_v2", description="[ТЕСТ] Показать статус Wavelink плеера"
    )
    async def status_v2(self, interaction: discord.Interaction) -> None:
        """Показывает текущий статус Wavelink плеера.

        Args:
            interaction: Взаимодействие Discord.
        """
        try:
            player: Optional[wavelink.Player] = cast(
                Optional[wavelink.Player], interaction.guild.voice_client
            )

            embed = discord.Embed(title="📊 Статус Wavelink V2", color=0x0099FF)

            if not player:
                embed.description = "❌ Плеер не подключен"
                embed.add_field(name="Состояние", value="Отключен", inline=True)
            else:
                embed.description = f"✅ Подключен к **{player.channel.name if player.channel else 'неизвестный канал'}**"
                embed.add_field(name="Состояние", value="Подключен", inline=True)
                embed.add_field(name="Пауза", value="Да" if player.paused else "Нет", inline=True)

                if player.current:
                    track = player.current
                    embed.add_field(name="Текущий трек", value=track.title, inline=False)
                    if track.author:
                        embed.add_field(name="Автор", value=track.author, inline=True)
                    embed.add_field(name="Источник", value=track.source.title(), inline=True)
                else:
                    embed.add_field(name="Текущий трек", value="Ничего не играет", inline=False)

            # Информация о Lavalink подключении
            nodes = wavelink.Pool.nodes
            if nodes:
                node = list(nodes.values())[0]
                embed.add_field(
                    name="Lavalink узел", value=f"{node.identifier} ({node.uri})", inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка получения статуса: {e}", ephemeral=True
            )
            logger.error(f"Ошибка в status_v2: {e}", exc_info=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ) -> None:
        """Обрабатывает ошибки команд приложения в этом коге.

        Args:
            interaction: Взаимодействие, где произошла ошибка.
            error: Объект ошибки.
        """
        logger.error(
            f"Ошибка в команде Wavelink V2 "
            f"'{interaction.command.name if interaction.command else 'неизвестно'}': {error}",
            exc_info=error,
        )

        error_message = f"Произошла ошибка в тестовом модуле Wavelink: `{error}`"

        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e}")


async def setup(bot: commands.Bot) -> None:
    """Добавляет MusicV2Cog к боту.

    Args:
        bot: Экземпляр discord.ext.commands.Bot.
    """
    await bot.add_cog(MusicV2Cog(bot))
    logger.info("Музыкальный модуль V2 (MusicV2Cog) добавлен к боту.")
