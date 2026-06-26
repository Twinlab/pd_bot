"""Ког для управления привязками аккаунтов FACEIT (CS2) к Discord аккаунтам.

Команды:
- ``/cslink <ник>`` — привязать аккаунт FACEIT по нику.
- ``/csunlink [ник]`` — отвязать конкретный аккаунт или все.
- ``/cslinks`` — показать привязанные аккаунты.

Привязки используются когом ``CsLastMatchCog`` для получения статистики CS2.
"""

import logging

from discord.ext import commands

from config import get_settings
from utils.cs_links_data_manager import CsLinksDataManager
from utils.cs_match_utils import resolve_player_by_nickname
from utils.error_handler import command_error_handler, safe_send

logger = logging.getLogger("bot.cogs.cs_links")


class CsLinksCog(commands.Cog):
    """Команды для привязки аккаунтов FACEIT."""

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког CsLinksCog."""
        self.bot = bot
        self.links_manager = CsLinksDataManager()

    async def send_response(self, ctx: commands.Context, message: str) -> None:
        """Тонкая обёртка над :func:`safe_send` для эфемерных ответов."""
        await safe_send(ctx, message, ephemeral=True)

    @commands.hybrid_command(description="Привязать аккаунт FACEIT (CS2) по нику")
    @command_error_handler
    async def cslink(self, ctx: commands.Context, nickname: str) -> None:
        """Привязывает аккаунт FACEIT к Discord аккаунту по нику."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        nickname = nickname.strip()
        if not nickname:
            await self.send_response(ctx, "Укажите ник FACEIT.")
            return

        settings = get_settings()
        api_key = settings.faceit_api_key
        if not api_key:
            await self.send_response(ctx, "FACEIT_API_KEY не найден в конфигурации бота.")
            return

        player = await resolve_player_by_nickname(nickname, api_key)
        if not player:
            await self.send_response(
                ctx, f"Игрок FACEIT с ником `{nickname}` не найден или не играет в CS2."
            )
            return

        player_id = player["player_id"]
        resolved_nick = player.get("nickname", nickname)
        user_id = ctx.author.id
        logger.info(f"Привязка FACEIT {resolved_nick} ({player_id}) к Discord ID {user_id}")

        current_links = await self.links_manager.get_links(user_id)
        if any(link.faceit_player_id == player_id for link in current_links):
            await self.send_response(ctx, f"Аккаунт FACEIT `{resolved_nick}` уже привязан.")
            return

        max_links = settings.limits.links_max_per_user
        if len(current_links) >= max_links:
            await self.send_response(
                ctx, f"Вы достигли лимита в {max_links} привязанных аккаунтов."
            )
            return

        success = await self.links_manager.add_link(user_id, player_id, resolved_nick)
        if success:
            await self.send_response(
                ctx,
                f"Аккаунт FACEIT `{resolved_nick}` успешно привязан.\n"
                "Теперь вы можете использовать команду `/cslastmatch`.",
            )
        else:
            await self.send_response(ctx, "Произошла ошибка при добавлении привязки.")

    @commands.hybrid_command(description="Отвязать аккаунт FACEIT (CS2)")
    @command_error_handler
    async def csunlink(self, ctx: commands.Context, nickname: str | None = None) -> None:
        """Отвязывает аккаунт FACEIT от Discord аккаунта."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        current_links = await self.links_manager.get_links(user_id)
        if not current_links:
            await self.send_response(ctx, "У вас нет привязанных аккаунтов FACEIT.")
            return

        if nickname is not None:
            nickname = nickname.strip()
            target = next(
                (link for link in current_links if link.nickname.lower() == nickname.lower()),
                None,
            )
            if target is None:
                accounts = ", ".join(link.nickname for link in current_links)
                await self.send_response(
                    ctx, f"Аккаунт `{nickname}` не привязан.\nВаши аккаунты: {accounts}"
                )
                return

            success = await self.links_manager.remove_link(user_id, target.faceit_player_id)
            if success:
                remaining = [
                    link
                    for link in current_links
                    if link.faceit_player_id != target.faceit_player_id
                ]
                if remaining:
                    remaining_str = ", ".join(link.nickname for link in remaining)
                    await self.send_response(
                        ctx,
                        f"Аккаунт FACEIT `{target.nickname}` отвязан.\n"
                        f"Остаются привязанными: {remaining_str}",
                    )
                else:
                    await self.send_response(
                        ctx,
                        f"Аккаунт FACEIT `{target.nickname}` отвязан. "
                        "У вас больше нет привязанных аккаунтов.",
                    )
            else:
                await self.send_response(ctx, "Произошла ошибка при удалении привязки.")
        else:
            count = await self.links_manager.remove_all_links(user_id)
            if count > 0:
                await self.send_response(ctx, f"Все {count} аккаунтов FACEIT были отвязаны.")
            else:
                await self.send_response(ctx, "Не удалось отвязать аккаунты.")

    @commands.hybrid_command(description="Показать привязанные аккаунты FACEIT (CS2)")
    @command_error_handler
    async def cslinks(self, ctx: commands.Context) -> None:
        """Показывает список аккаунтов FACEIT, привязанных к вашему Discord аккаунту."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        links = await self.links_manager.get_links(user_id)

        if not links:
            await self.send_response(
                ctx, "У вас нет привязанных аккаунтов FACEIT. Используйте `/cslink <ник>`."
            )
            return

        accounts_str = "\n".join(link.nickname for link in links)
        if len(links) > 1:
            await self.send_response(
                ctx,
                f"Ваши привязанные аккаунты FACEIT:\n{accounts_str}\n"
                "При использовании `/cslastmatch` бот выберет аккаунт с последним матчем.",
            )
        else:
            await self.send_response(ctx, f"Ваш привязанный аккаунт FACEIT:\n{accounts_str}")

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког CsLinksCog к боту."""
    await bot.add_cog(CsLinksCog(bot))
    logger.info("Ког CsLinksCog успешно загружен.")
