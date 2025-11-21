"""Модели базы данных Tortoise ORM."""

from tortoise import fields, models


class Link(models.Model):
    """Привязка аккаунта Discord к Steam ID."""

    discord_user_id = fields.BigIntField()
    steam_id = fields.BigIntField()

    class Meta:
        table = "links"
        unique_together = (("discord_user_id", "steam_id"),)


class DailyActivity(models.Model):
    """Ежедневная статистика игровой активности."""

    discord_user_id = fields.BigIntField()
    game_name = fields.TextField()
    date = fields.TextField()  # YYYY-MM-DD
    seconds_played_today = fields.IntField(default=0)

    class Meta:
        table = "daily_activity"
        unique_together = (("discord_user_id", "game_name", "date"),)
        indexes = (("date",),)


class MonthlyActivity(models.Model):
    """Ежемесячная агрегированная статистика."""

    discord_user_id = fields.BigIntField()
    game_name = fields.TextField()
    year = fields.IntField()
    month = fields.IntField()
    total_seconds_in_month = fields.IntField(default=0)

    class Meta:
        table = "monthly_activity"
        unique_together = (("discord_user_id", "game_name", "year", "month"),)
        indexes = (("discord_user_id", "year", "month"),)


class RoleReaction(models.Model):
    """Настройки ролей по реакциям."""

    guild_id = fields.BigIntField()
    channel_id = fields.BigIntField()
    message_id = fields.BigIntField()
    emoji = fields.TextField()
    role_id = fields.BigIntField()
    description = fields.TextField(null=True)

    class Meta:
        table = "role_reactions"
        unique_together = (("guild_id", "message_id", "emoji"),)


class TwitchStreamer(models.Model):
    """Информация о Twitch-стримерах."""

    guild_id = fields.BigIntField()
    channel_id = fields.BigIntField()
    twitch_username = fields.TextField()
    twitch_id = fields.TextField(null=True)
    is_live = fields.BooleanField(default=False)
    last_stream_id = fields.TextField(null=True)
    last_notification_time = fields.IntField(default=0)

    class Meta:
        table = "twitch_streamers"
        unique_together = (("guild_id", "twitch_username"),)
        indexes = (("twitch_username",),)


class AnimeCache(models.Model):
    """Кеш аниме-изображений."""

    post_id = fields.IntField(pk=True)
    added_at = fields.IntField()  # Timestamp

    class Meta:
        table = "anime_cache"
        indexes = (("added_at",),)


class APICache(models.Model):
    """Кеш ответов API (Dota, Twitch и др.)."""

    key = fields.TextField(pk=True)
    data = fields.JSONField()
    timestamp = fields.FloatField()
    ttl = fields.IntField()  # Время жизни в секундах

    class Meta:
        table = "api_cache"
