"""Ког для управления привязками аккаунтов Dota 2 к Discord аккаунтам.

Этот модуль предоставляет команды для:
- Привязки одного или нескольких Steam ID Dota 2 к Discord аккаунту пользователя.
- Отвязки одного или всех Steam ID.
- Просмотра списка привязанных Steam ID.

Привязанные аккаунты используются другими когами (например, LastMatchCog) для
получения игровой статистики пользователя.
"""

import logging
from typing import Optional

from discord.ext import commands

from utils.error_handler import command_error_handler
from utils.links_data_manager import LinksDataManager

logger = logging.getLogger("bot.cogs.links")  # Иерархическое имя логгера


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
        """Отправляет ответ пользователю, пытаясь использовать наиболее подходящий метод.

        Сначала пытается отправить как ephemeral сообщение через interaction,
        затем как обычное сообщение в канал, и в крайнем случае - в ЛС автору.

        Args:
            ctx: Контекст команды.
            message: Текст сообщения для отправки.
        """
        try:
            is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None
            if is_interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа: {e}")
            try:
                await ctx.author.send(message)
            except Exception:
                logger.error("Не удалось отправить приватный ответ")
            try:
                await ctx.send(message)
            except Exception:
                logger.error("Не удалось отправить ответ вообще")

    @commands.hybrid_command(description="Привязать аккаунт Dota 2")
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

        if len(current_links) >= 5:
            await self.send_response(ctx, "Вы достигли лимита в 5 привязанных аккаунтов.")
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
    @command_error_handler
    async def unlink(self, ctx: commands.Context, player_id: Optional[int] = None) -> None:
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

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки, возникающие при выполнении команд в этом коге.

        Args:
            ctx: Контекст команды, где произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.MissingPermissions):
            await self.send_response(ctx, "У вас нет прав для выполнения этой команды.")
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(
                f"Ошибка при выполнении команды {ctx.command}: {error.original}",
                exc_info=error.original,
            )
            await self.send_response(ctx, f"Произошла ошибка: {str(error.original)}")
        elif isinstance(error, commands.BadArgument):
            await self.send_response(ctx, f"Неверный аргумент: {error}")
        else:
            logger.error(f"Необработанная ошибка в команде {ctx.command}: {error}", exc_info=error)
            await self.send_response(ctx, f"Произошла неизвестная ошибка: {str(error)}")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког LinksCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LinksCog(bot))
    logger.info("Ког LinksCog успешно загружен.")
