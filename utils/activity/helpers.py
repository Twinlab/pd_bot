"""Вспомогательные функции для модуля отслеживания активности."""
import discord

# TODO: Consider if this needs access to bot config or roles in the future.
# For now, it's self-contained.
def is_application(member: discord.Member) -> bool:
    """
    Checks if a member is likely an application or bot based on name or roles.
    Used to filter out bots from activity tracking.

    Args:
        member: The discord.Member object to check.

    Returns:
        True if the member is likely a bot/application, False otherwise.
    """
    # Common bot names (can be expanded)
    app_names = ["minecraft bot"]
    if member.name in app_names:
        return True

    # Common role names indicating a bot (case-insensitive check might be better)
    app_role_names = ["BOT", "APP", "Application"]
    if any(role.name in app_role_names for role in member.roles):
        return True

    # Check the official bot flag
    if member.bot:
        return True

    return False


def format_time_short(seconds: int) -> str:
    """
    Formats time in seconds into a short string (e.g., "1h 5m").

    Args:
        seconds: The total number of seconds.

    Returns:
        A short formatted string representing the duration.
    """
    if seconds <= 0:
        return "0m" # Return "0m" if time is zero or negative

    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{hours}h"
    else:
        # Always show minutes, even if 0 and hours are 0 (e.g., for 30 seconds input)
        return f"{minutes}m"
