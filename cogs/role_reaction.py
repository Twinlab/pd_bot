import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
from typing import Optional, Union

# Импортируем утилиты
from utils.error_handler import command_error_handler, safe_send
from utils.role_reaction_data_manager import RoleReactionDataManager

# Настраиваем логгер для модуля ролей по реакциям
logger = logging.getLogger("bot.role_reactions")

class RoleReaction(commands.Cog):
    """Ког для управления ролями через реакции."""

    def __init__(self, bot):
        self.bot = bot
        self.data_manager = RoleReactionDataManager()
        self.message_cache = {}  # Кеш для хранения ID сообщений с реакциями {guild_id: (channel_id, message_id)}

    async def cog_load(self):
        """Вызывается при загрузке кога."""
        logger.info("Ког RoleReaction загружен")
        # Загружаем кеш сообщений при старте
        await self.load_message_cache()

    async def load_message_cache(self):
        """Загружает кеш сообщений с реакциями из БД."""
        for guild in self.bot.guilds:
            message_info = await self.data_manager.get_message_info(guild.id)
            if message_info:
                self.message_cache[guild.id] = message_info
                logger.info(f"Загружена информация о сообщении с реакциями для сервера {guild.id}")

    async def update_reaction_message(self, guild_id: int):
        """Обновляет сообщение с реакциями, добавляя описания ролей и эмодзи."""
        if guild_id not in self.message_cache:
            logger.warning(f"Не найдено сообщение с реакциями для сервера {guild_id}")
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
# Получаем все привязки ролей для этого сервера
        role_reactions = await self.data_manager.get_all_role_reactions(guild_id)
        
        # Формируем новое содержимое сообщения
        content = "Нужна роль? Нажми на соответствующую реакцию.\n\n"
        
        # Добавляем описания ролей и эмодзи
        for reaction in role_reactions:
            role = guild.get_role(reaction['role_id'])
            if role:
                content += f"{reaction['emoji']} - {role.mention}: {reaction['description']}\n"
            else:
                logger.warning(f"Не найдена роль с ID {reaction['role_id']} на сервере {guild_id}")

        # Обновляем сообщение
        try:
            await message.edit(content=content)
            logger.info(f"Обновлено сообщение с реакциями для сервера {guild_id}")
            
            # Убираем все реакции и добавляем нужные
            await message.clear_reactions()
            for reaction in role_reactions:
                try:
                    await message.add_reaction(reaction['emoji'])
                except discord.HTTPException as e:
                    logger.error(f"Не удалось добавить реакцию {reaction['emoji']}: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении сообщения с реакциями: {e}", exc_info=True)
            return False

    @commands.hybrid_command(
        name="setup_role_message",
        description="Создает сообщение для получения ролей через реакции"
    )
    @commands.has_permissions(administrator=True)
    @command_error_handler
    async def setup_role_message(self, ctx, channel_id: str = "1366858138153910282"):
        """
        Создает сообщение для получения ролей через реакции.
        Это сообщение будет обновляться при добавлении новых ролей.
        
        Параметры:
        channel_id: ID канала для сообщения с ролями (по умолчанию 1366858138153910282).
        """
        try:
            # Проверяем, существует ли уже сообщение для этого сервера
            existing_message = await self.data_manager.get_message_info(ctx.guild.id)
            if existing_message:
                old_channel_id, message_id = existing_message
                await safe_send(
                    ctx,
                    f"Сообщение с реакциями уже существует в канале <#{old_channel_id}>. "
                    f"Используйте команду `/role_assign` для добавления ролей.",
                    ephemeral=True
                )
                return
            
            # Определяем канал для отправки сообщения
            target_channel = ctx.channel
            
            # Если указан ID канала, используем его
            if channel_id != str(ctx.channel.id):
                try:
                    channel_id_int = int(channel_id)
                    specified_channel = self.bot.get_channel(channel_id_int)
                    if specified_channel:
                        target_channel = specified_channel
                    else:
                        await safe_send(
                            ctx,
                            f"Канал с ID {channel_id} не найден. Используется текущий канал.",
                            ephemeral=True
                        )
                except ValueError:
                    await safe_send(
                        ctx,
                        f"Некорректный ID канала: {channel_id}. Используется текущий канал.",
                        ephemeral=True
                    )
            
            # Отправляем начальное сообщение
            message = await target_channel.send("Нужна роль? Нажми на соответствующую реакцию.")
            
            # Сохраняем информацию о сообщении
            self.message_cache[ctx.guild.id] = (target_channel.id, message.id)
            
            # Подтверждаем создание сообщения
            await safe_send(
                ctx,
                f"Сообщение для получения ролей создано в канале <#{target_channel.id}>. "
                f"Используйте команду `/role_assign` для добавления ролей.",
                ephemeral=True
            )
            
            logger.info(f"Создано сообщение с реакциями для сервера {ctx.guild.id} в канале {target_channel.id}")
        except discord.Forbidden:
            await safe_send(
                ctx,
                f"У бота нет прав для отправки сообщений в указанный канал.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка при создании сообщения с ролями: {e}", exc_info=True)
            await safe_send(
                ctx,
                f"Произошла ошибка: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(
        name="role_assign",
        description="Добавляет роль, которую можно получить через реакцию"
    )
    @app_commands.describe(
        role="Роль, которую можно будет получить через реакцию",
        emoji="Эмодзи, который нужно нажать для получения роли",
        description="Описание роли"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def role_assign(self, interaction: discord.Interaction, role: discord.Role, emoji: str, description: str):
        """
        Добавляет роль, которую можно получить через реакцию.
        
        Параметры:
        role: Роль, которую можно будет получить через реакцию.
        emoji: Эмодзи, который нужно нажать для получения роли.
        description: Описание роли.
        """
        # Проверяем, существует ли сообщение с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(interaction.guild.id)
        if not message_info:
            # Если сообщения нет, предлагаем создать его
            await interaction.response.send_message(
                "Сообщение с реакциями не найдено. Сначала создайте его с помощью команды `/setup_role_message`.",
                ephemeral=True
            )
            return
        
        # Проверяем, что эмодзи валидный
        try:
            # Пытаемся преобразовать пользовательский эмодзи в формат, который Discord может использовать для реакций
            if len(emoji) > 2 and emoji.startswith('<') and emoji.endswith('>'):
                # Это пользовательский эмодзи, извлекаем его ID
                emoji_id = emoji.split(':')[-1][:-1]
                emoji_name = emoji.split(':')[1]
                emoji_animated = emoji.startswith('<a:')
                
                # Формируем правильный формат для реакции
                emoji_format = f"{'a:' if emoji_animated else ''}{emoji_name}:{emoji_id}"
            else:
                # Это стандартный эмодзи Unicode
                emoji_format = emoji
                
            # Добавляем привязку роли к эмодзи
            channel_id, message_id = message_info
            success = await self.data_manager.add_role_reaction(
                interaction.guild.id, channel_id, message_id, emoji_format, role.id, description
            )
            
            if success:
                # Обновляем сообщение с реакциями
                await self.update_reaction_message(interaction.guild.id)
                
                await interaction.response.send_message(
                    f"Роль {role.mention} успешно привязана к эмодзи {emoji}.",
                    ephemeral=True
                )
                logger.info(f"Добавлена привязка роли {role.id} к эмодзи {emoji_format} на сервере {interaction.guild.id}")
            else:
                await interaction.response.send_message(
                    "Не удалось добавить привязку роли. Проверьте журнал ошибок.",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Ошибка при добавлении привязки роли: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Произошла ошибка: {str(e)}",
                ephemeral=True
            )
            
    @app_commands.command(
        name="role_remove",
        description="Удаляет роль из списка ролей, получаемых через реакции"
    )
    @app_commands.describe(
        emoji="Эмодзи, привязанный к роли, которую нужно удалить"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def role_remove(self, interaction: discord.Interaction, emoji: str):
        """
        Удаляет роль из списка ролей, получаемых через реакции.
        
        Параметры:
        emoji: Эмодзи, привязанный к роли, которую нужно удалить.
        """
        # Проверяем, существует ли сообщение с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(interaction.guild.id)
        if not message_info:
            await interaction.response.send_message(
                "Сообщение с реакциями не найдено. Сначала создайте его с помощью команды `/setup_role_message`.",
                ephemeral=True
            )
            return
        
        # Преобразуем эмодзи в правильный формат
        try:
            if len(emoji) > 2 and emoji.startswith('<') and emoji.endswith('>'):
                # Это пользовательский эмодзи, извлекаем его ID
                emoji_id = emoji.split(':')[-1][:-1]
                emoji_name = emoji.split(':')[1]
                emoji_animated = emoji.startswith('<a:')
                
                # Формируем правильный формат для реакции
                emoji_format = f"{'a:' if emoji_animated else ''}{emoji_name}:{emoji_id}"
            else:
                # Это стандартный эмодзи Unicode
                emoji_format = emoji
            
            # Удаляем привязку роли к эмодзи
            success = await self.data_manager.remove_role_reaction(interaction.guild.id, emoji_format)
            
            if success:
                # Обновляем сообщение с реакциями
                await self.update_reaction_message(interaction.guild.id)
                
                await interaction.response.send_message(
                    f"Роль, привязанная к эмодзи {emoji}, успешно удалена.",
                    ephemeral=True
                )
                logger.info(f"Удалена привязка роли к эмодзи {emoji_format} на сервере {interaction.guild.id}")
            else:
                await interaction.response.send_message(
                    f"Не найдена привязка роли к эмодзи {emoji}.",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Ошибка при удалении привязки роли: {e}", exc_info=True)
            await interaction.response.send_message(
                f"Произошла ошибка: {str(e)}",
                ephemeral=True
            )
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Обрабатывает добавление реакции для выдачи роли."""
        # Игнорируем реакции от ботов
        if payload.member.bot:
            return
        
        # Проверяем, есть ли информация о сообщении с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(payload.guild_id)
        if not message_info:
            return
        
        channel_id, message_id = message_info
        
        # Проверяем, что реакция добавлена к нужному сообщению
        if payload.channel_id != channel_id or payload.message_id != message_id:
            return
        
        # Получаем эмодзи в правильном формате
        emoji = payload.emoji.name
        if payload.emoji.id:
            emoji = f"{payload.emoji.name}:{payload.emoji.id}"
        
        # Получаем роль, привязанную к этому эмодзи
        role_id = await self.data_manager.get_role_by_emoji(payload.guild_id, emoji)
        if not role_id:
            return
        
        # Получаем объект сервера и роли
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        role = guild.get_role(role_id)
        if not role:
            logger.warning(f"Не найдена роль с ID {role_id} на сервере {payload.guild_id}")
            return
        
        # Выдаем роль пользователю
        try:
            await payload.member.add_roles(role, reason="Роль по реакции")
            logger.info(f"Выдана роль {role.name} пользователю {payload.member.display_name} на сервере {guild.name}")
        except discord.Forbidden:
            logger.error(f"Недостаточно прав для выдачи роли {role.name} пользователю {payload.member.display_name}")
        except Exception as e:
            logger.error(f"Ошибка при выдаче роли {role.name} пользователю {payload.member.display_name}: {e}", exc_info=True)
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Обрабатывает удаление реакции для снятия роли."""
        # Проверяем, есть ли информация о сообщении с реакциями для этого сервера
        message_info = await self.data_manager.get_message_info(payload.guild_id)
        if not message_info:
            return
        
        channel_id, message_id = message_info
        
        # Проверяем, что реакция удалена с нужного сообщения
        if payload.channel_id != channel_id or payload.message_id != message_id:
            return
        
        # Получаем эмодзи в правильном формате
        emoji = payload.emoji.name
        if payload.emoji.id:
            emoji = f"{payload.emoji.name}:{payload.emoji.id}"
        
        # Получаем роль, привязанную к этому эмодзи
        role_id = await self.data_manager.get_role_by_emoji(payload.guild_id, emoji)
        if not role_id:
            return
        
        # Получаем объект сервера и роли
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        role = guild.get_role(role_id)
        if not role:
            logger.warning(f"Не найдена роль с ID {role_id} на сервере {payload.guild_id}")
            return
        
        # Получаем пользователя
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                logger.warning(f"Не найден пользователь с ID {payload.user_id} на сервере {payload.guild_id}")
                return
            except Exception as e:
                logger.error(f"Ошибка при получении пользователя {payload.user_id}: {e}", exc_info=True)
                return
        
        # Игнорируем ботов
        if member.bot:
            return
        
        # Снимаем роль с пользователя
        try:
            await member.remove_roles(role, reason="Роль по реакции (удалена)")
            logger.info(f"Снята роль {role.name} с пользователя {member.display_name} на сервере {guild.name}")
        except discord.Forbidden:
            logger.error(f"Недостаточно прав для снятия роли {role.name} с пользователя {member.display_name}")
        except Exception as e:
            logger.error(f"Ошибка при снятии роли {role.name} с пользователя {member.display_name}: {e}", exc_info=True)

async def setup(bot):
    await bot.add_cog(RoleReaction(bot))
