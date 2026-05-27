"""Утилиты для функционала "Смертельной битвы" между пользователями Discord.

Этот модуль предоставляет функции для симуляции пошаговой битвы между двумя участниками,
включая генерацию случайных событий, создание изображений с аватарами участников
и обновление сообщений с ходом битвы.
"""

import asyncio
import logging
import os
import random
from io import BytesIO
from typing import cast

import aiohttp
import discord
from discord.ext import commands
from PIL import Image

logger = logging.getLogger("bot.utils.deathbattle_utils")

# Шарим одну aiohttp-сессию между вызовами — каждый раз создавать новую дорого
# (новый TCP-handshake и FD на каждую битву).
_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None


def _get_session_lock() -> asyncio.Lock:
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _get_session_lock():
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5))
    return _session


async def close_session() -> None:
    """Закрывает шаренную aiohttp-сессию (при выгрузке кога)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


def _compose_image(background_bytes: bytes, avatar1: bytes, avatar2: bytes) -> bytes:
    """Синхронная PIL-сборка. Вызывается через asyncio.to_thread."""
    background = Image.open(BytesIO(background_bytes))
    m1 = Image.open(BytesIO(avatar1))
    m2 = Image.open(BytesIO(avatar2))
    background.paste(m1, (20, 133))
    background.paste(m2, (241, 133))
    buf = BytesIO()
    background.save(buf, "PNG")
    return buf.getvalue()


# Списки возможных событий для разных уровней урона в deathbattle
event_group_1 = [  # Низкий урон
    "**{attacker}** бьёт кулаком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** царапает **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** кусает **{defender}** и наносит **{damage}** урона!",
]

event_group_2 = [  # Средний урон
    "**{attacker}** бросает бутылку в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** бьёт молотком **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** брызгает кислотой в **{defender}** и наносит **{damage}** урона!",
]

event_group_3 = [  # Высокий урон
    "**{attacker}** бросает гранату в **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** вскрывает ножом пузо **{defender}** и наносит **{damage}** урона!",
    "**{attacker}** стреляет из пистолета в **{defender}** и наносит **{damage}** урона!",
]

event_group_4 = [  # Летальный урон (ваншот)
    "**{attacker}** ваншотит **{defender}**!",
]


def get_event_and_damage() -> tuple[str, int]:
    """Случайным образом выбирает текстовое событие и соответствующий ему урон для одного хода.

    Основывается на вероятностях из конфигурации.

    Returns:
        Кортеж (текст_события, урон).
    """
    # Получаем настройки
    from config.settings import get_settings

    settings = get_settings()
    damage_config = settings.fun.deathbattle.damage

    # Определяем вероятность для выбора группы событий
    event_group_chance = random.random()

    # Выбираем группу событий и урон в зависимости от вероятности
    if event_group_chance <= damage_config.oneshot_chance:  # Шанс на ваншот
        event = random.choice(event_group_4)
        damage = damage_config.oneshot_damage
    elif event_group_chance <= damage_config.high_damage_chance:  # Шанс на высокий урон
        event = random.choice(event_group_3)
        damage = random.randint(damage_config.high_damage_min, damage_config.high_damage_max)
    elif event_group_chance <= damage_config.medium_damage_chance:  # Шанс на средний урон
        event = random.choice(event_group_2)
        damage = random.randint(damage_config.medium_damage_min, damage_config.medium_damage_max)
    else:  # Оставшийся шанс на низкий урон
        event = random.choice(event_group_1)
        damage = random.randint(damage_config.low_damage_min, damage_config.low_damage_max)

    return event, damage


async def create_deathbattle_image(
    member1: discord.Member, member2: discord.Member
) -> BytesIO | None:
    """Создает изображение для deathbattle, накладывая аватары участников на фон.

    Фоновое изображение 'assets/deathbattle.jpg'.

    Args:
        member1: Первый участник.
        member2: Второй участник.

    Returns:
        BytesIO | None: BytesIO буфер с PNG-изображением или None в случае ошибки.
    """
    # Путь к фоновому изображению (относительно корня проекта)
    image_path = "assets/deathbattle.jpg"

    # Проверяем наличие фонового файла
    if not os.path.exists(image_path):
        logger.error(f"Файл фона для deathbattle не найден: {image_path}")
        return None

    try:
        from config.settings import get_settings

        avatar_size = get_settings().fun.deathbattle.avatar_size

        # Фон читаем с диска в потоке — PIL не любит async.
        background_bytes = await asyncio.to_thread(_read_file_bytes, image_path)

        member1_url = str(member1.display_avatar.replace(size=avatar_size, format="png").url)
        member2_url = str(member2.display_avatar.replace(size=avatar_size, format="png").url)

        session = await _get_session()
        avatar1_data, avatar2_data = await asyncio.gather(
            _fetch_bytes(session, member1_url),
            _fetch_bytes(session, member2_url),
        )

        # Сборка изображения в отдельном потоке — PIL блокирует event loop.
        png_bytes = await asyncio.to_thread(
            _compose_image, background_bytes, avatar1_data, avatar2_data
        )
        return BytesIO(png_bytes)
    except aiohttp.ClientError as http_err:
        logger.error(f"Ошибка HTTP при загрузке аватара для deathbattle: {http_err}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при создании изображения deathbattle: {e}", exc_info=True)
        return None


def _read_file_bytes(path: str) -> bytes:
    """Синхронное чтение файла (в потоке)."""
    with open(path, "rb") as f:
        return f.read()


async def _fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    """Загружает байты по URL с проверкой статуса."""
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.read()


async def run_battle(
    ctx: commands.Context,
    member1: discord.Member | None = None,
    member2: discord.Member | None = None,
) -> None:
    """Основная функция для команды /deathbattle.

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
        member1 = cast(discord.Member, ctx.author)  # Приводим тип к Member
        # Проверяем, что guild не None
        if ctx.guild is None:
            await ctx.send("Эта команда работает только на серверах!")
            return
        # Собираем список возможных оппонентов (все, кроме автора и ботов)
        members = [m for m in ctx.guild.members if m != ctx.author and not m.bot]
        if not members:
            await ctx.send("На сервере больше никого нет для битвы!")
            return
        member2 = random.choice(members)
    elif member2 is None:
        # Если указан только member1, он бьется с автором команды
        if member1 is not None:
            member2 = member1
            member1 = cast(discord.Member, ctx.author)  # Приводим тип к Member
        else:
            await ctx.send("Не удалось определить участников битвы!")
            return

    # Проверяем, что оба участника не None
    if member1 is None or member2 is None:
        await ctx.send("Не удалось определить участников битвы!")
        return

    # Генерируем изображение для битвы
    deathbattle_image = await create_deathbattle_image(member1, member2)
    if not deathbattle_image:
        await ctx.send("Не удалось создать изображение для битвы (ошибка загрузки аватара?).")
        return

    # Создаем начальный эмбед битвы
    battle_embed = discord.Embed(
        title=":crossed_swords: Смертельная битва!", color=discord.Color.red()
    )

    # Получаем настройки
    from config.settings import get_settings

    settings = get_settings()
    battle_config = settings.fun.deathbattle

    # Начальное здоровье участников
    hp1 = battle_config.initial_hp
    hp2 = battle_config.initial_hp

    # Случайно определяем, кто атакует первым
    first_attacker = random.choice([True, False])

    # Добавляем поля со здоровьем в начальный эмбед
    battle_embed.add_field(
        name=f"**{member1.name}**", value=f"{hp1}/{battle_config.initial_hp} HP", inline=True
    )
    battle_embed.add_field(
        name=f"**{member2.name}**", value=f"{hp2}/{battle_config.initial_hp} HP", inline=True
    )

    # Подготавливаем файл изображения для отправки
    file = discord.File(deathbattle_image, filename="deathbattle.png")
    battle_embed.set_image(url="attachment://deathbattle.png")  # Устанавливаем изображение в эмбед
    # Отправляем начальное сообщение с изображением и эмбедом
    battle_message = await ctx.send(file=file, embed=battle_embed)

    event_log: list[str] = []  # Лог последних событий битвы

    # Основной цикл битвы (пока оба участника живы)
    while hp1 > 0 and hp2 > 0:
        await asyncio.sleep(battle_config.turn_delay)  # Пауза между ходами
        # Получаем случайное событие и урон для этого хода
        event, damage = get_event_and_damage()

        # Ограничиваем лог событий последними записями согласно настройкам
        if len(event_log) >= battle_config.max_event_log:
            event_log.pop(0)  # Удаляем самое старое событие

        # Определяем атакующего и защищающегося, обновляем здоровье
        if first_attacker:
            hp2 -= damage
            event_text = event.format(attacker=member1.name, defender=member2.name, damage=damage)
            event_log.append(event_text)
            first_attacker = False  # Передаем ход другому участнику
        else:
            hp1 -= damage
            event_text = event.format(attacker=member2.name, defender=member1.name, damage=damage)
            event_log.append(event_text)
            first_attacker = True  # Передаем ход другому участнику

        # Создаем обновленный эмбед с логом событий
        battle_embed = discord.Embed(
            title=":crossed_swords: Смертельная битва!",
            description="\n".join(event_log),
            color=discord.Color.red(),
        )

        # Добавляем актуальное здоровье участников (не позволяем уйти в минус)
        hp1_display = max(0, hp1)
        hp2_display = max(0, hp2)

        battle_embed.add_field(
            name=f"**{member1.name}**",
            value=f"{hp1_display}/{battle_config.initial_hp} HP",
            inline=True,
        )

        battle_embed.add_field(
            name=f"**{member2.name}**",
            value=f"{hp2_display}/{battle_config.initial_hp} HP",
            inline=True,
        )

        # Редактируем сообщение, обновляя эмбед
        try:
            await battle_message.edit(embed=battle_embed)
        except discord.NotFound:
            logger.warning(
                "Сообщение deathbattle не найдено для редактирования (возможно, удалено)."
            )
            break  # Прерываем битву, если сообщение удалено
        except Exception as edit_err:
            logger.error(f"Ошибка при редактировании сообщения deathbattle: {edit_err}")
            break  # Прерываем битву при ошибке редактирования

    # Определяем победителя после завершения цикла
    # Проверяем, не закончилась ли битва из-за ошибки редактирования
    if hp1 <= 0 or hp2 <= 0:
        winner = member1.name if hp1 > 0 else member2.name  # Тот, у кого осталось здоровье
        event_log.append(
            f"\n:trophy: **{winner}** победил(а)!"
        )  # Добавляем финальное сообщение в лог

        # Создаем финальный эмбед с результатами
        final_embed = discord.Embed(
            title=":crossed_swords: Битва завершена!",
            description="\n".join(event_log),
            color=discord.Color.gold(),  # Меняем цвет для финального сообщения
        )

        final_embed.add_field(
            name=f"**{member1.name}**",
            value=f"{max(0, hp1)}/{battle_config.initial_hp} HP",  # Отображаем здоровье не ниже 0
            inline=True,
        )

        final_embed.add_field(
            name=f"**{member2.name}**",
            value=f"{max(0, hp2)}/{battle_config.initial_hp} HP",  # Отображаем здоровье не ниже 0
            inline=True,
        )

        # Редактируем сообщение последний раз, показывая финальный результат
        try:
            await battle_message.edit(embed=final_embed)
        except discord.NotFound:
            logger.warning("Сообщение deathbattle не найдено для финального редактирования.")
        except Exception as final_edit_err:
            logger.error(
                f"Ошибка при финальном редактировании сообщения deathbattle: {final_edit_err}"
            )
