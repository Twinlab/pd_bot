"""Развлекательный ког с различными командами для участников сервера.

Этот модуль предоставляет набор развлекательных команд для участников Discord сервера:
- deathbattle: Симуляция битвы между двумя пользователями
- snipe: Показ последнего удаленного сообщения в канале
- penis: Генерация случайного размера пениса для пользователя
- avatar: Отображение аватара пользователя
- quote: Отправка случайных изображений из папок

Также модуль отслеживает удаленные сообщения для функции snipe.
"""

import logging
import random
from typing import Optional

import discord
from discord.ext import commands

from utils.avatar_utils import display_avatar
from utils.deathbattle_utils import run_battle
from utils.error_handler import command_error_handler
from utils.penis_utils import measure_penis
from utils.quotes_utils import scan_quotes_folders, send_random_quote_image, validate_folder_exists
from utils.snipe_utils import save_deleted_message, show_sniped_message

logger: logging.Logger = logging.getLogger("bot.cogs.fun")  # Иерархическое имя логгера


class FunCog(commands.Cog):
    """Развлекательные команды для участников сервера.

    Предоставляет набор команд для развлечения пользователей, включая
    симуляцию битв, отображение аватаров, генерацию случайных значений
    и отслеживание удаленных сообщений.

    Attributes:
        bot: Экземпляр бота Discord.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког FunCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot: commands.Bot = bot

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Обрабатывает удаленные сообщения для команды snipe.

        Сохраняет информацию об удаленном сообщении для последующего
        отображения с помощью команды snipe.

        Args:
            message: Удаленное сообщение Discord.
        """
        # Блок try/except не нужен, т.к. ошибки listener не влияют на команды
        await save_deleted_message(message)

    @commands.hybrid_command(description="Запускает дезбаттл между двумя пользователями")
    @command_error_handler
    async def deathbattle(
        self,
        ctx: commands.Context,
        member1: Optional[discord.Member] = None,
        member2: Optional[discord.Member] = None,
    ) -> None:
        """Запускает битву между двумя пользователями с визуализацией сражения.

        Args:
            ctx: Контекст команды
            member1: Первый участник (опционально)
            member2: Второй участник (опционально)
        """
        await run_battle(ctx, member1, member2)

    @commands.hybrid_command(description="Показывает последнее удаленное сообщение")
    @command_error_handler
    async def snipe(self, ctx: commands.Context) -> None:
        """Показывает последнее удаленное сообщение в канале.

        Args:
            ctx: Контекст команды.
        """
        await show_sniped_message(ctx)

    @commands.hybrid_command(description="Показывает размер пениса")
    @command_error_handler
    async def penis(
        self, ctx: commands.Context, mentioned_user: Optional[discord.Member] = None
    ) -> None:
        """Генерирует случайный размер пениса.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, для которого измеряется
                (опционально, по умолчанию - автор команды).
        """
        await measure_penis(ctx, mentioned_user)

    @commands.hybrid_command(description="Показывает аватар пользователя")
    @command_error_handler
    async def avatar(
        self, ctx: commands.Context, mentioned_user: Optional[discord.Member] = None
    ) -> None:
        """Показывает аватар указанного пользователя или автора команды.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, чей аватар нужно показать
                (опционально, по умолчанию - автор команды).
        """
        await display_avatar(ctx, mentioned_user)

    @commands.hybrid_command(description="Отправляет рандомную цитату указанного юзера")
    @command_error_handler
    async def quote(self, ctx: commands.Context, user: Optional[str] = None) -> None:
        """Отправляет случайную цитату пользователя.

        Если user не указан, отправляет случайную цитату любого пользователя.
        Если указан, отправляет случайную цитату этого пользователя.

        Args:
            ctx: Контекст команды.
            user: Юзернейм (опционально).
        """
        if user is None:
            # Отправляем случайную цитату любого пользователя
            available_users = scan_quotes_folders()

            if not available_users:
                await ctx.send("❌ Цитаты не найдены!", ephemeral=True)
                return

            # Выбираем случайного пользователя
            random_user = random.choice(available_users)
            await send_random_quote_image(ctx, random_user, embed=False)

        else:
            # Проверяем существование пользователя
            if not validate_folder_exists(user):
                await ctx.send(f"❌ Цитаты пользователя `{user}` не найдены!", ephemeral=True)
                return

            # Отправляем случайную цитату указанного пользователя
            await send_random_quote_image(ctx, user, embed=False)

    @quote.autocomplete("user")
    async def quote_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[discord.app_commands.Choice[str]]:
        """Автокомплит для параметра user команды quote.

        Args:
            interaction: Взаимодействие Discord.
            current: Текущий ввод пользователя.

        Returns:
            list[discord.app_commands.Choice[str]]: Список вариантов для автокомплита.
        """
        try:
            available_users = scan_quotes_folders()

            # Фильтруем пользователей по текущему вводу (регистронезависимо)
            if current:
                filtered_users = [
                    user for user in available_users if current.lower() in user.lower()
                ]
            else:
                filtered_users = available_users

            # Ограничиваем до 25 вариантов (лимит Discord)
            choices = []
            for user in filtered_users[:25]:
                choices.append(discord.app_commands.Choice(name=user, value=user))

            return choices

        except Exception as e:
            logger.error(f"Ошибка в автокомплите quote: {e}", exc_info=True)
            return []

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки, возникающие при выполнении команд в этом коге.

        Args:
            ctx: Контекст команды, где произошла ошибка.
            error: Объект ошибки.
        """
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас нет прав для выполнения этой команды.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(
                f"Ошибка при выполнении команды: {error.original}", exc_info=error.original
            )
            await ctx.send(f"Произошла ошибка: {error.original}", ephemeral=True)
        else:
            logger.error(f"Необработанная ошибка в команде: {error}", exc_info=error)
            await ctx.send(f"Произошла неизвестная ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког FunCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(FunCog(bot))
    logger.info("Ког FunCog успешно загружен.")
