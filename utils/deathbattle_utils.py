import asyncio
import random
import discord
import aiohttp 
from PIL import Image, ImageOps
from io import BytesIO
import logging
import os
from typing import Tuple, Optional
from discord.ext import commands

logger = logging.getLogger("bot")

# Списки возможных событий для разных уровней урона в deathbattle
event_group_1 = [ # Низкий урон
    "**{attacker}** бьёт кулаком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** царапает **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** кусает **{defender}** и наносит **{damage}** урона!",
]

event_group_2 = [ # Средний урон
    "**{attacker}** бросает бутылку в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** бьёт молотком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** брызгает кислотой в **{defender}** и наносит **{damage}** урона!",
]

event_group_3 = [ # Высокий урон
    "**{attacker}** бросает гранату в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** вскрывает ножом пузо **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** стреляет из пистолета в **{defender}** и наносит **{damage}** урона!",
]

event_group_4 = [ # Летальный урон (ваншот)
    "**{attacker}** ваншотит **{defender}**!",
]

def get_event_and_damage() -> Tuple[str, int]:
    """
    Случайным образом выбирает текстовое событие и соответствующий ему урон
    для одного хода в deathbattle, основываясь на вероятностях.

    Returns:
        Кортеж (текст_события, урон).
    """
    # Определяем вероятность для выбора группы событий
    event_group_chance = random.random()

    # Выбираем группу событий и урон в зависимости от вероятности
    if event_group_chance <= 0.01: # 1% шанс на ваншот
        event = random.choice(event_group_4)
        damage = 100 # Урон для ваншота
    elif event_group_chance <= 0.41: # 40% шанс на высокий урон
        event = random.choice(event_group_3)
        damage = random.randint(20, 30) # Диапазон высокого урона
    elif event_group_chance <= 0.61: # 20% шанс на средний урон
        event = random.choice(event_group_2)
        damage = random.randint(10, 20) # Диапазон среднего урона
    else: # Оставшиеся ~39% шанс на низкий урон
        event = random.choice(event_group_1)
        damage = random.randint(1, 10) # Диапазон низкого урона

    return event, damage

async def create_deathbattle_image(member1: discord.Member, member2: discord.Member) -> Optional[BytesIO]:
    """
    Создает изображение для deathbattle, накладывая аватары участников
    на фоновое изображение 'deathbattle.jpg'.

    Args:
        member1: Первый участник.
        member2: Второй участник.
        
    Returns:
        Optional[BytesIO]: BytesIO буфер с PNG-изображением или None в случае ошибки.
    """
    # Путь к фоновому изображению (относительно корня проекта)
    image_path = "deathbattle.jpg"
    
    # Проверяем наличие фонового файла
    if not os.path.exists(image_path):
        logger.error(f"Файл фона для deathbattle не найден: {image_path}")
        return None
        
    try:
        # Открываем фоновое изображение
        background = Image.open(image_path)
        avatar_size = (128, 128) # Размер аватаров на изображении
 
        # Загрузка и обработка аватарки первого участника
        # Используем aiohttp для асинхронной загрузки
        async with aiohttp.ClientSession() as session:
            # Загрузка аватара 1
            member1_avatar_url = str(member1.display_avatar.replace(size=128, format='png').url) # Запрашиваем нужный размер и формат
            async with session.get(member1_avatar_url) as resp1:
                resp1.raise_for_status() # Проверка на ошибки HTTP
                avatar1_data = await resp1.read()
                member1_avatar = Image.open(BytesIO(avatar1_data))

            # Загрузка аватара 2
            member2_avatar_url = str(member2.display_avatar.replace(size=128, format='png').url)
            async with session.get(member2_avatar_url) as resp2:
                resp2.raise_for_status()
                avatar2_data = await resp2.read()
                member2_avatar = Image.open(BytesIO(avatar2_data))
 
        # Накладываем аватары на фон в заданных координатах
        background.paste(member1_avatar, (20, 133)) # Координаты для левого аватара
        background.paste(member2_avatar, (241, 133)) # Координаты для правого аватара
 
        # Сохраняем результат в буфер BytesIO в формате PNG
        image_buffer = BytesIO()
        background.save(image_buffer, "PNG")
        image_buffer.seek(0) # Перемещаем указатель в начало буфера
        return image_buffer
    except aiohttp.ClientError as http_err: # Ловим ошибки aiohttp
         logger.error(f"Ошибка HTTP при загрузке аватара для deathbattle: {http_err}")
         return None
    except Exception as e:
        logger.error(f"Ошибка при создании изображения deathbattle: {e}", exc_info=True)
        return None

