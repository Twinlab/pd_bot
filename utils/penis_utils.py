"""
Утилиты для команды измерения пениса.

Этот модуль предоставляет функциональность для генерации случайного размера пениса
и отображения результата в виде эмбеда Discord с соответствующим форматированием
и цветовой индикацией в зависимости от размера. Поддерживает шуточный режим:
случайный «нюанс» с настраиваемым шансом и список user_id, для которых пенис
«не найден».
"""

import logging
import random

import discord
from discord.ext import commands

from config.settings import PenisConfig, PenisLengthBucket

logger = logging.getLogger("bot.utils.penis_utils")


def _color_for_length(length: int) -> discord.Color:
    """Возвращает цвет эмбеда в зависимости от длины."""
    if length >= 15:
        return discord.Color.green()
    if length >= 10:
        return discord.Color.gold()
    return discord.Color.red()


def _pick_length(buckets: list[PenisLengthBucket]) -> int:
    """Выбирает корзину пропорционально весам и берёт случайную длину внутри неё."""
    bucket = random.choices(buckets, weights=[b.weight for b in buckets], k=1)[0]
    return random.randint(bucket.min_length, bucket.max_length)


def _build_description(
    *,
    user: discord.Member | discord.User,
    is_self: bool,
    representation: str,
    nuance_text: str | None,
) -> str:
    """Собирает текст описания эмбеда, опционально дописывая «нюанс» с новой строки."""
    if is_self:
        base = f"{user.mention}, твой пенис\n{representation}"
    else:
        base = f"Пенис {user.mention}\n{representation}"
    if nuance_text:
        return f"{base}\n{nuance_text}"
    return base


async def measure_penis(ctx: commands.Context, target_user: discord.Member | None = None) -> None:
    """
    Генерирует случайный размер пениса и отправляет его в виде эмбеда.

    Поведение:
        - Если ``user.id`` есть в ``settings.fun.penis.not_found_user_ids`` — вместо
          обычной выдачи отправляется шуточное сообщение «ошибка, пенис не найден».
        - С шансом ``settings.fun.penis.nuance_chance`` к обычной выдаче добавляется
          строка-нюанс из ``settings.fun.penis.nuance_text`` (на следующей строке).

    Args:
        ctx: Контекст команды.
        target_user: Пользователь, для которого генерируется размер (опционально).
    """
    from config.settings import get_settings

    settings = get_settings()
    cfg: PenisConfig = settings.fun.penis

    user = target_user if target_user else ctx.author

    if user.id in cfg.not_found_user_ids:
        await ctx.send(cfg.not_found_text)
        return

    penis_length = _pick_length(cfg.length_buckets)
    penis_representation = "8" + "=" * penis_length + "D"

    nuance = cfg.nuance_text if random.random() < cfg.nuance_chance else None

    description = _build_description(
        user=user,
        is_self=user == ctx.author,
        representation=penis_representation,
        nuance_text=nuance,
    )

    embed = discord.Embed(
        title="Измеритель пениса",
        description=description,
        color=_color_for_length(penis_length),
    )
    embed.add_field(name="Длина", value=f"{penis_length} см", inline=True)

    await ctx.send(embed=embed)
