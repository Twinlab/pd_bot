import discord
from .config import COLORS

def create_embed(title: str, description: str = "", color: discord.Color = COLORS['DEFAULT'], **kwargs) -> discord.Embed:
    """Создает и возвращает объект discord.Embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    for name, value in kwargs.items():
        if not value:
            continue
        if name == 'thumbnail':
            embed.set_thumbnail(url=value)
        elif name == 'footer':
            embed.set_footer(text=value)
        elif name == 'image':
            embed.set_image(url=value)
        elif name == 'author':
            if isinstance(value, dict):
                embed.set_author(
                    name=value.get('name', ''),
                    icon_url=value.get('icon_url', None),
                    url=value.get('url', None)
                )
            else:
                embed.set_author(name=str(value))
        elif name == 'fields':
            for field_data in value:
                inline = field_data[2] if len(field_data) > 2 else True
                embed.add_field(name=field_data[0], value=field_data[1], inline=inline)
        else:
            embed.add_field(name=name, value=value, inline=True)
    return embed

def format_duration(duration):
    """Форматирует секунды в MM:SS или HH:MM:SS."""
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
