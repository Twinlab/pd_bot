"""Вспомогательные функции для создания и форматирования discord.Embed объектов и длительности для музыкального модуля."""
import discord
from typing import Optional, Any, List, Tuple, Dict # Добавляем нужные типы
from .config import COLORS

def create_embed(title: str, description: str = "", color: Optional[discord.Color] = None, **kwargs: Any) -> discord.Embed:
    """
    Создает и возвращает объект discord.Embed с заданными параметрами.

    Args:
        title: Заголовок эмбеда.
        description: Описание эмбеда.
        color: Цвет эмбеда. По умолчанию используется COLORS['DEFAULT'].
        **kwargs: Дополнительные параметры для настройки эмбеда:
            thumbnail (str): URL для миниатюры.
            footer (str): Текст для футера.
            image (str): URL для изображения.
            author (dict | str): Информация об авторе. Если dict, ожидаются ключи 'name', 'icon_url', 'url'.
                                Если str, используется как имя автора.
            fields (List[Tuple[str, str, bool]]): Список полей для добавления.
                                                  Каждое поле - кортеж (name, value, inline).
            Любые другие kwargs будут добавлены как обычные поля (name=key, value=value, inline=True).
    Returns:
        Сконфигурированный объект discord.Embed.
    """
    final_color = color if color is not None else COLORS['DEFAULT']
    embed = discord.Embed(title=title, description=description, color=final_color) # Используем final_color
    for name, value in kwargs.items():
        if value is None: # Пропускаем только None значения
            continue
        if name == 'thumbnail' and isinstance(value, str):
            embed.set_thumbnail(url=value)
        elif name == 'footer' and isinstance(value, str):
            embed.set_footer(text=value)
        elif name == 'image' and isinstance(value, str):
            embed.set_image(url=value)
        elif name == 'author':
            if isinstance(value, dict):
                embed.set_author(
                    name=str(value.get('name', '')),
                    icon_url=value.get('icon_url') if isinstance(value.get('icon_url'), str) else None,
                    url=value.get('url') if isinstance(value.get('url'), str) else None
                )
            elif isinstance(value, str):
                embed.set_author(name=value)
        elif name == 'fields' and isinstance(value, list):
            for field_data in value:
                if isinstance(field_data, tuple) and len(field_data) >= 2:
                    field_name = str(field_data[0])
                    field_value = str(field_data[1])
                    inline = field_data[2] if len(field_data) > 2 and isinstance(field_data[2], bool) else True
                    embed.add_field(name=field_name, value=field_value, inline=inline)
        else:
            embed.add_field(name=str(name), value=str(value), inline=True)
    return embed

def format_duration(duration: Optional[int | float | str]) -> str: # Добавляем аннотации типов
    """
    Форматирует секунды в MM:SS или HH:MM:SS.
    
    Args:
        duration: Длительность в секундах (может быть int, float или строкой, которую можно преобразовать в число).
                 Если None, возвращает символ бесконечности.
    
    Returns:
        Отформатированная строка времени в формате MM:SS или HH:MM:SS.
        Возвращает "∞" для None, "00:00" для нулевых или отрицательных значений,
        и "?:??" при ошибке преобразования.
    """
    if duration is None:
        return "∞"
    try:
        duration = int(float(duration))
        if duration <= 0:
            return "00:00"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "?:??"
