"""
Утилиты для команды измерения пениса.

Этот модуль предоставляет функциональность для генерации случайного размера пениса
и отображения результата в виде CV2-карточки Discord с соответствующим форматированием
и цветовой индикацией (акцент-полоса) в зависимости от размера. Поддерживает шуточный
режим: случайный «нюанс» с настраиваемым шансом и список user_id, для которых пенис
«не найден».
"""

import logging
import random

import discord
from discord.ext import commands

from config.settings import PenisConfig, PenisLengthBucket

logger = logging.getLogger("bot.utils.penis_utils")


def _color_for_length(length: int) -> discord.Color:
    """Возвращает акцент карточки в зависимости от длины."""
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
    """Собирает текст карточки, опционально дописывая «нюанс» с новой строки."""
    if is_self:
        base = f"{user.mention}, твой пенис\n{representation}"
    else:
        base = f"Пенис {user.mention}\n{representation}"
    if nuance_text:
        return f"{base}\n{nuance_text}"
    return base


def build_penis_card(*, description: str, length: int) -> discord.ui.LayoutView:
    """Собирает CV2-карточку измерителя: заголовок, описание, длина.

    Акцент-полоса окрашивается по длине (зелёный/золотой/красный) через
    :func:`_color_for_length`.

    Args:
        description: Готовый текст с упоминанием и ASCII-представлением.
        length: Длина в сантиметрах (для акцента и подписи).

    Returns:
        Неинтерактивный ``LayoutView`` с единственным контейнером.
    """
    container: discord.ui.Container = discord.ui.Container(accent_colour=_color_for_length(length))
    container.add_item(discord.ui.TextDisplay("## Измеритель пениса"))
    container.add_item(discord.ui.TextDisplay(description))
    container.add_item(discord.ui.TextDisplay(f"-# Длина: {length} см"))
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


async def measure_penis(ctx: commands.Context, target_user: discord.Member | None = None) -> None:
    """
    Генерирует случайный размер пениса и отправляет его в виде CV2-карточки.

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

    await ctx.send(view=build_penis_card(description=description, length=penis_length))
