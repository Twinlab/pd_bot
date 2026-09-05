"""Публикация пользовательских изменений после запуска новой версии бота."""

import logging

import discord
from discord.ext import commands, tasks

from config.settings import Environment
from utils.release_announcements import ReleaseAnnouncer, load_release_note

logger = logging.getLogger("bot.cogs.announcements")


class AnnouncementsCog(commands.Cog):
    """Запускает доставку анонса после готовности Discord и повторяет сетевые сбои."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.announcer = ReleaseAnnouncer()
        self._completed = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Не создаёт дополнительных задач при повторных событиях готовности."""
        if self.bot.settings.environment != Environment.PRODUCTION:
            return
        if not self._completed and not self.deliver_release.is_running():
            self.deliver_release.start()

    async def cog_unload(self) -> None:
        """Останавливает повторы при выгрузке кога."""
        if self.deliver_release.is_running():
            self.deliver_release.cancel()

    @tasks.loop(minutes=5)
    async def deliver_release(self) -> None:
        """Завершает задачу после публикации или отсутствия нового текста."""
        try:
            release = load_release_note()
            channel_id = self.bot.settings.channels.announcements
            if not release.text or channel_id is None:
                logger.info("Анонс обновления пропущен: текст или канал не настроен.")
            else:
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    raise ValueError("Канал анонсов должен быть текстовым каналом сервера.")
                if channel.guild.id != self.bot.settings.guild_id:
                    raise ValueError("Канал анонсов не принадлежит настроенному серверу.")
                if self.bot.user is None:
                    raise RuntimeError("Discord ещё не предоставил пользователя бота.")
                published = await self.announcer.publish(release, channel, bot_id=self.bot.user.id)
                logger.info(
                    "Анонс релиза %s: %s.",
                    release.id,
                    "опубликован" if published else "уже доставлен",
                )
            self._completed = True
            self.deliver_release.stop()
        except Exception:
            logger.exception("Не удалось доставить анонс обновления; повтор через 5 минут.")


async def setup(bot: commands.Bot) -> None:
    """Загружает объявления об обновлениях."""
    await bot.add_cog(AnnouncementsCog(bot))
