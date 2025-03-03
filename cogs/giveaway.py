# cogs/giveaway.py - оптимизированная версия
import discord
from discord.ext import commands
import asyncio
import logging
import re
from typing import Optional, Set, Dict, Union
import random
from datetime import datetime, timedelta

logger = logging.getLogger("bot")

class Giveaway(commands.Cog):
    """Команды для проведения розыгрышей"""
    
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways: Dict[int, asyncio.Task] = {}  # Отслеживание активных розыгрышей
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    def cog_unload(self):
        """Отменяет все активные задачи при выгрузке кога"""
        for giveaway_id, task in self.active_giveaways.items():
            if not task.done():
                task.cancel()
        logger.info(f"Ког {self.__class__.__name__} выгружен, активные розыгрыши отменены")
    
    @commands.hybrid_command(description='Создать розыгрыш')
    async def giveaway(self, ctx, duration: str, *, description: str):
        """
        Создает розыгрыш с указанной длительностью и описанием.
        
        Args:
            ctx: Контекст команды
            duration: Длительность розыгрыша в формате (например: 1h30m)
            description: Описание розыгрыша
        """
        try:
            # Проверяем длину описания
            if len(description) > 4000:
                await ctx.send("Описание розыгрыша слишком длинное (максимум 4000 символов).")
                return
                
            # Парсим длительность
            duration_seconds = await self.parse_duration(duration)
            
            if duration_seconds is None:
                await ctx.send("Неверный формат времени. Используйте 's' для секунд, 'm' для минут и 'h' для часов. Например: 1h30m")
                return
                
            if duration_seconds < 10:
                await ctx.send("Минимальная длительность розыгрыша - 10 секунд.")
                return
                
            if duration_seconds > 7 * 24 * 3600:  # 7 дней
                await ctx.send("Максимальная длительность розыгрыша - 7 дней.")
                return
            
            # Рассчитываем время окончания
            end_time = datetime.now() + timedelta(seconds=duration_seconds)
            formatted_end_time = end_time.strftime("%d.%m.%Y %H:%M:%S")
            
            # Создаем эмбед с информацией о розыгрыше
            embed = discord.Embed(
                title="🎉 Розыгрыш",
                description=description,
                color=discord.Color.green()
            )
            
            # Добавляем поля с информацией
            embed.add_field(
                name="Организатор",
                value=ctx.author.mention,
                inline=True
            )
            
            embed.add_field(
                name="Длительность",
                value=self.format_duration(duration_seconds),
                inline=True
            )
            
            embed.add_field(
                name="Окончание",
                value=f"<t:{int(end_time.timestamp())}:R>",  # Относительное время в формате Discord
                inline=True
            )
            
            embed.set_footer(
                text=f"Розыгрыш создан {ctx.author.name} | Заканчивается {formatted_end_time}",
                icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
            )
            
            # Отправляем сообщение
            giveaway_message = await ctx.send(embed=embed)
            
            # Добавляем реакцию для участия
            await giveaway_message.add_reaction("🎉")
            
            # Создаем и запускаем задачу для отслеживания розыгрыша
            task = asyncio.create_task(
                self.wait_and_collect_reactions(ctx, giveaway_message, duration_seconds, end_time)
            )
            
            # Сохраняем ссылку на задачу
            self.active_giveaways[giveaway_message.id] = task
            
            logger.info(f"Создан розыгрыш с ID {giveaway_message.id}, длительность: {self.format_duration(duration_seconds)}")
            
        except Exception as e:
            logger.error(f"Ошибка при создании розыгрыша: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при создании розыгрыша: {e}")
    
    async def wait_and_collect_reactions(self, ctx, giveaway_message, duration_seconds, end_time):
        """
        Ожидает окончания розыгрыша и собирает реакции участников.
        
        Args:
            ctx: Контекст команды
            giveaway_message: Сообщение с розыгрышем
            duration_seconds: Длительность в секундах
            end_time: Время окончания
        """
        try:
            # Ожидаем указанное время
            await asyncio.sleep(duration_seconds)
            
            # Получаем обновленное сообщение
            try:
                message = await ctx.channel.fetch_message(giveaway_message.id)
            except discord.NotFound:
                logger.warning(f"Сообщение розыгрыша {giveaway_message.id} не найдено, возможно удалено")
                # Удаляем из активных
                self.active_giveaways.pop(giveaway_message.id, None)
                return
            
            # Собираем участников
            participants = []
            for reaction in message.reactions:
                if str(reaction.emoji) == "🎉":
                    async for user in reaction.users():
                        if not user.bot:  # Исключаем ботов
                            participants.append(user)
            
            # Формируем результаты
            participants_count = len(participants)
            embed = discord.Embed(
                title="🎉 Розыгрыш завершен!",
                description=message.embeds[0].description if message.embeds else "Описание недоступно",
                color=discord.Color.gold()
            )
            
            # Выбираем победителя, если есть участники
            if participants:
                winner = random.choice(participants)
                embed.add_field(
                    name="Победитель",
                    value=f"{winner.mention} ({winner.name})",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Победитель",
                    value="Никто не участвовал в розыгрыше 😢",
                    inline=False
                )
            
            embed.add_field(
                name="Участников",
                value=str(participants_count),
                inline=True
            )
            
            embed.add_field(
                name="Организатор",
                value=ctx.author.mention,
                inline=True
            )
            
            embed.set_footer(
                text=f"Розыгрыш завершен | ID: {giveaway_message.id}",
                icon_url=self.bot.user.avatar.url if self.bot.user.avatar else self.bot.user.default_avatar.url
            )
            
            # Обновляем сообщение
            await message.edit(embed=embed)
            
            # Отправляем уведомление в канал
            if participants:
                await ctx.channel.send(
                    f"🎉 Розыгрыш завершен! Поздравляем {winner.mention}, вы победили!" +
                    f"\nСсылка на розыгрыш: {message.jump_url}"
                )
            else:
                await ctx.channel.send(
                    f"🎉 Розыгрыш завершен, но никто не принял участие." +
                    f"\nСсылка на розыгрыш: {message.jump_url}"
                )
            
            # Отправляем список участников организатору
            if participants:
                participants_list = "\n".join([f"{i+1}. {user.name} ({user.id})" for i, user in enumerate(participants)])
                
                # Разбиваем список на части, если он слишком длинный
                max_length = 1900  # Немного меньше лимита Discord в 2000 символов
                chunks = [participants_list[i:i+max_length] for i in range(0, len(participants_list), max_length)]
                
                await ctx.author.send(f"**Список участников розыгрыша (всего {participants_count}):**")
                for chunk in chunks:
                    await ctx.author.send(f"```\n{chunk}\n```")
                
                if participants:
                    await ctx.author.send(f"**Победитель: {winner.name} ({winner.id})**")
            else:
                await ctx.author.send("В вашем розыгрыше никто не принял участие.")
            
            # Удаляем из активных
            self.active_giveaways.pop(giveaway_message.id, None)
            
            logger.info(f"Розыгрыш {giveaway_message.id} завершен. Участников: {participants_count}")
            
        except asyncio.CancelledError:
            logger.info(f"Розыгрыш {giveaway_message.id} был отменен")
            # Не делаем ничего, задача была отменена
        except Exception as e:
            logger.error(f"Ошибка при завершении розыгрыша: {e}", exc_info=True)
            try:
                await ctx.send("Произошла ошибка при завершении розыгрыша.")
            except:
                pass
            
            # Удаляем из активных
            self.active_giveaways.pop(giveaway_message.id, None)
    
    @staticmethod
    async def parse_duration(duration_str: str) -> Optional[int]:
        """
        Преобразует строку с продолжительностью в секунды.
        
        Поддерживаемые форматы:
        - 1h30m
        - 1h30m20s
        - 30m
        - 60s
        
        Args:
            duration_str: Строка с продолжительностью
            
        Returns:
            int: Количество секунд или None, если не удалось распарсить
        """
        # Удаляем пробелы
        duration_str = duration_str.lower().strip()
        
        # Проверяем с помощью регулярного выражения
        pattern = r'^(\d+[hms])+$'
        if not re.match(pattern, duration_str):
            return None
        
        seconds = 0
        time_units = {'s': 1, 'm': 60, 'h': 3600}
        
        # Ищем все вхождения цифр с единицей измерения
        matches = re.findall(r'(\d+)([hms])', duration_str)
        
        for value_str, unit in matches:
            try:
                value = int(value_str)
                if value < 0:
                    return None
                seconds += value * time_units[unit]
            except ValueError:
                return None
        
        return seconds if seconds > 0 else None
    
    @staticmethod
    def format_duration(seconds: int) -> str:
        """
        Форматирует длительность в секундах в удобочитаемую строку.
        
        Args:
            seconds: Длительность в секундах
            
        Returns:
            str: Отформатированная строка (например, "1ч 30м 20с")
        """
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if hours:
            parts.append(f"{hours}ч")
        if minutes:
            parts.append(f"{minutes}м")
        if seconds or not parts:  # Добавляем секунды, если нет часов и минут
            parts.append(f"{seconds}с")
        
        return " ".join(parts)

async def setup(bot):
    await bot.add_cog(Giveaway(bot))