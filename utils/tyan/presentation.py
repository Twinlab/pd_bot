"""Короткая карточка результата /tyan."""

import discord

from utils.tyan.types import Roll


def build_tyan_card(roll: Roll, *, display_name: str) -> discord.Embed:
    """Собирает карточку без кнопок повторного броска."""
    color = 0xF0B232 if roll.kind == "mother" else 0x5865F2
    if roll.kind == "none":
        color = 0x747F8D
    embed = discord.Embed(description=roll.text, color=color)
    embed.set_author(name=f"Тянка на сегодня · {display_name}")
    embed.set_footer(text="Следующая выдача — в 00:00 МСК")
    return embed
