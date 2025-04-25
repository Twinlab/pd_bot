import discord
from discord.ext import commands
import asyncio
import logging
import re
from typing import Optional, Set, Dict, Union
import random
from datetime import datetime, timedelta

# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

class Giveaway(commands.Cog):
    """Ког для создания и управления розыгрышами в Discord."""
    
    def __init__(self, bot):
        """Инициализирует ког и словарь для отслеживания активных розыгрышей."""
        self.bot = bot
        # Словарь для хранения задач asyncio, отслеживающих активные розыгрыши {message_id: task}
        self.active_giveaways: Dict[int, asyncio.Task] = {}
        logger.info(f"Ког {self.__class__.__name__} загружен")
    
    def cog_unload(self):
        """Вызывается при выгрузке кога, отменяет все активные задачи розыгрышей."""
        logger.info("Отмена активных задач розыгрышей...")
        for giveaway_id, task in self.active_giveaways.items():
            if not task.done():
                task.cancel()
        logger.info(f"Ког {self.__class__.__name__} выгружен, активные розыгрыши отменены")
    
    @commands.hybrid_command(description='Создать розыгрыш')
    @command_error_handler
    async def giveaway(self, ctx: commands.Context, duration: str, *, description: str):
        """
        Создает новое сообщение-розыгрыш.

        Пользователи могут участвовать, нажимая на реакцию 🎉.
        По истечении времени бот автоматически выбирает победителя.

        Args:
            ctx: Контекст команды
            duration: Длительность розыгрыша в формате (например: 1h30m)
            description: Описание розыгрыша
        """
        # Проверяем максимальную длину описания (ограничение Discord для эмбедов)
        if len(description) > 4000:
            await ctx.send("Описание розыгрыша слишком длинное (максимум 4000 символов).")
            return
                
        # Преобразуем строку длительности (напр., "1h30m") в секунды
        duration_seconds = await self.parse_duration(duration)
            
        if duration_seconds is None:
            await ctx.send("Неверный формат времени. Используйте 's' для секунд, 'm' для минут и 'h' для часов. Например: 1h30m")
            return
                
        # Проверка минимальной длительности
        if duration_seconds < 10:
            await ctx.send("Минимальная длительность розыгрыша - 10 секунд.")
            return
                
        # Проверка максимальной длительности (7 дней)
        if duration_seconds > 7 * 24 * 3600:
            await ctx.send("Максимальная длительность розыгрыша - 7 дней.")
            return
            
        # Рассчитываем точное время окончания розыгрыша
        end_time = datetime.now() + timedelta(seconds=duration_seconds)
        formatted_end_time = end_time.strftime("%d.%m.%Y %H:%M:%S")
            
        # Создаем эмбед-сообщение для розыгрыша
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
            
        # Устанавливаем футер с информацией о создателе и времени окончания
        embed.set_footer(
            text=f"Розыгрыш создан {ctx.author.name} | Заканчивается {formatted_end_time}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
        )
            
        # Отправляем сообщение с эмбедом в текущий канал
        giveaway_message = await ctx.send(embed=embed)
            
        # Добавляем реакцию "🎉", чтобы пользователи могли участвовать
        await giveaway_message.add_reaction("🎉")
            
        # Создаем фоновую задачу asyncio для ожидания окончания розыгрыша
        task = asyncio.create_task(
            self.wait_and_collect_reactions(ctx, giveaway_message, duration_seconds, end_time)
        )
            
        # Сохраняем задачу в словарь активных розыгрышей по ID сообщения
        self.active_giveaways[giveaway_message.id] = task
            
        logger.info(f"Создан розыгрыш (ID: {giveaway_message.id}), длительность: {self.format_duration(duration_seconds)}")

    async def wait_and_collect_reactions(self, ctx: commands.Context, giveaway_message: discord.Message, duration_seconds: int, end_time: datetime):
        """
        Асинхронная задача, ожидающая окончания розыгрыша.
        После ожидания собирает участников по реакциям, выбирает победителя,
        обновляет исходное сообщение и отправляет результаты.

        Args:
            ctx: Контекст команды
            giveaway_message: Сообщение с розыгрышем
            duration_seconds: Длительность в секундах
            end_time: Время окончания.
        """
        try:
            # Приостанавливаем выполнение задачи до окончания розыгрыша
            await asyncio.sleep(duration_seconds)
            
            # Получаем актуальную версию сообщения с реакциями
            try:
                message = await ctx.channel.fetch_message(giveaway_message.id)
            except discord.NotFound:
                logger.warning(f"Сообщение розыгрыша {giveaway_message.id} не найдено, возможно удалено")
                # Удаляем из активных
                self.active_giveaways.pop(giveaway_message.id, None)
                return
            
            # Собираем список пользователей (не ботов), нажавших на реакцию 🎉
            participants: List[discord.User] = []
            for reaction in message.reactions:
                if str(reaction.emoji) == "🎉":
                    async for user in reaction.users():
                        if not user.bot:  # Исключаем ботов
                            participants.append(user)
            
            # Подготавливаем эмбед с результатами
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
            
            # Редактируем исходное сообщение розыгрыша, заменяя его эмбедом с результатами
            await message.edit(embed=embed)
            
            # Отправляем отдельное сообщение в канал с упоминанием победителя (если он есть)
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
            
            # Отправляем список участников и победителя организатору в личные сообщения
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
            
            # Удаляем задачу из словаря активных розыгрышей
            self.active_giveaways.pop(giveaway_message.id, None)
            
            logger.info(f"Розыгрыш {giveaway_message.id} завершен. Победитель: {winner.name if participants else 'Нет'}. Участников: {participants_count}")
            
        except asyncio.CancelledError:
            # Задача была отменена (например, при выгрузке кога)
            logger.info(f"Розыгрыш {giveaway_message.id} был отменен")
            # Ничего не делаем, просто логируем отмену
        except Exception as e:
            # Логируем непредвиденную ошибку при завершении розыгрыша
            logger.error(f"Ошибка в wait_and_collect_reactions для розыгрыша {giveaway_message.id}: {e}", exc_info=True)
            try:
                await ctx.send("Произошла ошибка при завершении розыгрыша.")
            except:
                pass # Игнорируем ошибки при отправке сообщения об ошибке
            
            # В любом случае удаляем задачу из активных при ошибке
            self.active_giveaways.pop(giveaway_message.id, None)
    
    # --- Вспомогательные статические методы ---
    
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
            int: Общее количество секунд или None при неверном формате.
        """
        # Приводим к нижнему регистру и убираем пробелы по краям
        duration_str = duration_str.lower().strip()
        
        # Регулярное выражение для проверки формата (только цифры и h/m/s)
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
        Форматирует количество секунд в строку вида "Xч Yм Zс".

        Args:
            seconds: Длительность в секундах
            
        Returns:
            str: Отформатированная строка (например, "1ч 30м", "45м", "10с").
        """
        if seconds <= 0:
             return "0с"
             
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        # Добавляем секунды, только если нет часов и минут, или если они не равны нулю
        if seconds > 0 or not parts:
            parts.append(f"{seconds}с")
        
        return " ".join(parts)

async def setup(bot):
    await bot.add_cog(Giveaway(bot))
