"""Builder embed-а для модуля сбора пати.

Чистая функция — никакого I/O, чтобы её можно было тестировать и просто
вызывать из кога при каждом обновлении состояния. Один и тот же embed
вешается в публичном сообщении и в DM каждому участнику — так что
обновления видны везде синхронно.
"""

from __future__ import annotations

from collections.abc import Callable

import discord

from utils.party.manager import Party, PartyPhase

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
    """Форматирует список юзеров: у инициатора — корона, у остальных просто упоминание."""
    if not user_ids:
        return "_никого_"
    lines: list[str] = []
    for uid in user_ids:
        mention = _format_user(uid, resolver)
        if uid == party.initiator_id:
            lines.append(f"{initiator_emoji} {mention}")
        else:
            lines.append(f"• {mention}")
    return "\n".join(lines)


def _add_collecting_fields(
    embed: discord.Embed,
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> None:
    """Секции фазы сбора: готовы / начинка / отказались."""
    embed.add_field(
        name=f"✅ Готовы ({len(party.ready)}/{party.count})",
        value=_format_section(party.ready, party, resolver, initiator_emoji),
        inline=False,
    )
    if party.bench:
        embed.add_field(
            name=f"🪑 Начинка ({len(party.bench)})",
            value=_format_section(party.bench, party, resolver, initiator_emoji),
            inline=False,
        )
    if party.declined:
        embed.add_field(
            name=f"❌ Не пойдут ({len(party.declined)})",
            value=_format_section(party.declined, party, resolver, initiator_emoji),
            inline=False,
        )


def _add_ready_check_fields(
    embed: discord.Embed,
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> None:
    """Секции фазы чека: подтвердили / ждём / резерв / слетели / отказались."""
    embed.add_field(
        name=f"✅ Подтвердили ({len(party.confirmed)}/{party.count})",
        value=_format_section(party.confirmed, party, resolver, initiator_emoji),
        inline=False,
    )
    if party.pending_confirm:
        embed.add_field(
            name=f"⏳ Ждём подтверждения ({len(party.pending_confirm)})",
            value=_format_section(party.pending_confirm, party, resolver, initiator_emoji),
            inline=False,
        )
    if party.bench:
        embed.add_field(
            name=f"🪑 Резерв ({len(party.bench)})",
            value=_format_section(party.bench, party, resolver, initiator_emoji),
            inline=False,
        )
    if party.not_confirmed:
        embed.add_field(
            name=f"🛑 Не подтвердили ({len(party.not_confirmed)})",
            value=_format_section(party.not_confirmed, party, resolver, initiator_emoji),
            inline=False,
        )
    if party.declined:
        embed.add_field(
            name=f"❌ Не пойдут ({len(party.declined)})",
            value=_format_section(party.declined, party, resolver, initiator_emoji),
            inline=False,
        )


def build_party_embed(
    party: Party,
    *,
    role_name: str,
    initiator: discord.Member | discord.User | None,
    member_resolver: MemberResolver,
    initiator_emoji: str,
    finalized: bool = False,
    jump_url: str | None = None,
) -> discord.Embed:
    """Универсальный embed для публичного сообщения и DM.

    Args:
        party: Текущее состояние пати.
        role_name: Имя роли plain text — Discord не парсит mention в title.
        initiator: Инициатор (для footer).
        member_resolver: ``user_id -> Member | User | None`` для упоминаний.
        initiator_emoji: Эмодзи рядом с инициатором (по умолчанию корона).
        finalized: Если True — embed серый, в title пометка «Сбор закрыт».
        jump_url: Ссылка на публичное сообщение пати; делает title кликабельным
            (нужно прежде всего в DM, чтобы можно было прыгнуть в общий канал).
    """
    in_check = party.phase is PartyPhase.READY_CHECK and not finalized

    if finalized:
        title_prefix = "Сбор закрыт"
        color = discord.Color.dark_grey()
    elif in_check:
        title_prefix = "Чек готовности"
        color = discord.Color.gold()
    else:
        title_prefix = "Сбор пати"
        color = discord.Color.green()
    title = f"{title_prefix}: {role_name}"

    # Размер состава (party.count) намеренно НЕ дублируем в description —
    # он уже виден в заголовке секции с готовыми/подтвердившими.
    description_parts: list[str] = []
    if party.comment:
        description_parts.append(f"**Комментарий:** {party.comment}")
    if in_check:
        description_parts.append("Все из основы — жмите **«Подтверждаю»**!")
    deadline_unix = int(party.deadline.timestamp())
    if finalized:
        description_parts.append(f"Закрыт <t:{deadline_unix}:R>")
    else:
        description_parts.append(f"Закрытие <t:{deadline_unix}:R>")

    embed = discord.Embed(
        title=title,
        description="\n".join(description_parts),
        color=color,
        url=jump_url,
    )

    if party.image_url:
        embed.set_image(url=party.image_url)

    if in_check:
        _add_ready_check_fields(embed, party, member_resolver, initiator_emoji)
    else:
        _add_collecting_fields(embed, party, member_resolver, initiator_emoji)

    if initiator is not None:
        embed.set_footer(
            text=f"Собирает: {initiator.display_name}",
            icon_url=initiator.display_avatar.url if hasattr(initiator, "display_avatar") else None,
        )

    return embed
