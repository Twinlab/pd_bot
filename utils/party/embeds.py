"""Builder'ы embed-ов для модуля сбора пати.

Чистые функции — никакого I/O, чтобы их можно было тестировать
и просто вызывать из кога при каждом обновлении состояния.
"""

from __future__ import annotations

from collections.abc import Callable

import discord

from utils.party.manager import Party

MemberResolver = Callable[[int], discord.Member | discord.User | None]


def _format_user(user_id: int, resolver: MemberResolver) -> str:
    """Возвращает упоминание участника или fallback с raw-id, если resolver не нашёл."""
    member = resolver(user_id)
    if member is None:
        return f"<@{user_id}>"
    return member.mention


def _format_section(
    user_ids: list[int],
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> str:
    """Форматирует список юзеров в виде ``эмодзи упоминание`` по одному на строку."""
    if not user_ids:
        return "_никого_"
    lines: list[str] = []
    for uid in user_ids:
        emoji = party.display_emoji(uid, initiator_emoji=initiator_emoji)
        lines.append(f"{emoji} {_format_user(uid, resolver)}")
    return "\n".join(lines)


def build_public_embed(
    party: Party,
    *,
    role_name: str,
    initiator: discord.Member | discord.User | None,
    member_resolver: MemberResolver,
    initiator_emoji: str,
    finalized: bool = False,
) -> discord.Embed:
    """Собирает публичный embed для сообщения в исходном канале.

    Args:
        party: Текущее состояние пати.
        role_name: Имя роли — попадает в title как plain text. Discord не
            парсит markdown/mention в title, поэтому именно строка ``role.name``,
            а не ``role.mention`` (иначе будет сырой ``<@&id>``).
        initiator: Объект инициатора (для footer'а).
        member_resolver: Функция ``user_id -> Member | None`` для резолва упоминаний.
        initiator_emoji: Эмодзи-корона для инициатора.
        finalized: Если True — embed закрашивается серым и в title идёт пометка.

    Returns:
        Готовый :class:`discord.Embed`.
    """
    title_prefix = "Сбор закрыт" if finalized else "Сбор пати"
    title = f"{title_prefix}: {role_name}"

    description_parts: list[str] = []
    if party.comment:
        description_parts.append(f"**Комментарий:** {party.comment}")
    description_parts.append(f"**Нужно:** {party.count} чел.")
    deadline_unix = int(party.deadline.timestamp())
    if finalized:
        description_parts.append(f"Закрыт <t:{deadline_unix}:R>")
    else:
        description_parts.append(f"Закрытие <t:{deadline_unix}:R>")

    color = discord.Color.dark_grey() if finalized else discord.Color.green()
    embed = discord.Embed(
        title=title,
        description="\n".join(description_parts),
        color=color,
    )

    ready_value = _format_section(party.ready, party, member_resolver, initiator_emoji)
    embed.add_field(
        name=f"✅ Готовы ({len(party.ready)}/{party.count})",
        value=ready_value,
        inline=False,
    )

    if party.bench:
        bench_value = _format_section(party.bench, party, member_resolver, initiator_emoji)
        embed.add_field(
            name=f"🪑 Начинка ({len(party.bench)})",
            value=bench_value,
            inline=False,
        )

    if initiator is not None:
        embed.set_footer(
            text=f"Собирает: {initiator.display_name}",
            icon_url=initiator.display_avatar.url if hasattr(initiator, "display_avatar") else None,
        )

    return embed


def build_dm_embed(
    party: Party,
    *,
    role_name: str,
    initiator: discord.Member | discord.User,
    jump_url: str,
) -> discord.Embed:
    """Собирает embed, который отправляется юзеру в личку.

    Просит поставить любую реакцию на это сообщение, чтобы записаться.
    """
    deadline_unix = int(party.deadline.timestamp())
    description = (
        f"{initiator.mention} зовёт в **{role_name}** — закрытие <t:{deadline_unix}:R>.\n"
        f"Нужно человек: **{party.count}**.\n"
    )
    if party.comment:
        description += f"**Комментарий:** {party.comment}\n"
    description += (
        "\nПоставь **любую реакцию** на это сообщение, если готов. "
        "Снимешь реакцию — выпадешь из списка."
    )

    embed = discord.Embed(
        title=f"Сбор пати: {role_name}",
        description=description,
        color=discord.Color.green(),
        url=jump_url,
    )
    embed.add_field(name="Окно сбора", value=f"[Перейти]({jump_url})", inline=False)
    return embed
