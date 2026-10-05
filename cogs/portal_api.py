"""Внутренний HTTP-адаптер PD Room, выключенный по умолчанию."""

import logging

import discord
from aiohttp import web
from discord.ext import commands

from utils.portal.api import PortalApi, load_portal_token

logger = logging.getLogger("bot.portal")


class PortalApiCog(commands.Cog):
    """Управляет listener без второго процесса или второго хранилища цитат."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api: PortalApi | None = None
        self._runner: web.AppRunner | None = None

    async def cog_load(self) -> None:
        """Открывает закрытый listener только при явном включении и корректном секрете."""
        config = self.bot.settings.portal_api
        if not config.enabled:
            return
        guild_id = self.bot.settings.guild_id
        if not guild_id:
            raise ValueError("Portal API требует ID единственного Discord-сервера.")
        self.api = PortalApi(self.bot, config, load_portal_token(config), guild_id)
        runner = web.AppRunner(
            self.api.create_app(),
            access_log=None,
            shutdown_timeout=15,
            max_line_size=4096,
            max_field_size=1024,
        )
        try:
            await runner.setup()
            await web.TCPSite(runner, config.host, config.port).start()
        except BaseException:
            await runner.cleanup()
            raise
        self._runner = runner
        logger.info("Внутренний Portal API слушает %s:%s", config.host, config.port)

    async def cog_unload(self) -> None:
        """Дожидается активных запросов и закрывает listener при выгрузке."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self.api = None

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Сбрасывает кэш доступа сразу после выхода участника."""
        if self.api is not None and member.guild.id == self.api.guild_id:
            self.api.invalidate_member(member.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Не удерживает устаревшее имя или роль в коротком кэше профиля."""
        if self.api is not None and after.guild.id == self.api.guild_id:
            self.api.invalidate_member(after.id)


async def setup(bot: commands.Bot) -> None:
    """Регистрирует необязательный интерфейс портала."""
    await bot.add_cog(PortalApiCog(bot))
