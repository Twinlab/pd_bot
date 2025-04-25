import json
import os
import logging
import discord
from discord.ext import commands
from typing import Optional, Dict, List

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

# Импортируем функцию загрузки из config.py
from config import load_user_links as load_links_from_config

class Links(commands.Cog):
    """Команды для привязки аккаунтов Dota 2"""
    
    def __init__(self, bot):
        self.bot = bot
        self.user_links_file = "data/user_links.json"
        # Используем импортированную функцию
        self.user_links = load_links_from_config(self.user_links_file)
        logger.info(f"Ког {self.__class__.__name__} загружен")

    def save_user_links(self) -> bool:
        """
        Сохраняет привязки аккаунтов в файл.
        
        Returns:
            bool: True, если сохранение прошло успешно
        """
        try:
            # Создаем папку, если её нет
            os.makedirs(os.path.dirname(self.user_links_file) or '.', exist_ok=True)
            
            # Проверяем и очищаем данные перед сохранением
            clean_data = {}
            for user_id, accounts in self.user_links.items():
                # Сохраняем только строки как ключи и списки как значения
                if isinstance(accounts, list) and accounts:
                    clean_data[str(user_id)] = accounts
            
            # Сначала записываем во временный файл
            temp_file = f"{self.user_links_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(clean_data, f, indent=4)
            
            # Затем безопасно переименовываем
            os.replace(temp_file, self.user_links_file)
            
            logger.info(f"Данные привязок аккаунтов сохранены в {self.user_links_file}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных привязок аккаунтов: {e}")
            return False

    async def send_response(self, ctx, message):
        """
        Отправляет приватный ответ в зависимости от типа контекста команды.
        
        Args:
            ctx: Контекст команды
            message: Сообщение для отправки
        """
        try:
            # Проверяем тип команды (slash или обычная)
            is_interaction = hasattr(ctx, 'interaction') and ctx.interaction is not None
            
            if is_interaction:
                # Для slash-команд
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(message, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(message, ephemeral=True)
            else:
                # Для обычных команд
                await ctx.send(message)
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа: {e}")
            # Запасной вариант - отправка в личку
            try:
                await ctx.author.send(message)
            except:
                logger.error(f"Не удалось отправить приватный ответ")
                try:
                    await ctx.send(message)
                except:
                    logger.error(f"Не удалось отправить ответ вообще")
    
    @commands.hybrid_command(description='Привязать аккаунт Dota 2')
    @command_error_handler
    async def link(self, ctx, player_id: int):
        """
        Привязывает аккаунт Dota 2 к Discord аккаунту.
        
        Args:
            ctx: Контекст команды
            player_id: ID игрока Dota 2 для привязки
        """
        # Для slash-команд делаем ответ приватным
        is_interaction = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)
        
        # Проверяем корректность ID
        if player_id <= 0:
            await self.send_response(ctx, f"ID игрока должен быть положительным числом.")
            return
            
        # Всегда используем строковый ID
        user_id = str(ctx.author.id)
        
        logger.info(f"Привязка аккаунта Dota 2 {player_id} к Discord ID {user_id}")
        
        # Если у пользователя еще нет привязок, создаем список
        if user_id not in self.user_links:
            self.user_links[user_id] = []
        
        # Проверяем, не привязан ли уже этот аккаунт
        if player_id in self.user_links[user_id]:
            await self.send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} уже привязан к вашему аккаунту Discord.")
            return
        
        # Проверяем лимит привязок (не более 5)
        if len(self.user_links[user_id]) >= 5:
            await self.send_response(ctx, "Вы достигли лимита в 5 привязанных аккаунтов. Отвяжите неиспользуемые аккаунты перед добавлением новых.")
            return
            
        # Добавляем аккаунт в список привязок
        self.user_links[user_id].append(player_id)
        
        # Сохраняем изменения
        success = self.save_user_links()
        
        if success:
            await self.send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} успешно привязан к вашему аккаунту Discord.")
            
            # Если это первый привязанный аккаунт, добавляем подсказку
            if len(self.user_links[user_id]) == 1:
                await self.send_response(ctx, "Теперь вы можете использовать команду `/lastmatch`, чтобы увидеть информацию о вашем последнем матче.")
            else:
                all_accounts = ", ".join(str(acc) for acc in self.user_links[user_id])
                await self.send_response(ctx, f"У вас привязано несколько аккаунтов: {all_accounts}. "+
                            "При использовании `/lastmatch` бот автоматически выберет аккаунт с самым последним матчем.")
        else:
            await self.send_response(ctx, "Произошла ошибка при сохранении привязки. Пожалуйста, попробуйте снова.")

    @commands.hybrid_command(description='Отвязать аккаунт Dota 2')
    @command_error_handler
    async def unlink(self, ctx, player_id: Optional[int] = None):
        """
        Отвязывает аккаунт Dota 2 от Discord аккаунта.
        
        Args:
            ctx: Контекст команды
            player_id: ID игрока Dota 2 для отвязки (опционально)
        """
        # Для slash-команд делаем ответ приватным
        is_interaction = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)
        
        # Всегда используем строковый ID
        user_id = str(ctx.author.id)
        
        logger.info(f"Отвязка аккаунта Dota 2 от Discord ID {user_id}. Player ID: {player_id}")
        
        # Проверяем, есть ли вообще привязки у пользователя
        if user_id not in self.user_links or not self.user_links[user_id]:
            await self.send_response(ctx, "У вас нет привязанных аккаунтов Dota 2.")
            return
        
        # Если указан конкретный ID для отвязки
        if player_id is not None:
            if player_id in self.user_links[user_id]:
                self.user_links[user_id].remove(player_id)
                save_success = self.save_user_links()
                
                if save_success:
                    await self.send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} успешно отвязан от вашего аккаунта Discord.")
                    
                    # Если остались другие аккаунты, показываем их
                    if self.user_links[user_id]:
                        remaining = ", ".join(str(acc) for acc in self.user_links[user_id])
                        await self.send_response(ctx, f"У вас остаются привязанными следующие аккаунты: {remaining}")
                else:
                    await self.send_response(ctx, "Произошла ошибка при сохранении изменений. Пожалуйста, попробуйте снова.")
            else:
                # Показываем список привязанных аккаунтов, если пользователь указал неверный ID
                accounts = ", ".join(str(acc) for acc in self.user_links[user_id])
                await self.send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} не привязан к вашему аккаунту Discord.\n"+
                            f"Ваши привязанные аккаунты: {accounts}")
        else:
            # Отвязываем все аккаунты
            self.user_links[user_id] = []
            save_success = self.save_user_links()
            
            if save_success:
                await self.send_response(ctx, f"Все аккаунты Dota 2 были успешно отвязаны от вашего аккаунта Discord.")
            else:
                await self.send_response(ctx, "Произошла ошибка при сохранении изменений. Пожалуйста, попробуйте снова.")

    @commands.hybrid_command(description='Показать привязанные аккаунты Dota 2')
    @command_error_handler
    async def links(self, ctx: commands.Context):
        """Показывает список Steam ID Dota 2, привязанных к вашему Discord аккаунту."""
        # Для slash-команд делаем ответ приватным и отложенным
        is_interaction = hasattr(ctx, 'interaction') and ctx.interaction is not None
        if is_interaction:
            await ctx.defer(ephemeral=True)
        
        # Получаем Discord ID автора команды
        user_id = str(ctx.author.id)
        
        logger.info(f"Запрос списка привязанных аккаунтов для Discord ID {user_id}.")
        
        # Проверяем наличие привязок
        if user_id in self.user_links and self.user_links[user_id]:
            # Формируем список ID для вывода
            linked_accounts = "\n".join(str(account_id) for account_id in self.user_links[user_id])
            await self.send_response(ctx, f"Ваши привязанные аккаунты Dota 2:\n{linked_accounts}")
            
            # Добавляем пояснение, если аккаунтов несколько
            if len(self.user_links[user_id]) > 1:
                await self.send_response(ctx, "При использовании команды `/lastmatch` бот автоматически выберет аккаунт с самым последним матчем.")
        else:
            # Если привязок нет
            await self.send_response(ctx, "У вас нет привязанных аккаунтов Dota 2. Используйте команду `/link PLAYER_ID`, чтобы привязать свой аккаунт.")

    # Этот метод используется другими когами (например, LastMatch) для доступа к данным привязок
    def get_user_links(self):
        """Возвращает словарь с привязками аккаунтов"""
        return self.user_links

async def setup(bot):
    await bot.add_cog(Links(bot))
