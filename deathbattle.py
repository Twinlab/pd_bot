import asyncio
import random
import discord
from discord import Embed
from discord.ext.commands import Cog, Context
import requests
from PIL import Image, ImageDraw, ImageOps
from io import BytesIO

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

def get_event_and_damage():
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

async def create_deathbattle_image(member1, member2):
    background = Image.open("deathbattle.jpg")
    avatar_size = (128, 128)

    # Загрузка аватарки первого участника
    member1_avatar_url = str(member1.display_avatar.url)
    response1 = requests.get(member1_avatar_url)
    member1_avatar = Image.open(BytesIO(response1.content))
    member1_avatar = ImageOps.fit(member1_avatar, avatar_size, Image.ANTIALIAS)

    # Загрузка аватарки второго участника
    member2_avatar_url = str(member2.display_avatar.url)
    response2 = requests.get(member2_avatar_url)
    member2_avatar = Image.open(BytesIO(response2.content))
    member2_avatar = ImageOps.fit(member2_avatar, avatar_size, Image.ANTIALIAS)

    # Расположение аватарок на фоне
    background.paste(member1_avatar, (20, 133)) 
    background.paste(member2_avatar, (241, 133)) 

    # Сохранение и возврат сформированного изображения
    image_buffer = BytesIO()
    background.save(image_buffer, "PNG")
    image_buffer.seek(0)
    return image_buffer

async def handle_deathbattle(ctx: Context, member1=None, member2=None):
    if member1 is None and member2 is None:
        author = ctx.author
        member1 = author
        member2 = random.choice([m for m in ctx.guild.members])
    elif member2 is None:
        author = ctx.author
        member2 = member1
        member1 = author
    elif member1 is None:
        member1 = ctx.author

    # Создание изображения смертельной битвы с аватарками участников
    deathbattle_image = await create_deathbattle_image(member1, member2)

    battle_embed = Embed(title=":crossed_swords: Смертельная битва!", color=0xFF0000)

    hp1 = 100
    hp2 = 100

    first_attacker = random.choice([True, False])

    battle_embed.add_field(name=f"**{member1.display_name}**", value=f"{hp1}/100", inline=True)
    battle_embed.add_field(name=f"**{member2.display_name}**", value=f"{hp2}/100", inline=True)
    
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
            event_text = event.format(attacker=member1.display_name, defender=member2.display_name, damage=damage)
            event_log.append(event_text)
            first_attacker = False
        else:
            hp1 -= damage
            event_text = event.format(attacker=member2.display_name, defender=member1.display_name, damage=damage)
            event_log.append(event_text)
            first_attacker = True

        battle_embed = Embed(title=":crossed_swords: Смертельная битва!", description='\n'.join(event_log), color=0xFF0000)
        battle_embed.add_field(name=f"**{member1.display_name}**", value=f"{max(0, hp1)}/100", inline=True)
        battle_embed.add_field(name=f"**{member2.display_name}**", value=f"{max(0, hp2)}/100", inline=True)
        await battle_message.edit(embed=battle_embed)

    winner = member1.display_name if hp1 > hp2 else member2.display_name
    event_log.append(f":trophy: **{winner}** разъебал!")

    battle_embed = Embed(title=":crossed_swords: Смертельная битва!", description='\n'.join(event_log), color=0xFF0000)
    battle_embed.add_field(name=f"{member1.display_name}", value=f"{max(0, hp1)}/100", inline=True)
    battle_embed.add_field(name=f"{member2.display_name}", value=f"{max(0, hp2)}/100", inline=True)
    await battle_message.edit(embed=battle_embed)

