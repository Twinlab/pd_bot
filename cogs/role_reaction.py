"""Ког для выдачи ролей через persistent-кнопки под сообщением.

Администратор создаёт сообщение (``/setup_role_message``) и привязывает к нему
роли (``/role_assign``); каждая роль получает кнопку-переключатель. Нажатие
выдаёт или снимает роль. Кнопки используют ``DynamicItem`` (``role_id`` зашит в
``custom_id``), поэтому переживают рестарт бота после единственной регистрации
``bot.add_dynamic_items`` в :meth:`cog_load`.

Привязки хранятся в БД (эмодзи, роль, описание); системная запись с
``role_id == 0`` помечает само ролевое сообщение и в кнопки не попадает.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.role_reaction_data_manager import RoleReactionDataManager
from utils.role_reaction_views import MAX_BUTTONS, RoleButton, parse_emoji

ROLE_MESSAGE_INTRO = "Нужна роль? Нажми на кнопку ниже."

logger = logging.getLogger("bot.cogs.role_reaction")


def _normalize_emoji(emoji_str: str) -> str:
    """Нормализует формат эмодзи, убирая префикс 'a:' для единообразия хранения и поиска."""
    if emoji_str.startswith("a:"):
        return emoji_str[2:]
    return emoji_str


class RoleReactionCog(commands.Cog):
    """Ког для управления ролями через реакции."""

    bot: commands.Bot
    data_manager: RoleReactionDataManager
    message_cache: dict[int, tuple[int, int]]

    def __init__(self, bot: commands.Bot):
        """Инициализирует ког RoleReactionCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        self.data_manager = RoleReactionDataManager()
        self.message_cache: dict[
            int, tuple[int, int]
        ] = {}  # Кеш для хранения ID сообщений с реакциями {guild_id: (channel_id, message_id)}
        self._migrated = False  # Перерисовку на кнопки делаем один раз за процесс

    async def cog_load(self) -> None:
        """Регистрирует persistent-кнопки ролей.

        ``add_dynamic_items`` оживляет кнопки после рестарта (``role_id`` зашит в
        ``custom_id``). Загрузку кеша и перерисовку старого сообщения делаем в
        :meth:`on_ready` — на момент ``cog_load`` бот ещё не подключён к гильдиям
        (``self.bot.guilds`` пуст), и кеш просто не загрузился бы.
        """
        self.bot.add_dynamic_items(RoleButton)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Один раз за процесс грузит кеш и мигрирует сообщение на кнопки.

        Старое ролевое сообщение могло быть на эмодзи-реакциях — перерисовываем
        его на кнопки и снимаем легаси-реакции. ``on_ready`` может срабатывать на
        каждый реконнект, поэтому защищаемся флагом ``_migrated``.
        """
        if self._migrated:
            return
        self._migrated = True

        await self.load_message_cache()
        for guild_id in list(self.message_cache):
            try:
                await self.update_reaction_message(guild_id)
            except Exception as e:
                logger.warning(
                    f"Не удалось перерисовать ролевое сообщение {guild_id} на кнопки: {e}"
                )

    async def load_message_cache(self) -> None:
        """Загружает кеш сообщений с реакциями из БД в атрибут self.message_cache."""
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if guild is None:
            logger.warning("load_message_cache: бот ещё не подключен ни к одному серверу.")
            return
        message_info = await self.data_manager.get_message_info(guild.id)
        if message_info:
            self.message_cache[guild.id] = message_info
            logger.info(f"Загружена информация о сообщении с реакциями для сервера {guild.id}")

    async def update_reaction_message(self, guild_id: int) -> bool:
        """Перерисовывает ролевое сообщение: список ролей в тексте + кнопки.

        Каждой валидной привязке соответствует persistent-кнопка
        :class:`RoleButton`. Системные записи (``role_id == 0``) и привязки на
        несуществующие роли в кнопки не попадают.

        Args:
            guild_id: ID сервера, на котором нужно обновить сообщение.

        Returns:
            True, если обновление прошло успешно, иначе False.
        """
        if guild_id not in self.message_cache:
            logger.warning(f"Не найдено ролевое сообщение для сервера {guild_id}")
            return False

        channel_id, message_id = self.message_cache[guild_id]
        guild = self.bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"Не найден сервер с ID {guild_id}")
            return False

        channel = guild.get_channel(channel_id)
        if not channel:
            logger.warning(f"Не найден канал с ID {channel_id} на сервере {guild_id}")
            return False

        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            logger.warning(f"Не найдено сообщение с ID {message_id} в канале {channel_id}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при получении сообщения {message_id}: {e}", exc_info=True)
            return False

        role_reactions = await self.data_manager.get_all_role_reactions(guild_id)

        content = f"{ROLE_MESSAGE_INTRO}\n\n"
        view = discord.ui.View(timeout=None)
        for db_reaction_info in role_reactions:
            if db_reaction_info["role_id"] == 0:
                continue
            role = guild.get_role(db_reaction_info["role_id"])
            if role is None:
                logger.warning(
                    f"Не найдена роль с ID {db_reaction_info['role_id']} на сервере {guild_id}"
                )
                continue
            content += (
                f"{db_reaction_info['emoji']} — {role.mention}: {db_reaction_info['description']}\n"
            )
            if len(view.children) < MAX_BUTTONS:
                view.add_item(
                    RoleButton(
                        role.id, label=role.name[:80], emoji=parse_emoji(db_reaction_info["emoji"])
                    )
                )

        try:
            await message.edit(content=content, view=view)
            # Снимаем легаси эмодзи-реакции, оставшиеся от старой схемы выдачи ролей.
            if message.reactions:
                try:
                    await message.clear_reactions()
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.warning(f"Не удалось снять старые реакции с {message_id}: {e}")
            logger.info(f"Обновлено ролевое сообщение для сервера {guild_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении ролевого сообщения: {e}", exc_info=True)
            return False

    @commands.hybrid_command(
        name="setup_role_message", description="Создает сообщение для получения ролей через реакции"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def setup_role_message(self, ctx: commands.Context) -> None:
        """Создает сообщение для получения ролей через реакции в указанном канале.

        Канал берется из конфигурации (`ROLE_REACTION_DEFAULT_CHANNEL_ID`) или используется текущий.
        Это сообщение будет обновляться при добавлении новых ролей.
        """
        # Получаем ID канала из конфига или используем текущий
        default_channel_id_str = str(self.bot.settings.channels.role_reactions_default)
        target_channel = ctx.channel  # По умолчанию текущий

        try:
            target_channel_id_int = int(default_channel_id_str)
            specified_channel = self.bot.get_channel(target_channel_id_int)
            if specified_channel:
                # Используем аннотацию типа для указания mypy, что тип совместим
                target_channel = specified_channel  # type: ignore
                logger.info(
                    f"Используется канал {target_channel.id} из конфигурации "
                    "(ROLE_REACTION_DEFAULT_CHANNEL_ID)."
                )
            else:
                logger.warning(
                    f"Канал с ID {default_channel_id_str} из конфига не найден. "
                    f"Используется текущий канал {ctx.channel.id}."
                )
        except ValueError:
            logger.warning(
                f"Некорректный ID канала '{default_channel_id_str}' в конфиге. "
                f"Используется текущий канал {ctx.channel.id}."
            )

        try:
            # Проверяем, существует ли уже сообщение для этого сервера
            existing_message = await self.data_manager.get_message_info(ctx.guild.id)
            if existing_message:
                old_channel_id, message_id = existing_message
                await safe_send(
                    ctx,
                    f"Сообщение с реакциями уже существует в канале <#{old_channel_id}>. "
                    f"Используйте команду `/role_assign` для добавления ролей.",
                    ephemeral=True,
                )
                return

            # Отправляем начальное сообщение в определенный ранее target_channel
            message = await target_channel.send(ROLE_MESSAGE_INTRO)

            # Сохраняем информацию о сообщении в кеше
            self.message_cache[ctx.guild.id] = (target_channel.id, message.id)

            # Сохраняем информацию о сообщении в базе данных
            # Используем специальный эмодзи, который не будет удален
            await self.data_manager.add_role_reaction(
                ctx.guild.id,
                target_channel.id,
                message.id,
                "✅",
                0,
                "Системная запись - не удалять",
            )

            # Подтверждаем создание сообщения
            await safe_send(
                ctx,
                f"Сообщение для получения ролей создано в канале <#{target_channel.id}>. "
                f"Используйте команду `/role_assign` для добавления ролей.",
                ephemeral=True,
            )

            logger.info(
                f"Создано сообщение с реакциями для сервера {ctx.guild.id} "
                f"в канале {target_channel.id}"
            )
        except discord.Forbidden:
            await safe_send(
                ctx, "У бота нет прав для отправки сообщений в указанный канал.", ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка при создании сообщения с ролями: {e}", exc_info=True)
            await safe_send(ctx, f"Произошла ошибка: {str(e)}", ephemeral=True)

    @app_commands.command(
        name="role_assign", description="Добавляет роль, которую можно получить через реакцию"
    )
    @app_commands.describe(
        role="Роль, которую можно будет получить через реакцию",
        emoji="Эмодзи, который нужно нажать для получения роли",
        description="Описание роли",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def role_assign(
        self, interaction: discord.Interaction, role: discord.Role, emoji: str, description: str
    ) -> None:
        """Добавляет роль, которую можно получить через реакцию.

        Параметры:
        role: Роль, которую можно будет получить через реакцию.
        emoji: Эмодзи, который нужно нажать для получения роли.
        description: Описание роли.
        """
        # Проверяем, существует ли сообщение с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(interaction.guild.id)
        if not message_info:
            await safe_send_error(
                interaction,
                "Сообщение с реакциями не найдено. Сначала создайте его с помощью "
                "команды `/setup_role_message`.",
            )
            return

        # Проверяем, что эмодзи валидный
        try:
            # Пытаемся преобразовать пользовательский эмодзи в формат,
            # который Discord может использовать для реакций
            if len(emoji) > 2 and emoji.startswith("<") and emoji.endswith(">"):
                # Это пользовательский эмодзи, извлекаем его ID
                emoji_id = emoji.split(":")[-1][:-1]
                emoji_name = emoji.split(":")[1]

                emoji_format = _normalize_emoji(f"{emoji_name}:{emoji_id}")
            else:
                emoji_format = emoji

            channel_id, message_id = message_info
            # Обновляем кеш, если его нет
            if interaction.guild.id not in self.message_cache:
                self.message_cache[interaction.guild.id] = (channel_id, message_id)

            success = await self.data_manager.add_role_reaction(
                interaction.guild.id, channel_id, message_id, emoji_format, role.id, description
            )

            if success:
                # Обновляем сообщение с реакциями
                await self.update_reaction_message(interaction.guild.id)

                await interaction.response.send_message(
                    f"Роль {role.mention} успешно привязана к эмодзи {emoji}.", ephemeral=True
                )
                logger.info(
                    f"Добавлена привязка роли {role.id} к эмодзи {emoji_format} "
                    f"на сервере {interaction.guild.id}"
                )
            else:
                await safe_send_error(
                    interaction, "Не удалось добавить привязку роли. Проверьте журнал ошибок."
                )
        except discord.NotFound as e:
            # Если это ошибка "Unknown interaction", просто логируем
            error_str = str(e).lower()
            if "unknown interaction" in error_str:
                logger.info(f"Взаимодействие не найдено при добавлении роли: {e}")
                return

            # Для других ошибок NotFound пытаемся отправить сообщение
            logger.error(f"Ошибка 'Not Found' при добавлении привязки роли: {e}", exc_info=True)
            await safe_send_error(interaction, str(e))
        except Exception as e:
            logger.error(f"Ошибка при добавлении привязки роли: {e}", exc_info=True)
            await safe_send_error(interaction, str(e))

    @app_commands.command(
        name="role_remove", description="Удаляет роль из списка ролей, получаемых через реакции"
    )
    @app_commands.describe(emoji="Эмодзи, привязанный к роли, которую нужно удалить")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def role_remove(self, interaction: discord.Interaction, emoji: str) -> None:
        """Удаляет роль из списка ролей, получаемых через реакции.

        Параметры:
        emoji: Эмодзи, привязанный к роли, которую нужно удалить.
        """
        # Проверяем, существует ли сообщение с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(interaction.guild.id)
        if not message_info:
            await safe_send_error(
                interaction,
                "Сообщение с реакциями не найдено. Сначала создайте его с помощью "
                "команды `/setup_role_message`.",
            )
            return

        # Преобразуем эмодзи в правильный формат
        try:
            if len(emoji) > 2 and emoji.startswith("<") and emoji.endswith(">"):
                # Это пользовательский эмодзи, извлекаем его ID
                emoji_id = emoji.split(":")[-1][:-1]
                emoji_name = emoji.split(":")[1]

                emoji_format = _normalize_emoji(f"{emoji_name}:{emoji_id}")
            else:
                emoji_format = emoji

            success = await self.data_manager.remove_role_reaction(
                interaction.guild.id, emoji_format
            )

            if success:
                # Обновляем сообщение с реакциями
                await self.update_reaction_message(interaction.guild.id)

                await interaction.response.send_message(
                    f"Роль, привязанная к эмодзи {emoji}, успешно удалена.", ephemeral=True
                )
                logger.info(
                    f"Удалена привязка роли к эмодзи {emoji_format} "
                    f"на сервере {interaction.guild.id}"
                )
            else:
                await safe_send_error(interaction, f"Не найдена привязка роли к эмодзи {emoji}.")
        except discord.NotFound as e:
            # Если это ошибка "Unknown interaction", просто логируем
            error_str = str(e).lower()
            if "unknown interaction" in error_str:
                logger.info(f"Взаимодействие не найдено при удалении роли: {e}")
                return

            # Для других ошибок NotFound пытаемся отправить сообщение
            logger.error(f"Ошибка 'Not Found' при удалении привязки роли: {e}", exc_info=True)
            await safe_send_error(interaction, str(e))
        except Exception as e:
            logger.error(f"Ошибка при удалении привязки роли: {e}", exc_info=True)
            await safe_send_error(interaction, str(e))

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога."""
        # В данном коге нет активных задач, требующих остановки,
        # но логируем для единообразия.
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког RoleReactionCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(RoleReactionCog(bot))
    logger.info("Ког RoleReactionCog успешно загружен.")
