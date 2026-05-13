"""Ког сбора пати в игры через DM-реакции.

Команда ``/party`` создаёт публичный embed в текущем канале и шлёт DM
каждому участнику с указанной серверной ролью. Юзер ставит **любую**
реакцию на DM-сообщение → попадает в живой embed (готовы / начинка).
По истечении таймера бот пингует готовых отдельным сообщением.

Админ-команды ``/party_block``, ``/party_unblock``, ``/party_blocklist``
управляют чёрным списком пользователей, которым запрещено вызывать ``/party``.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.party.data_manager import PartyDataManager
from utils.party.duration import parse_minutes
from utils.party.embeds import build_dm_embed, build_public_embed
from utils.party.manager import Party, PartyManager
from utils.role_reaction_data_manager import RoleReactionDataManager


def _party_cooldown(ctx: commands.Context) -> commands.Cooldown:
    """Берёт текущий лимит кулдауна из настроек на каждый вызов команды."""
    return commands.Cooldown(1, get_settings().party.command_cooldown_seconds)


logger = logging.getLogger("bot.cogs.party")


def _resolve_emoji(
    bot: commands.Bot, payload: discord.RawReactionActionEvent, fallback: str
) -> str:
    """Превращает RawReaction-эмодзи в строку для embed.

    - Unicode-эмодзи возвращаем как есть (`payload.emoji.name`).
    - Кастомный эмодзи отдаём в формате ``<:name:id>`` / ``<a:name:id>`` только
      если бот видит его (`bot.get_emoji(id) is not None`); иначе подставляем
      fallback из конфига.
    """
    if payload.emoji.id is None:
        return payload.emoji.name or fallback
    if bot.get_emoji(payload.emoji.id) is None:
        return fallback
    prefix = "a" if payload.emoji.animated else ""
    return f"<{prefix}:{payload.emoji.name}:{payload.emoji.id}>"


class PartyCog(commands.Cog):
    """Сбор пати: команды + listener'ы + таймеры финализации."""

    bot: commands.Bot
    manager: PartyManager
    data_manager: PartyDataManager
    role_reaction_manager: RoleReactionDataManager
    _timers: dict[str, asyncio.Task[None]]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = PartyManager()
        self.data_manager = PartyDataManager()
        self.role_reaction_manager = RoleReactionDataManager()
        self._timers = {}

    async def _allowed_role_ids(self, guild_id: int) -> set[int]:
        """ID ролей, разрешённых для сбора (только выданные через /role_assign).

        Системная запись с ``role_id == 0`` отфильтровывается — это маркер
        самого role-message, не настоящая роль.
        """
        rows = await self.role_reaction_manager.get_all_role_reactions(guild_id)
        return {row["role_id"] for row in rows if row["role_id"] != 0}

    async def cog_unload(self) -> None:
        """Отменяет все запущенные таймеры финализации."""
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()
        logger.info(f"Ког {self.__class__.__name__} выгружен.")

    def _member_resolver(
        self, guild: discord.Guild | None
    ) -> Callable[[int], discord.Member | discord.User | None]:
        """Создаёт resolver `user_id -> Member | User | None` для embed-builder'ов."""

        def resolve(user_id: int) -> discord.Member | discord.User | None:
            if guild is not None:
                member = guild.get_member(user_id)
                if member is not None:
                    return member
            return self.bot.get_user(user_id)

        return resolve

    async def _refresh_public_embed(self, party: Party) -> None:
        """Перерисовывает публичный embed; поглощает Discord-ошибки."""
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        role = guild.get_role(party.role_id) if guild else None
        initiator = self._member_resolver(guild)(party.initiator_id)

        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return

        try:
            message = await channel.fetch_message(party.public_message_id)
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException as e:
            logger.warning(f"fetch_message {party.public_message_id} упал: {e}")
            return

        embed = build_public_embed(
            party,
            role_name=role.name if role else f"роль #{party.role_id}",
            initiator=initiator,
            member_resolver=self._member_resolver(guild),
            initiator_emoji=settings.party.initiator_emoji,
            finalized=party.finalized,
        )
        try:
            await message.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException as e:
            logger.warning(f"Не удалось обновить embed пати {party.id}: {e}")

    async def _send_dms(
        self,
        party: Party,
        role: discord.Role,
        initiator: discord.Member,
        jump_url: str,
    ) -> int:
        """Рассылает DM участникам роли. Возвращает число доставленных писем."""
        settings = get_settings()
        delivered = 0
        embed = build_dm_embed(
            party,
            role_name=role.name,
            initiator=initiator,
            jump_url=jump_url,
        )
        for member in role.members:
            if member.bot or member.id == initiator.id:
                continue
            if await self.data_manager.is_blocked(member.id):
                continue
            try:
                msg = await member.send(embed=embed)
                self.manager.register_dm(party.id, member.id, msg.id)
                delivered += 1
            except discord.Forbidden:
                logger.info(f"Юзер {member.id} закрыл DM — пропускаем")
            except discord.HTTPException as e:
                logger.warning(f"Ошибка отправки DM юзеру {member.id}: {e}")
            await asyncio.sleep(settings.party.dm_send_delay)
        return delivered

    async def _finalize_after(self, party: Party, seconds: float) -> None:
        """Таймер закрытия пати. Отменяется через `task.cancel()` в `cog_unload`."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        await self._finalize(party)

    async def _finalize(self, party: Party) -> None:
        """Финализирует пати: пингует готовых, обновляет embed, чистит state."""
        if party.finalized:
            return
        settings = get_settings()
        guild = self.bot.get_guild(party.guild_id)
        channel = self.bot.get_channel(party.channel_id) if guild else None
        role = guild.get_role(party.role_id) if guild else None

        ready_ids = list(party.ready)
        # Имя роли, а не mention — иначе в финальном сообщении она выглядит как кликабельный
        # пинг (даже с allowed_mentions roles=False это всё равно подсвечивается и раздражает).
        role_name = role.name if role else f"роль #{party.role_id}"

        # Пати считается собранным только если набрали запрошенный состав (включая инициатора).
        # Если ready меньше count — переиспользуем шаблон "никого не собрали": раз состав
        # не набран, пинговать частично собравшихся бессмысленно.
        if len(ready_ids) >= party.count:
            ready_pings = " ".join(f"<@{uid}>" for uid in ready_ids)
            text = settings.party.finished_message_template.format(
                ready_pings=ready_pings,
                role=role_name,
                comment=party.comment,
            )
        else:
            text = settings.party.empty_finished_message.format(
                role=role_name,
                comment=party.comment,
            )

        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            try:
                await channel.send(
                    text,
                    allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False
                    ),
                )
            except discord.HTTPException as e:
                logger.warning(f"Не удалось отправить финальное сообщение пати {party.id}: {e}")

        self.manager.cancel(party.id)
        await self._refresh_public_embed(party)
        self._timers.pop(party.id, None)

    @commands.hybrid_command(
        name="party",
        description="Собрать пати в игру: разошлёт DM всем с этой ролью.",
    )
    @app_commands.describe(
        role="Игровая роль (только из /role_assign)",
        when="Через сколько закроется сбор (минут, максимум 240)",
        count="Сколько ещё человек нужно (тебя считать не надо)",
        comment="Комментарий, который увидят все",
    )
    @commands.dynamic_cooldown(_party_cooldown, commands.BucketType.user)
    @command_error_handler
    async def party(
        self,
        ctx: commands.Context,
        role: discord.Role,
        when: int,
        count: int,
        *,
        comment: str,
    ) -> None:
        """Создаёт сбор пати. Подробности — в docstring модуля."""
        settings = get_settings()

        if ctx.guild is None:
            await safe_send_error(ctx, "чел ты долбоёб? пиши команду в конфе")
            return

        if await self.data_manager.is_blocked(ctx.author.id):
            await safe_send_error(ctx, "ты в бане")
            return

        allowed_role_ids = await self._allowed_role_ids(ctx.guild.id)
        if role.id not in allowed_role_ids:
            await safe_send_error(
                ctx,
                "Можно звать только в роли из /role_assign — выбери одну из них.",
            )
            return

        try:
            duration = parse_minutes(
                when,
                min_minutes=settings.party.min_duration_minutes,
                max_minutes=settings.party.max_duration_minutes,
            )
        except ValueError as e:
            await safe_send_error(ctx, str(e))
            return

        if not (settings.party.min_count <= count <= settings.party.max_count):
            await safe_send_error(
                ctx,
                f"Число участников должно быть от {settings.party.min_count} "
                f"до {settings.party.max_count}.",
            )
            return

        initiator = ctx.author
        if not isinstance(initiator, discord.Member):
            await safe_send_error(ctx, "чел ты не в конфе")
            return

        seconds = int(duration.total_seconds())

        now = datetime.now(UTC)
        deadline = now + duration

        placeholder_embed = discord.Embed(
            title=f"Сбор пати: {role.mention}",
            description="Готовлю сбор…",
            color=discord.Color.green(),
        )
        public_message = await safe_send(ctx, embed=placeholder_embed)
        if public_message is None:
            logger.error("Не удалось опубликовать embed пати — отмена.")
            return

        party = self.manager.create(
            guild_id=ctx.guild.id,
            channel_id=public_message.channel.id,
            public_message_id=public_message.id,
            role_id=role.id,
            initiator_id=initiator.id,
            count=count
            + 1,  # +1: инициатор тоже занимает слот, но не должен съедать запрошенное число
            comment=comment,
            created_at=now,
            deadline=deadline,
        )

        await self._refresh_public_embed(party)

        delivered = await self._send_dms(party, role, initiator, public_message.jump_url)
        logger.info(
            f"Создано пати {party.id} (роль {role.id}, нужно {count}, дедлайн {deadline.isoformat()}): "
            f"DM доставлено {delivered}"
        )

        task = asyncio.create_task(
            self._finalize_after(party, seconds), name=f"party-finalize-{party.id}"
        )
        self._timers[party.id] = task

    @commands.hybrid_command(
        name="party_cancel",
        description="Отменить свой последний активный сбор пати.",
    )
    @command_error_handler
    async def party_cancel(self, ctx: commands.Context) -> None:
        """Отменяет последний активный сбор инициатора."""
        active = self.manager.list_for_initiator(ctx.author.id)
        if not active:
            await safe_send_error(ctx, "У тебя нет активных пати.")
            return

        party = active[-1]
        task = self._timers.pop(party.id, None)
        if task is not None:
            task.cancel()
        self.manager.cancel(party.id)
        await self._refresh_public_embed(party)
        await safe_send(ctx, "Сбор пати отменён.", ephemeral=True)
        logger.info(f"Пати {party.id} отменено инициатором {ctx.author.id}")

    @app_commands.command(
        name="party_block",
        description="(Админ) Запретить пользователю вызывать /party.",
    )
    @app_commands.describe(user="Кого блокировать", reason="Причина (опционально)")
    @app_commands.checks.has_permissions(administrator=True)
    async def party_block(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str | None = None,
    ) -> None:
        """Добавляет пользователя в blacklist команды /party."""
        ok = await self.data_manager.add_block(
            user_id=user.id, blocked_by=interaction.user.id, reason=reason
        )
        if ok:
            suffix = f" (причина: {reason})" if reason else ""
            await interaction.response.send_message(
                f"Пользователь {user.mention} заблокирован для /party{suffix}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Не удалось заблокировать пользователя — см. логи.", ephemeral=True
            )

    @app_commands.command(
        name="party_unblock",
        description="(Админ) Снять запрет на /party.",
    )
    @app_commands.describe(user="Кого разблокировать")
    @app_commands.checks.has_permissions(administrator=True)
    async def party_unblock(self, interaction: discord.Interaction, user: discord.User) -> None:
        """Снимает блокировку пользователя."""
        ok = await self.data_manager.remove_block(user_id=user.id)
        if ok:
            await interaction.response.send_message(
                f"Пользователь {user.mention} разблокирован.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Пользователь {user.mention} не был в blacklist.", ephemeral=True
            )

    @app_commands.command(
        name="party_blocklist",
        description="(Админ) Показать заблокированных для /party пользователей.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def party_blocklist(self, interaction: discord.Interaction) -> None:
        """Выводит список заблокированных пользователей."""
        rows = await self.data_manager.list_blocks()
        if not rows:
            await interaction.response.send_message("Blacklist /party пуст.", ephemeral=True)
            return

        lines: list[str] = []
        for row in rows:
            user_id = row["user_id"]
            blocked_by = row["blocked_by"]
            reason = row["reason"] or "—"
            lines.append(f"<@{user_id}> (by <@{blocked_by}>): {reason}")

        embed = discord.Embed(
            title="Blacklist /party",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Учитывает реакцию юзера на DM-сообщение пати."""
        if payload.guild_id is not None:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        party = self.manager.get_by_dm_message(payload.message_id)
        if party is None:
            return

        settings = get_settings()
        emoji_str = _resolve_emoji(self.bot, payload, settings.party.fallback_emoji)
        updated = self.manager.add_reaction(payload.message_id, payload.user_id, emoji_str)
        if updated is not None:
            await self._refresh_public_embed(updated)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """Учитывает снятие реакции юзера с DM-сообщения пати."""
        if payload.guild_id is not None:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        party = self.manager.get_by_dm_message(payload.message_id)
        if party is None:
            return

        settings = get_settings()
        emoji_str = _resolve_emoji(self.bot, payload, settings.party.fallback_emoji)
        updated = self.manager.remove_reaction(payload.message_id, payload.user_id, emoji_str)
        if updated is not None:
            await self._refresh_public_embed(updated)


async def setup(bot: commands.Bot) -> None:
    """Регистрирует ког в боте."""
    await bot.add_cog(PartyCog(bot))
    logger.info("Ког PartyCog успешно загружен.")
