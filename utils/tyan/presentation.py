"""CV2-карточка результата /tyan."""

from datetime import timedelta

import discord

from utils.tyan.types import Roll


def build_tyan_card(roll: Roll) -> discord.ui.LayoutView:
    """Собирает карточку с упоминанием владельца и датой следующей выдачи."""
    color = 0xF0B232 if roll.kind == "mother" else 0x5865F2
    if roll.kind == "none":
        color = 0x747F8D
    next_day = roll.day + timedelta(days=1)
    container: discord.ui.Container = discord.ui.Container(accent_colour=color)
    container.add_item(discord.ui.TextDisplay(f"## Тянка <@{roll.user_id}> на сегодня"))
    container.add_item(discord.ui.TextDisplay(roll.text))
    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(f"-# Следующая выдача — **{next_day:%d.%m.%Y} в 00:00 МСК**")
    )
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view