async def run_battle(ctx: commands.Context, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None): # Используем commands.Context
    """
    Основная функция для команды /deathbattle.
    Симулирует пошаговую битву между двумя участниками, обновляя сообщение
    с ходом битвы и изображением.

    Args:
        ctx: Контекст команды.
        member1: Первый участник (если None, используется автор команды).
        member2: Второй участник (если None, выбирается случайно).
    """
    # Определение участников битвы
    if member1 is None and member2 is None:
        # Если не указан ни один участник, бьется автор и случайный участник сервера
        member1 = ctx.author
        # Собираем список возможных оппонентов (все, кроме автора и ботов)
        members = [m for m in ctx.guild.members if m != ctx.author and not m.bot]
        if not members:
            await ctx.send("На сервере больше никого нет для битвы!")
            return
        member2 = random.choice(members)
    elif member2 is None:
        # Если указан только member1, он бьется с автором команды
        member2 = member1
        member1 = ctx.author
 
    # Генерируем изображение для битвы
    deathbattle_image = await create_deathbattle_image(member1, member2)
    if not deathbattle_image:
        await ctx.send("Не удалось создать изображение для битвы (ошибка загрузки аватара?).")
        return
 
    # Создаем начальный эмбед битвы
    battle_embed = discord.Embed(title=":crossed_swords: Смертельная битва!", color=discord.Color.red())
 
    # Начальное здоровье участников
    hp1 = 100
    hp2 = 100
 
    # Случайно определяем, кто атакует первым
    first_attacker = random.choice([True, False])
 
    # Добавляем поля со здоровьем в начальный эмбед
    battle_embed.add_field(name=f"**{member1.name}**", value=f"{hp1}/100 HP", inline=True)
    battle_embed.add_field(name=f"**{member2.name}**", value=f"{hp2}/100 HP", inline=True)
        
    # Подготавливаем файл изображения для отправки
    file = discord.File(deathbattle_image, filename="deathbattle.png")
    battle_embed.set_image(url="attachment://deathbattle.png") # Устанавливаем изображение в эмбед
    # Отправляем начальное сообщение с изображением и эмбедом
    battle_message = await ctx.send(file=file, embed=battle_embed)
 
    event_log = [] # Лог последних событий битвы (максимум 3)
 
    # Основной цикл битвы (пока оба участника живы)
    while hp1 > 0 and hp2 > 0:
        await asyncio.sleep(2) # Пауза между ходами
        # Получаем случайное событие и урон для этого хода
        event, damage = get_event_and_damage()
 
        # Ограничиваем лог событий последними 3 записями
        if len(event_log) >= 3:
            event_log.pop(0) # Удаляем самое старое событие
 
        # Определяем атакующего и защищающегося, обновляем здоровье
        if first_attacker:
            hp2 -= damage
            event_text = event.format(attacker=member1.name, defender=member2.name, damage=damage)
            event_log.append(event_text)
            first_attacker = False # Передаем ход другому участнику
        else:
            hp1 -= damage
            event_text = event.format(attacker=member2.name, defender=member1.name, damage=damage)
            event_log.append(event_text)
            first_attacker = True # Передаем ход другому участнику
                
        # Создаем обновленный эмбед с логом событий
        battle_embed = discord.Embed(
            title=":crossed_swords: Смертельная битва!",
            description='\n'.join(event_log),
            color=discord.Color.red()
        )
            
        # Добавляем актуальное здоровье участников (не позволяем уйти в минус)
        hp1_display = max(0, hp1)
        hp2_display = max(0, hp2)
            
        battle_embed.add_field(
            name=f"**{member1.name}**",
            value=f"{hp1_display}/100 HP",
            inline=True
        )
            
        battle_embed.add_field(
            name=f"**{member2.name}**",
            value=f"{hp2_display}/100 HP",
            inline=True
        )
            
        # Редактируем сообщение, обновляя эмбед
        try:
            await battle_message.edit(embed=battle_embed)
        except discord.NotFound:
             logger.warning("Сообщение deathbattle не найдено для редактирования (возможно, удалено).")
             break # Прерываем битву, если сообщение удалено
        except Exception as edit_err:
             logger.error(f"Ошибка при редактировании сообщения deathbattle: {edit_err}")
             break # Прерываем битву при ошибке редактирования
 
    # Определяем победителя после завершения цикла
    # Проверяем, не закончилась ли битва из-за ошибки редактирования
    if hp1 <= 0 or hp2 <= 0:
        winner = member1.name if hp1 > 0 else member2.name # Тот, у кого осталось здоровье
        event_log.append(f"\n:trophy: **{winner}** победил(а)!") # Добавляем финальное сообщение в лог
 
        # Создаем финальный эмбед с результатами
        final_embed = discord.Embed(
            title=":crossed_swords: Битва завершена!",
            description='\n'.join(event_log),
            color=discord.Color.gold()  # Меняем цвет для финального сообщения
        )
        
        final_embed.add_field(
            name=f"**{member1.name}**",
            value=f"{max(0, hp1)}/100 HP", # Отображаем здоровье не ниже 0
            inline=True
        )
        
        final_embed.add_field(
            name=f"**{member2.name}**",
            value=f"{max(0, hp2)}/100 HP", # Отображаем здоровье не ниже 0
            inline=True
        )
        
        # Редактируем сообщение последний раз, показывая финальный результат
        try:
            await battle_message.edit(embed=final_embed)
        except discord.NotFound:
             logger.warning("Сообщение deathbattle не найдено для финального редактирования.")
        except Exception as final_edit_err:
             logger.error(f"Ошибка при финальном редактировании сообщения deathbattle: {final_edit_err}")
