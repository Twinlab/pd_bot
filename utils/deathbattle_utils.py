# utils/deathbattle_utils.py
import asyncio
import random
import discord
import requests
from PIL import Image, ImageOps
from io import BytesIO
import logging
import os
from typing import Tuple, Optional

logger = logging.getLogger("bot")

# Данные для deathbattle - оптимизированы для лучшей читаемости
event_group_1 = [
    "**{attacker}** бьёт кулаком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** царапает **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** кусает **{defender}** и наносит **{damage}** урона!",
]

event_group_2 = [
    "**{attacker}** бросает бутылку в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** бьёт молотком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** брызгает кислотой в **{defender}** и наносит **{damage}** урона!",
]

event_group_3 = [
    "**{attacker}** бросает гранату в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** вскрывает ножом пузо **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** стреляет из пистолета в **{defender}** и наносит **{damage}** урона!",
]

event_group_4 = [
    "**{attacker}** ваншотит **{defender}**!",
]

def get_event_and_damage() -> Tuple[str, int]:
    """
    Выбирает событие и урон для deathbattle.
    
    Оптимизации:
    - Добавлена типизация
    - Улучшена читаемость кода
    
    Returns:
        Tuple[str, int]: Текст события и величина урона
    """
    event_group_chance = random.random()

    if event_group_chance <= 0.01:
        event = random.choice(event_group_4)
        damage = 100
    elif event_group_chance <= 0.41:
        event = random.choice(event_group_3)
        damage = random.randint(20, 30)
    elif event_group_chance <= 0.61:
        event = random.choice(event_group_2)
        damage = random.randint(10, 20)
    else:
        event = random.choice(event_group_1)
        damage = random.randint(1, 10)

    return event, damage

async def create_deathbattle_image(member1, member2) -> Optional[BytesIO]:
    """
    Создает изображение для deathbattle с аватарками участников.
    
    Оптимизации:
    - Добавлена типизация
    - Улучшена обработка ошибок
    - Использование более современного метода ресайза
    
    Args:
        member1: Первый участник
        member2: Второй участник
        
    Returns:
        Optional[BytesIO]: Буфер с изображением или None в случае ошибки
    """
    image_path = "deathbattle.jpg"
    
    # Проверяем существование файла
    if not os.path.exists(image_path):
        logger.error(f"Файл фона для deathbattle не найден: {image_path}")
        return None
        
    try:
        background = Image.open(image_path)
        avatar_size = (128, 128)

        # Загрузка аватарки первого участника
        member1_avatar_url = str(member1.display_avatar.url)
        response1 = requests.get(member1_avatar_url)
        member1_avatar = Image.open(BytesIO(response1.content))
        # Замена ANTIALIAS на LANCZOS для соответствия новой версии Pillow
        member1_avatar = ImageOps.fit(member1_avatar, avatar_size, Image.LANCZOS)

        # Загрузка аватарки второго участника
        member2_avatar_url = str(member2.display_avatar.url)
        response2 = requests.get(member2_avatar_url)
        member2_avatar = Image.open(BytesIO(response2.content))
        member2_avatar = ImageOps.fit(member2_avatar, avatar_size, Image.LANCZOS)

        # Расположение аватарок на фоне
        background.paste(member1_avatar, (20, 133)) 
        background.paste(member2_avatar, (241, 133)) 

        # Сохранение и возврат сформированного изображения
        image_buffer = BytesIO()
        background.save(image_buffer, "PNG")
        image_buffer.seek(0)
        return image_buffer
    except Exception as e:
        logger.error(f"Ошибка при создании изображения deathbattle: {e}", exc_info=True)
        return None

async def run_battle(ctx, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None):
    """
    Проводит смертельную битву между двумя участниками.
    
    Оптимизации:
    - Добавлена типизация
    - Улучшена обработка ошибок
    - Улучшено форматирование текста
    - Улучшение внешнего вида эмбедов
    
    Args:
        ctx: Контекст команды
        member1: Первый участник (опционально)
        member2: Второй участник (опционально)
    """
    try:
        # Если не указаны участники, используем автора и случайного участника
        if member1 is None and member2 is None:
            member1 = ctx.author
            members = [m for m in ctx.guild.members if m != ctx.author and not m.bot]
            if not members:
                await ctx.send("Недостаточно участников для битвы.")
                return
            member2 = random.choice(members)
        elif member2 is None:
            member2 = member1
            member1 = ctx.author

        # Создание изображения смертельной битвы с аватарками участников
        deathbattle_image = await create_deathbattle_image(member1, member2)
        if not deathbattle_image:
            await ctx.send("Не удалось создать изображение для битвы.")
            return

        battle_embed = discord.Embed(title=":crossed_swords: Смертельная битва!", color=0xFF0000)

        hp1 = 100
        hp2 = 100

        first_attacker = random.choice([True, False])

        battle_embed.add_field(name=f"**{member1.name}**", value=f"{hp1}/100", inline=True)
        battle_embed.add_field(name=f"**{member2.name}**", value=f"{hp2}/100", inline=True)
        
        file = discord.File(deathbattle_image, filename="deathbattle.png")
        battle_embed.set_image(url="attachment://deathbattle.png")
        battle_message = await ctx.send(file=file, embed=battle_embed)

        event_log = []

        while hp1 > 0 and hp2 > 0:
            await asyncio.sleep(2)
            event, damage = get_event_and_damage()

            if len(event_log) == 3:
                event_log.pop(0)

            if first_attacker:
                hp2 -= damage
                event_text = event.format(attacker=member1.name, defender=member2.name, damage=damage)
                event_log.append(event_text)
                first_attacker = False
            else:
                hp1 -= damage
                event_text = event.format(attacker=member2.name, defender=member1.name, damage=damage)
                event_log.append(event_text)
                first_attacker = True
            battle_embed = discord.Embed(
                title=":crossed_swords: Смертельная битва!",
                description='\n'.join(event_log),
                color=0xFF0000
            )
            
            # Форматирование строк здоровья с процентами для наглядности
            hp1_percent = max(0, hp1)
            hp2_percent = max(0, hp2)
            
            battle_embed.add_field(
                name=f"**{member1.name}**",
                value=f"{hp1_percent}/100 HP",
                inline=True
            )
            
            battle_embed.add_field(
                name=f"**{member2.name}**",
                value=f"{hp2_percent}/100 HP",
                inline=True
            )
            
            await battle_message.edit(embed=battle_embed)

        winner = member1.name if hp1 > hp2 else member2.name
        event_log.append(f":trophy: **{winner}** разъебал!")

        # Финальный эмбед с результатом битвы
        battle_embed = discord.Embed(
            title=":crossed_swords: Битва завершена!",
            description='\n'.join(event_log),
            color=discord.Color.gold()  # Меняем цвет для финального сообщения
        )
        
        battle_embed.add_field(
            name=f"**{member1.name}**",
            value=f"{max(0, hp1)}/100 HP",
            inline=True
        )
        
        battle_embed.add_field(
            name=f"**{member2.name}**",
            value=f"{max(0, hp2)}/100 HP",
            inline=True
        )
        
        await battle_message.edit(embed=battle_embed)
        
    except Exception as e:
        logger.error(f"Ошибка в deathbattle: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка при проведении битвы: {e}")