"""Развлекательный ког с различными командами для участников сервера.

Этот модуль предоставляет набор развлекательных команд для участников Discord сервера:
- deathbattle: Симуляция битвы между двумя пользователями
- snipe: Показ последнего удаленного сообщения в канале
- penis: Генерация случайного размера пениса для пользователя
- avatar: Отображение аватара пользователя
- quote: Случайная карточка из старой коллекции или сохранённых сообщений

Также модуль отслеживает удаленные сообщения для функции snipe.
"""

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from config.settings import get_settings
from utils.avatar_utils import display_avatar
from utils.deathbattle_utils import run_battle
from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.penis_utils import measure_penis
from utils.quotes.service import QuoteService
from utils.quotes.store import QuoteRecord, QuoteStoreError
from utils.quotes.views import DeleteQuoteButton
from utils.quotes_utils import (
    scan_quotes_folders,
    send_random_quote_image,
    validate_folder_exists,
)
from utils.snipe_utils import save_deleted_message, show_sniped_message
from utils.tyan.catalog import load_catalog
from utils.tyan.presentation import build_tyan_card
from utils.tyan_data_manager import TyanDataManager

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
        self.tyan_catalog = load_catalog()
        self.tyan_manager = TyanDataManager()
        self._quotes: QuoteService | None = None
        self.quote_menu = app_commands.ContextMenu(
            name="В цитаты", callback=self.add_quote_context_menu
        )

    @property
    def quotes(self) -> QuoteService:
        """Лениво создаёт общее хранилище и ограниченный рендер цитат."""
        if self._quotes is None:
            settings = get_settings()
            self._quotes = QuoteService(settings.fun.quotes, settings.guild_id)
        return self._quotes

    async def cog_load(self) -> None:
        """Регистрирует меню сообщений и один обработчик постоянных кнопок."""
        self.bot.tree.add_command(self.quote_menu)
        self.bot.add_dynamic_items(DeleteQuoteButton)

    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 30.0, key=lambda interaction: interaction.user.id)
    @command_error_handler
    async def add_quote_context_menu(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        """Показывает личный предпросмотр текстовой цитаты перед сохранением."""
        try:
            await self.quotes.start_preview(interaction, message)
        except (ValueError, QuoteStoreError) as error:
            await safe_send_error(interaction, str(error))

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
    @discord.app_commands.describe(
        member1="Первый боец (по умолчанию — автор команды)",
        member2="Второй боец (по умолчанию — случайный участник)",
    )
    @command_error_handler
    async def deathbattle(
        self,
        ctx: commands.Context,
        member1: discord.Member | None = None,
        member2: discord.Member | None = None,
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
    @discord.app_commands.describe(mentioned_user="Чей размер измерить (по умолчанию — твой)")
    @command_error_handler
    async def penis(
        self, ctx: commands.Context, mentioned_user: discord.Member | None = None
    ) -> None:
        """Генерирует случайный размер пениса.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, для которого измеряется
                (опционально, по умолчанию - автор команды).
        """
        await measure_penis(ctx, mentioned_user)

    @commands.hybrid_command(description="Твоя случайная тянка на сегодня")
    @commands.guild_only()
    @app_commands.guild_only()
    @command_error_handler
    async def tyan(self, ctx: commands.Context) -> None:
        """Показывает дневную тянку автора с обновлением в полночь по Москве."""
        if ctx.guild is None:
            await safe_send_error(ctx, "Эта команда доступна только на сервере.")
            return
        if ctx.interaction is not None:
            await ctx.defer()
        roll = await self.tyan_manager.get_daily_roll(
            self.tyan_catalog,
            self.bot.settings.fun.tyan,
            user_id=ctx.author.id,
            member_ids=[member.id for member in ctx.guild.members if not member.bot],
        )
        await safe_send(
            ctx, view=build_tyan_card(roll), allowed_mentions=discord.AllowedMentions.none()
        )

    @commands.hybrid_command(description="Показывает аватар пользователя")
    @discord.app_commands.describe(mentioned_user="Чей аватар показать (по умолчанию — твой)")
    @command_error_handler
    async def avatar(
        self, ctx: commands.Context, mentioned_user: discord.Member | None = None
    ) -> None:
        """Показывает аватар указанного пользователя или автора команды.

        Args:
            ctx: Контекст команды.
            mentioned_user: Пользователь, чей аватар нужно показать
                (опционально, по умолчанию - автор команды).
        """
        await display_avatar(ctx, mentioned_user)

    @commands.hybrid_command(description="Показывает случайную цитату из коллекции сервера")
    @discord.app_commands.describe(user="Чьи цитаты показать (по умолчанию — случайный участник)")
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    @command_error_handler
    async def quote(self, ctx: commands.Context, user: str | None = None) -> None:
        """Отправляет случайную цитату пользователя.

        Если user не указан, отправляет случайную цитату любого пользователя.
        Если указан, отправляет случайную цитату этого пользователя.

        Args:
            ctx: Контекст команды.
            user: Имя старой коллекции или автор из подсказок (опционально).
        """
        try:
            records = await self.quotes.visible_records(ctx.guild) if ctx.guild is not None else []
            if records or (user is not None and user.startswith("user:")):
                await self._send_collected_quote(ctx, user, records)
                return
        except (ValueError, QuoteStoreError) as error:
            await safe_send_error(ctx, str(error))
            return
        if user is None:
            available_users = scan_quotes_folders()

            if not available_users:
                await safe_send_error(ctx, "Цитаты не найдены.")
                return

            # Выбираем случайного пользователя
            random_user = random.choice(available_users)
            await send_random_quote_image(ctx, random_user, embed=False)

        else:
            # Проверяем существование пользователя
            if not validate_folder_exists(user):
                await safe_send_error(ctx, f"Цитаты пользователя `{user}` не найдены.")
                return

            # Отправляем случайную цитату указанного пользователя
            await send_random_quote_image(ctx, user, embed=False)

    async def _send_collected_quote(
        self, ctx: commands.Context, user: str | None, records: list[QuoteRecord]
    ) -> None:
        if user is not None and user.startswith("user:"):
            candidates = [record for record in records if user == f"user:{record.author_id}"]
            if not candidates:
                await safe_send_error(ctx, "Доступных цитат этого автора пока нет.")
                return
            await self.quotes.send_record(ctx, random.choice(candidates))
            return
        legacy = scan_quotes_folders()
        groups: dict[str, list[QuoteRecord]] = {name: [] for name in legacy}
        for record in records:
            key = next(
                (name for name in legacy if name.casefold() == record.author_name.casefold()),
                f"user:{record.author_id}",
            )
            groups.setdefault(key, []).append(record)
        selected = user
        if selected is None and groups:
            selected = random.choice(list(groups))
        if selected not in groups:
            selected = next(
                (
                    key
                    for key, items in groups.items()
                    if user is not None
                    and (
                        key.casefold() == user.casefold()
                        or any(
                            user.casefold()
                            in {
                                record.author_name.casefold(),
                                record.author_display_name.casefold(),
                            }
                            or user == f"user:{record.author_id}"
                            for record in items
                        )
                    )
                ),
                None,
            )
        if selected is None:
            await safe_send_error(ctx, "Доступных цитат этого автора пока нет.")
            return
        pool: list[QuoteRecord | None] = list(groups[selected])
        if selected in legacy:
            pool.append(None)
        chosen = random.choice(pool)
        if chosen is None:
            await send_random_quote_image(ctx, selected, embed=False)
        else:
            await self.quotes.send_record(ctx, chosen)

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

            choices = [
                app_commands.Choice(name=name[:100], value=name)
                for name in available_users
                if current.casefold() in name.casefold()
            ]
            if isinstance(interaction.guild, discord.Guild):
                authors: dict[int, QuoteRecord] = {}
                for record in await self.quotes.visible_records(interaction.guild):
                    authors.setdefault(record.author_id, record)
                for author_id, record in authors.items():
                    label = f"{record.author_display_name} (@{record.author_name})"
                    if current.casefold() in label.casefold():
                        choices.append(
                            app_commands.Choice(name=label[:100], value=f"user:{author_id}")
                        )
            return choices[:25]

        except Exception as e:
            logger.error(f"Ошибка в автокомплите quote: {e}", exc_info=True)
            return []

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        self.bot.tree.remove_command(self.quote_menu.name, type=self.quote_menu.type)
        guild_id = getattr(getattr(self.bot, "settings", None), "guild_id", None)
        if isinstance(guild_id, int):
            guild = discord.Object(id=guild_id)
            if (
                self.bot.tree.get_command(
                    self.quote_menu.name, guild=guild, type=self.quote_menu.type
                )
                is self.quote_menu
            ):
                self.bot.tree.remove_command(
                    self.quote_menu.name, guild=guild, type=self.quote_menu.type
                )
        self.bot.remove_dynamic_items(DeleteQuoteButton)
        if self._quotes is not None:
            await self._quotes.close()
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког FunCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(FunCog(bot))
    logger.info("Ког FunCog успешно загружен.")
