"""Единая палитра цветов для CV2-карточек и системных сообщений.

Единый источник истины для нового кода: CV2-хелперы (:mod:`utils.ui.components`)
и обработчик ошибок. Нейтральный тон взят из тем Discord 2.6
(``Colour.onyx_embed``), статусные цвета — семантические (успех/ошибка/инфо/
предупреждение) и совпадают с тем, что раньше хардкодилось по месту
(``discord.Color.green()`` / ``red()``), чтобы миграция не меняла вид сообщений.

Классические эмбеды отдельных фич пока берут цвета из ``config.colors`` и
сходятся к этой палитре по мере перевода поверхностей на Components V2.
"""

from __future__ import annotations

import discord

# Нейтральный фон под тему Discord 2.6 — для CV2-контейнеров без явного статуса.
NEUTRAL: discord.Colour = discord.Colour.onyx_embed()

# Статусные цвета. Значения совпадают с прежним хардкодом ради визуальной парности.
SUCCESS: discord.Colour = discord.Colour.green()
ERROR: discord.Colour = discord.Colour.red()
INFO: discord.Colour = discord.Colour.blurple()
WARNING: discord.Colour = discord.Colour.orange()
BRAND: discord.Colour = discord.Colour.blurple()


def result_accent(is_success: bool) -> discord.Colour:
    """Возвращает акцент победы/поражения (зелёный/красный) для карточек матчей."""
    return SUCCESS if is_success else ERROR
