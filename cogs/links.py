"""Ког для управления привязками аккаунтов Dota 2 к Discord аккаунтам.

Этот модуль предоставляет команды для:
- Привязки одного или нескольких Steam ID Dota 2 к Discord аккаунту пользователя.
- Отвязки одного или всех Steam ID.
- Просмотра списка привязанных Steam ID.

Привязанные аккаунты используются другими когами (например, LastMatchCog) для
получения игровой статистики пользователя.
"""

import logging

from discord import Interaction, app_commands
from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler, safe_send
from utils.links_data_manager import LinksDataManager

logger = logging.getLogger("bot.cogs.links")


class LinksCog(commands.Cog):
    """Команды для привязки аккаунтов Dota 2."""

    cog_name = "Links"

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког LinksCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        self.links_manager = LinksDataManager()

    async def send_response(self, ctx: commands.Context, message: str) -> None:
        """Тонкая обёртка над :func:`safe_send` — оставлена для обратной совместимости вызывающего кода."""
        await safe_send(ctx, message, ephemeral=True)

    @commands.hybrid_command(description="Привязать аккаунт Dota 2")
    @app_commands.describe(player_id="Steam ID аккаунта Dota 2 (32-битное число)")
    @command_error_handler
    async def link(self, ctx: commands.Context, player_id: int) -> None:
        """Привязывает аккаунт Dota 2 к Discord аккаунту."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        if player_id <= 0:
            await self.send_response(ctx, "ID игрока должен быть положительным числом.")
            return

        user_id = ctx.author.id
        logger.info(f"Привязка аккаунта Dota 2 {player_id} к Discord ID {user_id}")

        # Получаем текущие привязки из БД
        current_links = await self.links_manager.get_links(user_id)

        if player_id in current_links:
            await self.send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} уже привязан.")
            return

        settings = get_settings()
        max_links = settings.limits.links_max_per_user
        if len(current_links) >= max_links:
            await self.send_response(
                ctx, f"Вы достигли лимита в {max_links} привязанных аккаунтов."
            )
            return

        # Добавляем привязку через менеджер
        success = await self.links_manager.add_link(user_id, player_id)

        if success:
            current_links.append(player_id)
            if len(current_links) == 1:
                await self.send_response(
                    ctx,
                    (
                        f"Аккаунт Dota 2 с ID {player_id} успешно привязан.\n"
                        "Теперь вы можете использовать команду `/lastmatch`."
                    ),
                )
            else:
                all_accounts = ", ".join(str(acc) for acc in current_links)
                await self.send_response(
                    ctx,
                    f"Аккаунт Dota 2 с ID {player_id} успешно привязан.\n"
                    f"У вас привязано несколько аккаунтов: {all_accounts}.\n"
                    f"Бот автоматически выберет аккаунт с последним матчем.",
                )
        else:
            await self.send_response(
                ctx,
                (
                    "Произошла ошибка при добавлении привязки. "
                    "Возможно, она уже существует или произошла ошибка БД."
                ),
            )

    @commands.hybrid_command(description="Отвязать аккаунт Dota 2")
    @app_commands.describe(player_id="Какой ID отвязать (без указания — отвяжутся все)")
    @command_error_handler
    async def unlink(self, ctx: commands.Context, player_id: int | None = None) -> None:
        """Отвязывает аккаунт Dota 2 от Discord аккаунта."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        logger.info(f"Отвязка аккаунта Dota 2 от Discord ID {user_id}. Player ID: {player_id}")

        current_links = await self.links_manager.get_links(user_id)
        if not current_links:
            await self.send_response(ctx, "У вас нет привязанных аккаунтов Dota 2.")
            return

        if player_id is not None:
            # Отвязка конкретного ID
            if player_id in current_links:
                success = await self.links_manager.remove_link(user_id, player_id)
                if success:
                    if current_links:
                        current_links.remove(player_id)
                    if current_links:
                        remaining = ", ".join(str(acc) for acc in current_links)
                        await self.send_response(
                            ctx,
                            f"Аккаунт Dota 2 с ID {player_id} успешно отвязан.\n"
                            f"У вас остаются привязанными: {remaining}",
                        )
                    else:
                        await self.send_response(
                            ctx,
                            (
                                f"Аккаунт Dota 2 с ID {player_id} успешно отвязан. "
                                "У вас больше нет привязанных аккаунтов."
                            ),
                        )
                else:
                    await self.send_response(ctx, "Произошла ошибка при удалении привязки.")
            else:
                accounts = ", ".join(str(acc) for acc in current_links)
                await self.send_response(
                    ctx, f"Аккаунт Dota 2 с ID {player_id} не привязан.\nВаши аккаунты: {accounts}"
                )
        else:
            # Отвязка всех аккаунтов
            count = await self.links_manager.remove_all_links(user_id)
            if count > 0:
                await self.send_response(
                    ctx, f"Все {count} аккаунтов Dota 2 были успешно отвязаны."
                )
            else:
                # Эта ветка не должна сработать из-за проверки в начале, но на всякий случай
                await self.send_response(
                    ctx,
                    "Не удалось отвязать аккаунты (возможно, их уже не было или произошла ошибка).",
                )

    @unlink.autocomplete("player_id")
    async def unlink_autocomplete(
        self, interaction: Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        """Подсказывает при отвязке только уже привязанные к пользователю ID."""
        try:
            links = await self.links_manager.get_links(interaction.user.id)
        except Exception as e:
            logger.debug(f"Автокомплит unlink не смог получить привязки: {e}")
            return []
        cur = current.strip()
        return [
            app_commands.Choice(name=str(pid), value=pid)
            for pid in links
            if not cur or cur in str(pid)
        ][:25]

    @commands.hybrid_command(description="Показать привязанные аккаунты Dota 2")
    @command_error_handler
    async def links(self, ctx: commands.Context) -> None:
        """Показывает список Steam ID Dota 2, привязанных к вашему Discord аккаунту."""
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        logger.info(f"Запрос списка привязанных аккаунтов для Discord ID {user_id}.")

        linked_accounts_ids = await self.links_manager.get_links(user_id)

        if linked_accounts_ids:
            linked_accounts_str = "\n".join(str(account_id) for account_id in linked_accounts_ids)
            if len(linked_accounts_ids) > 1:
                await self.send_response(
                    ctx,
                    (
                        f"Ваши привязанные аккаунты Dota 2:\n{linked_accounts_str}\n"
                        "При использовании `/lastmatch` бот автоматически выберет "
                        "аккаунт с последним матчем."
                    ),
                )
            else:
                await self.send_response(
                    ctx, f"Ваш привязанный аккаунт Dota 2:\n{linked_accounts_str}"
                )
        else:
            await self.send_response(
                ctx, "У вас нет привязанных аккаунтов Dota 2. Используйте `/link PLAYER_ID`."
            )

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        # В данном коге нет активных задач или ресурсов, требующих освобождения.
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког LinksCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LinksCog(bot))
    logger.info("Ког LinksCog успешно загружен.")
