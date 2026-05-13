"""Тесты для PartyCog."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.party import PartyCog, _resolve_emoji
from config.settings import BotSettings


@pytest.fixture
def party_settings() -> BotSettings:
    """Настройки бота с дефолтным блоком party."""
    return BotSettings()


@pytest.fixture
def patched_settings(party_settings: BotSettings):
    """Подменяет get_settings во всех местах, где он импортирован в коге."""
    with patch("cogs.party.get_settings", return_value=party_settings):
        yield party_settings


@pytest.fixture
def bot() -> MagicMock:
    """Бот с .user, get_emoji, get_guild, get_channel, get_user."""
    b = MagicMock(spec=commands.Bot)
    b.user = MagicMock(spec=discord.ClientUser)
    b.user.id = 99
    b.get_emoji = MagicMock(return_value=None)
    b.get_guild = MagicMock(return_value=None)
    b.get_channel = MagicMock(return_value=None)
    b.get_user = MagicMock(return_value=None)
    return b


@pytest.fixture
def cog(bot: MagicMock) -> PartyCog:
    """Свежий PartyCog с замоканным role_reaction_manager (по умолчанию пускает любую роль).

    Тесты, которым нужен другой allowlist (или пустой), переопределяют возвращаемое значение.
    """
    c = PartyCog(bot)
    c.role_reaction_manager = MagicMock()
    c.role_reaction_manager.get_all_role_reactions = AsyncMock(
        return_value=[{"role_id": 42, "emoji": "🎮", "message_id": 1}]
    )
    return c


@pytest.fixture
def role() -> MagicMock:
    """Роль с заранее заполненным `members`."""
    r = MagicMock(spec=discord.Role)
    r.id = 42
    r.name = "Гремлины"
    r.mention = "<@&42>"
    r.members = []
    return r


def _make_emoji(*, id_: int | None, name: str, animated: bool = False) -> MagicMock:
    """Готовит мок discord.PartialEmoji с правильно проставленным `name`.

    `MagicMock(name=...)` не работает — `name` это служебное поле самого мока,
    поэтому атрибуты приходится выставлять отдельными присваиваниями.
    """
    emoji = MagicMock()
    emoji.id = id_
    emoji.name = name
    emoji.animated = animated
    return emoji


def make_member(user_id: int, *, can_dm: bool = True, is_bot: bool = False) -> MagicMock:
    """Создаёт мок Member; если can_dm=False — `send` бросает Forbidden."""
    m = MagicMock(spec=discord.Member)
    m.id = user_id
    m.name = f"user{user_id}"
    m.display_name = f"user{user_id}"
    m.mention = f"<@{user_id}>"
    m.bot = is_bot
    m.display_avatar = MagicMock()
    m.display_avatar.url = "http://avatar"
    if can_dm:
        sent = MagicMock()
        sent.id = 10000 + user_id
        m.send = AsyncMock(return_value=sent)
    else:
        m.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "DM closed"))
    return m


class TestResolveEmoji:
    """Тесты _resolve_emoji."""

    def test_unicode_emoji(self, bot: MagicMock) -> None:
        """Unicode-эмодзи возвращается как есть."""
        payload = MagicMock()
        payload.emoji = _make_emoji(id_=None, name="🎮", animated=False)
        assert _resolve_emoji(bot, payload, "💩") == "🎮"

    def test_custom_emoji_visible(self, bot: MagicMock) -> None:
        """Кастомный эмодзи, который бот видит — форматируется в `<:name:id>`."""
        bot.get_emoji.return_value = MagicMock()
        payload = MagicMock()
        payload.emoji = _make_emoji(id_=12345, name="kekw", animated=False)
        assert _resolve_emoji(bot, payload, "💩") == "<:kekw:12345>"

    def test_custom_emoji_animated(self, bot: MagicMock) -> None:
        """Анимированный кастомный эмодзи — `<a:name:id>`."""
        bot.get_emoji.return_value = MagicMock()
        payload = MagicMock()
        payload.emoji = _make_emoji(id_=12345, name="dance", animated=True)
        assert _resolve_emoji(bot, payload, "💩") == "<a:dance:12345>"

    def test_custom_emoji_invisible_falls_back(self, bot: MagicMock) -> None:
        """Если бот не видит кастомный эмодзи — fallback из конфига."""
        bot.get_emoji.return_value = None
        payload = MagicMock()
        payload.emoji = _make_emoji(id_=12345, name="secret", animated=False)
        assert _resolve_emoji(bot, payload, "💩") == "💩"


class TestSendDMs:
    """Тесты _send_dms."""

    @pytest.mark.asyncio
    async def test_skips_initiator_and_bots(
        self,
        cog: PartyCog,
        role: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Инициатор и боты пропускаются."""
        initiator = make_member(100)
        member_bot = make_member(200, is_bot=True)
        regular = make_member(300)
        role.members = [initiator, member_bot, regular]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=initiator.id,
            count=2,
            comment="test",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator, "http://jump")

        assert delivered == 1
        regular.send.assert_awaited_once()
        member_bot.send.assert_not_called()
        initiator.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_blocked_users(
        self,
        cog: PartyCog,
        role: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Заблокированные юзеры не получают DM."""
        initiator = make_member(100)
        blocked = make_member(200)
        ok_user = make_member(300)
        role.members = [blocked, ok_user]

        cog.data_manager = MagicMock()

        async def is_blocked(uid: int) -> bool:
            return uid == 200

        cog.data_manager.is_blocked = AsyncMock(side_effect=is_blocked)

        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=initiator.id,
            count=2,
            comment="test",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator, "http://jump")

        assert delivered == 1
        blocked.send.assert_not_called()
        ok_user.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forbidden_does_not_break_loop(
        self,
        cog: PartyCog,
        role: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Если у одного юзера закрыты DM — остальные всё равно получают."""
        initiator = make_member(100)
        closed_dm = make_member(200, can_dm=False)
        ok_user = make_member(300)
        role.members = [closed_dm, ok_user]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=initiator.id,
            count=2,
            comment="test",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator, "http://jump")

        assert delivered == 1
        ok_user.send.assert_awaited_once()
        # closed_dm попал в send но swallowed
        closed_dm.send.assert_awaited_once()
        # DM-сообщение зарегистрировано только у успешного
        assert ok_user.id in party.dm_messages
        assert closed_dm.id not in party.dm_messages

    @pytest.mark.asyncio
    async def test_registers_dm_message_id(
        self,
        cog: PartyCog,
        role: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """После успешной отправки DM message_id кладётся в party.dm_messages."""
        initiator = make_member(100)
        member = make_member(200)
        role.members = [member]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=initiator.id,
            count=2,
            comment="test",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            await cog._send_dms(party, role, initiator, "http://jump")

        assert party.dm_messages[200] == 10200
        assert cog.manager.get_by_dm_message(10200) is party


class TestFinalize:
    """Тесты _finalize."""

    @pytest.mark.asyncio
    async def test_pings_ready_users(
        self,
        cog: PartyCog,
        bot: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Полный состав → пинги по шаблону, роль как plain-text, без `<@&id>`."""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 1
        role = MagicMock(spec=discord.Role)
        role.id = 42
        role.name = "Гремлины"
        role.mention = "<@&42>"
        guild.get_role = MagicMock(return_value=role)
        bot.get_guild.return_value = guild

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.send = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        bot.get_channel.return_value = channel

        # count=2 → нужно ровно 2 готовых (инициатор + 1 реакция). Полный состав.
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=100,
            count=2,
            comment="идём ранкед",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC),
        )
        cog.manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        cog.manager.add_reaction(2000, user_id=200, emoji="🎮")

        await cog._finalize(party)

        channel.send.assert_awaited_once()
        sent_text = channel.send.await_args.args[0]
        assert "<@100>" in sent_text
        assert "<@200>" in sent_text
        assert "идём ранкед" in sent_text
        # Имя роли — да, mention роли — нет
        assert "Гремлины" in sent_text
        assert "<@&42>" not in sent_text
        assert party.finalized is True

    @pytest.mark.asyncio
    async def test_incomplete_party_uses_empty_template(
        self,
        cog: PartyCog,
        bot: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Если набрано меньше count — переиспользуем empty_finished_message без пингов."""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 1
        role = MagicMock(spec=discord.Role)
        role.id = 42
        role.name = "Гремлины"
        role.mention = "<@&42>"
        guild.get_role = MagicMock(return_value=role)
        bot.get_guild.return_value = guild

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.send = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        bot.get_channel.return_value = channel

        # count=3, но в ready только инициатор (1 < 3) — неполный состав.
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=100,
            count=3,
            comment="тестим",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC),
        )

        await cog._finalize(party)

        channel.send.assert_awaited_once()
        sent_text = channel.send.await_args.args[0]
        assert "Никого не собрали" in sent_text
        # Никого не пингуем — даже инициатора
        assert "<@100>" not in sent_text
        # И роль остаётся plain-text
        assert "<@&42>" not in sent_text

    @pytest.mark.asyncio
    async def test_empty_pings_uses_empty_template(
        self,
        cog: PartyCog,
        bot: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Если никого нет — используется empty_finished_message (без пингов)."""
        guild = MagicMock(spec=discord.Guild)
        role = MagicMock(spec=discord.Role)
        role.id = 42
        role.name = "x"
        role.mention = "<@&42>"
        guild.get_role = MagicMock(return_value=role)
        bot.get_guild.return_value = guild

        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        bot.get_channel.return_value = channel

        # Пати без count = 0 не сделать (min_count=1), но можем эмулировать пустоту
        # путём искусственного очищения joined_order:
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=role.id,
            initiator_id=100,
            count=2,
            comment="x",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC),
        )
        party.joined_order.clear()

        await cog._finalize(party)

        channel.send.assert_awaited_once()
        sent_text = channel.send.await_args.args[0]
        assert "Никого не собрали" in sent_text

    @pytest.mark.asyncio
    async def test_finalize_idempotent(
        self,
        cog: PartyCog,
        bot: MagicMock,
        patched_settings: BotSettings,
    ) -> None:
        """Повторный _finalize ничего не делает."""
        bot.get_guild.return_value = None

        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1,
            role_id=42,
            initiator_id=100,
            count=1,
            comment="",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC),
        )
        party.finalized = True

        # Не должен валиться и не должен ничего делать
        await cog._finalize(party)


class TestReactionListeners:
    """Тесты on_raw_reaction_add / on_raw_reaction_remove."""

    @pytest.mark.asyncio
    async def test_ignores_guild_reactions(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Реакции на гилдовые сообщения игнорируются."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        payload = MagicMock()
        payload.guild_id = 555
        payload.user_id = 1
        payload.message_id = 9999

        await cog.on_raw_reaction_add(payload)
        cog._refresh_public_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unknown_dm_message(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Реакции на DM, не связанные ни с одним пати — игнорируются."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        payload = MagicMock()
        payload.guild_id = None
        payload.user_id = 1
        payload.message_id = 9999

        await cog.on_raw_reaction_add(payload)
        cog._refresh_public_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_self_reactions(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Реакции самого бота игнорируются."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        payload = MagicMock()
        payload.guild_id = None
        payload.user_id = bot.user.id
        payload.message_id = 9999

        await cog.on_raw_reaction_add(payload)
        cog._refresh_public_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_reaction_updates_embed(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Валидная реакция → manager обновляется + embed перерисовывается."""
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=42,
            initiator_id=100,
            count=2,
            comment="x",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )
        cog.manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]

        payload = MagicMock()
        payload.guild_id = None
        payload.user_id = 200
        payload.message_id = 2000
        payload.emoji = _make_emoji(id_=None, name="🎮", animated=False)

        await cog.on_raw_reaction_add(payload)

        assert party.reactions[200] == "🎮"
        cog._refresh_public_embed.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_remove_reaction_updates_embed(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Снятие реакции → юзер выбивается + embed перерисовывается."""
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=42,
            initiator_id=100,
            count=2,
            comment="x",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )
        cog.manager.register_dm(party.id, user_id=200, dm_message_id=2000)
        cog.manager.add_reaction(2000, user_id=200, emoji="🎮")
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]

        payload = MagicMock()
        payload.guild_id = None
        payload.user_id = 200
        payload.message_id = 2000
        payload.emoji = _make_emoji(id_=None, name="🎮", animated=False)

        await cog.on_raw_reaction_remove(payload)

        assert 200 not in party.reactions
        cog._refresh_public_embed.assert_awaited_once_with(party)


class TestBlocklistCommands:
    """Тесты /party_block / /party_unblock / /party_blocklist."""

    @pytest.mark.asyncio
    async def test_party_block_adds_record(self, cog: PartyCog) -> None:
        """party_block зовёт data_manager.add_block и шлёт ответ."""
        cog.data_manager.add_block = AsyncMock(return_value=True)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(spec=discord.User, id=1)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        target = MagicMock(spec=discord.User)
        target.id = 2
        target.mention = "<@2>"

        await cog.party_block.callback(cog, interaction, target, reason="спам")

        cog.data_manager.add_block.assert_awaited_once_with(user_id=2, blocked_by=1, reason="спам")
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_party_unblock_removes_record(self, cog: PartyCog) -> None:
        """party_unblock зовёт data_manager.remove_block."""
        cog.data_manager.remove_block = AsyncMock(return_value=True)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(spec=discord.User, id=1)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        target = MagicMock(spec=discord.User)
        target.id = 2
        target.mention = "<@2>"

        await cog.party_unblock.callback(cog, interaction, target)

        cog.data_manager.remove_block.assert_awaited_once_with(user_id=2)
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_party_blocklist_empty(self, cog: PartyCog) -> None:
        """Пустой blacklist — отдельное сообщение про это."""
        cog.data_manager.list_blocks = AsyncMock(return_value=[])

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.party_blocklist.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.await_args.kwargs
        args = interaction.response.send_message.await_args.args
        sent = args[0] if args else kwargs.get("content", "")
        assert "пуст" in sent.lower()

    @pytest.mark.asyncio
    async def test_party_blocklist_lists_records(self, cog: PartyCog) -> None:
        """Непустой blacklist — embed с записями."""
        cog.data_manager.list_blocks = AsyncMock(
            return_value=[{"user_id": 1, "blocked_by": 2, "reason": "спам", "created_at": None}]
        )

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.party_blocklist.callback(cog, interaction)

        kwargs = interaction.response.send_message.await_args.kwargs
        embed = kwargs["embed"]
        assert "<@1>" in embed.description
        assert "спам" in embed.description


class TestPartyCommandGuards:
    """Проверки входной валидации команды /party (без вызова Discord)."""

    @pytest.mark.asyncio
    async def test_blocked_user_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Заблокированный инициатор получает отказ."""
        cog.data_manager.is_blocked = AsyncMock(return_value=True)
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=15, count=3, comment="x")

        send_err.assert_awaited_once()
        assert send_err.await_args.args[1] == "ты в бане"

    @pytest.mark.asyncio
    async def test_too_short_duration_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Длительность ниже min — отказ с упоминанием минимума."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=0, count=3, comment="x")

        send_err.assert_awaited_once()
        assert "Минимум" in send_err.await_args.args[1]

    @pytest.mark.asyncio
    async def test_too_long_duration_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Длительность выше max — отказ с упоминанием максимума."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=999, count=3, comment="x")

        send_err.assert_awaited_once()
        assert "Максимум" in send_err.await_args.args[1]

    @pytest.mark.asyncio
    async def test_count_out_of_range_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Count выше max — отказ."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=15, count=1000, comment="x")

        send_err.assert_awaited_once()
        assert "от" in send_err.await_args.args[1]

    @pytest.mark.asyncio
    async def test_role_not_in_allowlist_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Роль вне списка ролей из /role_assign — отказ."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        cog.role_reaction_manager.get_all_role_reactions = AsyncMock(
            return_value=[{"role_id": 42, "emoji": "🎮", "message_id": 1}]
        )

        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        # role.id=999 — НЕ из allowlist
        role = MagicMock(spec=discord.Role, id=999, mention="<@&999>", name="random", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=15, count=2, comment="x")

        send_err.assert_awaited_once()
        assert "role_assign" in send_err.await_args.args[1]

    @pytest.mark.asyncio
    async def test_role_in_allowlist_passes_role_check(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Если роль в allowlist — проверка роли проходит, ошибка приходит уже от
        дальнейших шагов (тут — длительность вне границ).
        """
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        cog.role_reaction_manager.get_all_role_reactions = AsyncMock(
            return_value=[{"role_id": 42, "emoji": "🎮", "message_id": 1}]
        )

        ctx = MagicMock(spec=commands.Context)
        ctx.guild = MagicMock(spec=discord.Guild, id=1)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", name="ok", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=0, count=2, comment="x")

        send_err.assert_awaited_once()
        # Сообщение про минимум — не про allowlist
        assert "role_assign" not in send_err.await_args.args[1]

    @pytest.mark.asyncio
    async def test_dm_invocation_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Команда из ЛС бота — отдельное локальное сообщение."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        ctx = MagicMock(spec=commands.Context)
        ctx.guild = None
        ctx.author = MagicMock(spec=discord.User, id=100)

        role = MagicMock(spec=discord.Role, id=42, mention="<@&42>", members=[])

        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party.callback(cog, ctx, role=role, when=15, count=3, comment="x")

        send_err.assert_awaited_once()
        assert send_err.await_args.args[1] == "чел ты долбоёб? пиши команду в конфе"


class TestPartyCancel:
    """/party_cancel логика."""

    @pytest.mark.asyncio
    async def test_no_active_returns_error(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Если у юзера нет активных пати — даём ошибку."""
        ctx = MagicMock(spec=commands.Context)
        ctx.author = MagicMock(spec=discord.Member, id=100)
        with patch("cogs.party.safe_send_error", new_callable=AsyncMock) as send_err:
            await cog.party_cancel.callback(cog, ctx)
        send_err.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancels_last_active(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Если есть активное — отменяется и таймер тоже."""
        bot.get_guild.return_value = None
        party = cog.manager.create(
            guild_id=1,
            channel_id=10,
            public_message_id=1000,
            role_id=42,
            initiator_id=100,
            count=1,
            comment="",
            created_at=datetime.now(UTC),
            deadline=datetime.now(UTC) + timedelta(minutes=15),
        )
        timer = MagicMock()
        timer.cancel = MagicMock()
        cog._timers[party.id] = timer

        ctx = MagicMock(spec=commands.Context)
        ctx.author = MagicMock(spec=discord.Member, id=100)

        with patch("cogs.party.safe_send", new_callable=AsyncMock) as send_ok:
            await cog.party_cancel.callback(cog, ctx)

        timer.cancel.assert_called_once()
        assert cog.manager.get(party.id) is None
        send_ok.assert_awaited_once()
