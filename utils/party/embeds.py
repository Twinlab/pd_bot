"""Builder CV2-контейнера для модуля сбора пати.

Чистая функция — никакого I/O, чтобы её можно было тестировать и просто
вызывать из кога при каждом обновлении состояния. Один и тот же контейнер
вешается в публичном сообщении и в DM каждому участнику (в DM к нему ещё
добавляется ряд кнопок) — так что обновления видны везде синхронно.
"""

from __future__ import annotations

from collections.abc import Callable

import discord

from utils.party.manager import Party, PartyPhase
from utils.ui import colors

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


def _section_block(
    title: str,
    user_ids: list[int],
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> str:
    """Один текстовый блок секции: жирный заголовок + список участников."""
    return f"**{title}**\n{_format_section(user_ids, party, resolver, initiator_emoji)}"


def _collecting_blocks(
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> list[str]:
    """Блоки фазы сбора: готовы / начинка / отказались."""
    blocks = [
        _section_block(
            f"✅ Готовы ({len(party.ready)}/{party.count})",
            party.ready,
            party,
            resolver,
            initiator_emoji,
        )
    ]
    if party.bench:
        blocks.append(
            _section_block(
                f"🪑 Начинка ({len(party.bench)})", party.bench, party, resolver, initiator_emoji
            )
        )
    if party.declined:
        blocks.append(
            _section_block(
                f"❌ Не пойдут ({len(party.declined)})",
                party.declined,
                party,
                resolver,
                initiator_emoji,
            )
        )
    return blocks


def _ready_check_blocks(
    party: Party,
    resolver: MemberResolver,
    initiator_emoji: str,
) -> list[str]:
    """Блоки фазы чека: подтвердили / ждём / резерв / слетели / отказались."""
    blocks = [
        _section_block(
            f"✅ Подтвердили ({len(party.confirmed)}/{party.count})",
            party.confirmed,
            party,
            resolver,
            initiator_emoji,
        )
    ]
    if party.pending_confirm:
        blocks.append(
            _section_block(
                f"⏳ Ждём подтверждения ({len(party.pending_confirm)})",
                party.pending_confirm,
                party,
                resolver,
                initiator_emoji,
            )
        )
    if party.bench:
        blocks.append(
            _section_block(
                f"🪑 Резерв ({len(party.bench)})", party.bench, party, resolver, initiator_emoji
            )
        )
    if party.not_confirmed:
        blocks.append(
            _section_block(
                f"🛑 Не подтвердили ({len(party.not_confirmed)})",
                party.not_confirmed,
                party,
                resolver,
                initiator_emoji,
            )
        )
    if party.declined:
        blocks.append(
            _section_block(
                f"❌ Не пойдут ({len(party.declined)})",
                party.declined,
                party,
                resolver,
                initiator_emoji,
            )
        )
    return blocks


def build_party_container(
    party: Party,
    *,
    role_name: str,
    initiator: discord.Member | discord.User | None,
    member_resolver: MemberResolver,
    initiator_emoji: str,
    finalized: bool = False,
    jump_url: str | None = None,
) -> discord.ui.Container:
    """Универсальный CV2-контейнер для публичного сообщения и DM.

    Args:
        party: Текущее состояние пати.
        role_name: Имя роли plain text — заголовок не парсит mention.
        initiator: Инициатор (для аватара-заголовка и подписи).
        member_resolver: ``user_id -> Member | User | None`` для упоминаний.
        initiator_emoji: Эмодзи рядом с инициатором (по умолчанию корона).
        finalized: Если True — нейтральный акцент и пометка «Сбор закрыт».
        jump_url: Ссылка на публичное сообщение пати; делает заголовок кликабельным
            (нужно прежде всего в DM, чтобы можно было прыгнуть в общий канал).

    Returns:
        ``Container`` без кнопок. В DM к нему ещё добавляется ряд управления.
    """
    in_check = party.phase is PartyPhase.READY_CHECK and not finalized

    if finalized:
        title_prefix = "Сбор закрыт"
        accent: discord.Colour = colors.NEUTRAL
    elif in_check:
        title_prefix = "Чек готовности"
        accent = colors.WARNING
    else:
        title_prefix = "Сбор пати"
        accent = colors.SUCCESS
    title_text = f"{title_prefix}: {role_name}"
    heading = f"## [{title_text}]({jump_url})" if jump_url else f"## {title_text}"

    container: discord.ui.Container = discord.ui.Container(accent_colour=accent)

    avatar = getattr(initiator, "display_avatar", None) if initiator is not None else None
    if avatar is not None:
        container.add_item(discord.ui.Section(heading, accessory=discord.ui.Thumbnail(avatar.url)))
    else:
        container.add_item(discord.ui.TextDisplay(heading))

    description_parts: list[str] = []
    if party.comment:
        description_parts.append(f"**Комментарий:** {party.comment}")
    if in_check:
        description_parts.append("Все из основы — жмите **«Подтверждаю»**!")
    deadline_unix = int(party.deadline.timestamp())
    description_parts.append(
        f"Закрыт <t:{deadline_unix}:R>" if finalized else f"Закрытие <t:{deadline_unix}:R>"
    )
    container.add_item(discord.ui.TextDisplay("\n".join(description_parts)))

    container.add_item(discord.ui.Separator())

    blocks = (
        _ready_check_blocks(party, member_resolver, initiator_emoji)
        if in_check
        else _collecting_blocks(party, member_resolver, initiator_emoji)
    )
    for block in blocks:
        container.add_item(discord.ui.TextDisplay(block))

    if party.image_url:
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=party.image_url)))

    if initiator is not None:
        container.add_item(discord.ui.TextDisplay(f"-# Собирает: {initiator.display_name}"))

    return container


def party_card_view(container: discord.ui.Container) -> discord.ui.LayoutView:
    """Оборачивает контейнер в неинтерактивный ``LayoutView`` (публичное сообщение, финал)."""
    view: discord.ui.LayoutView = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view
