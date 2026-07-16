"""Тесты для PartyCog (кнопочная версия)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.party import PartyCog
from config.settings import BotSettings
from utils.party.manager import PartyPhase
from utils.party.views import (
    PartyConfirmView,
    PartyPublishView,
    PartySetupModal,
    PartyView,
    _PartyDraft,
)


@pytest.fixture
def party_settings() -> BotSettings:
    """Настройки бота с дефолтным блоком party."""
    return BotSettings()


@pytest.fixture
def patched_settings(party_settings: BotSettings):
    """Подменяет get_settings во всех местах, где он импортирован."""
    with (
        patch("cogs.party.get_settings", return_value=party_settings),
        patch("utils.party.views.get_settings", return_value=party_settings),
    ):
        yield party_settings


@pytest.fixture
def bot() -> MagicMock:
    """Бот с .user, get_guild, get_channel, get_user."""
    b = MagicMock(spec=commands.Bot)
    b.user = MagicMock(spec=discord.ClientUser)
    b.user.id = 99
    b.get_guild = MagicMock(return_value=None)
    b.get_channel = MagicMock(return_value=None)
    b.get_user = MagicMock(return_value=None)
    return b


@pytest.fixture
def cog(bot: MagicMock) -> PartyCog:
    """Свежий PartyCog с замоканным role_reaction_manager (по умолчанию пускает role.id=42)."""
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
        sent = MagicMock(spec=discord.Message)
        sent.id = 10000 + user_id
        sent.edit = AsyncMock()
        m.send = AsyncMock(return_value=sent)
    else:
        m.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "DM closed"))
    return m


def _make_party(cog: PartyCog, *, count: int = 2, comment: str = "x", initiator_id: int = 100):
    """Хелпер: создаёт пати в менеджере с дефолтами."""
    return cog.manager.create(
        guild_id=1,
        channel_id=10,
        public_message_id=1000,
        role_id=42,
        initiator_id=initiator_id,
        count=count,
        comment=comment,
        created_at=datetime.now(UTC),
        deadline=datetime.now(UTC) + timedelta(minutes=15),
    )


class TestSendDMs:
    """Тесты _send_dms."""

    @pytest.mark.asyncio
    async def test_skips_initiator_and_bots(
        self, cog: PartyCog, role: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Инициатор и боты пропускаются."""
        initiator = make_member(100)
        member_bot = make_member(200, is_bot=True)
        regular = make_member(300)
        role.members = [initiator, member_bot, regular]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = _make_party(cog, count=2, initiator_id=initiator.id)

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator)

        assert delivered == 1
        regular.send.assert_awaited_once()
        member_bot.send.assert_not_called()
        initiator.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_blocked_users(
        self, cog: PartyCog, role: MagicMock, patched_settings: BotSettings
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

        party = _make_party(cog, count=2, initiator_id=initiator.id)

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator)

        assert delivered == 1
        blocked.send.assert_not_called()
        ok_user.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forbidden_does_not_break_loop(
        self, cog: PartyCog, role: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Если у одного юзера закрыты DM — остальные всё равно получают."""
        initiator = make_member(100)
        closed_dm = make_member(200, can_dm=False)
        ok_user = make_member(300)
        role.members = [closed_dm, ok_user]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = _make_party(cog, count=2, initiator_id=initiator.id)

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            delivered = await cog._send_dms(party, role, initiator)

        assert delivered == 1
        ok_user.send.assert_awaited_once()
        closed_dm.send.assert_awaited_once()
        # Сохранён только успешный
        assert ok_user.id in party.dm_messages
        assert closed_dm.id not in party.dm_messages

    @pytest.mark.asyncio
    async def test_sends_with_view(
        self, cog: PartyCog, role: MagicMock, patched_settings: BotSettings
    ) -> None:
        """В send() передаётся CV2-LayoutView с кнопками (без отдельного embed)."""
        initiator = make_member(100)
        member = make_member(200)
        role.members = [member]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = _make_party(cog, count=2, initiator_id=initiator.id)

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            await cog._send_dms(party, role, initiator)

        member.send.assert_awaited_once()
        kwargs = member.send.await_args.kwargs
        # CV2: контент и кнопки в одном LayoutView, отдельного embed нет.
        assert "embed" not in kwargs
        assert isinstance(kwargs["view"], PartyView)

    @pytest.mark.asyncio
    async def test_stores_message_object(
        self, cog: PartyCog, role: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Возвращённый Message сохраняется в party.dm_messages для последующих edit."""
        initiator = make_member(100)
        member = make_member(200)
        role.members = [member]

        cog.data_manager = MagicMock()
        cog.data_manager.is_blocked = AsyncMock(return_value=False)

        party = _make_party(cog, count=2, initiator_id=initiator.id)

        with patch("cogs.party.asyncio.sleep", new=AsyncMock()):
            await cog._send_dms(party, role, initiator)

        assert party.dm_messages[200] is member.send.return_value


class TestRefreshAllEmbeds:
    """Тесты _refresh_all_embeds — публичный + DM-сообщения."""

    @pytest.mark.asyncio
    async def test_edits_all_dm_messages(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """edit() вызывается на каждом DM-сообщении в party.dm_messages."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]

        party = _make_party(cog, count=2)
        msg_a = MagicMock(spec=discord.Message)
        msg_a.edit = AsyncMock()
        msg_b = MagicMock(spec=discord.Message)
        msg_b.edit = AsyncMock()
        party.dm_messages = {200: msg_a, 300: msg_b}

        await cog._refresh_all_embeds(party)

        msg_a.edit.assert_awaited_once()
        msg_b.edit.assert_awaited_once()
        cog._refresh_public_embed.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_dm_edit_failure_does_not_break_loop(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Если у одного DM edit упал — остальные всё равно обновляются."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]

        party = _make_party(cog, count=2)
        broken = MagicMock(spec=discord.Message)
        broken.edit = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        ok = MagicMock(spec=discord.Message)
        ok.edit = AsyncMock()
        party.dm_messages = {200: broken, 300: ok}

        await cog._refresh_all_embeds(party)

        ok.edit.assert_awaited_once()


class TestPartyView:
    """Тесты кнопок «Готов» / «Не готов»."""

    @pytest.mark.asyncio
    async def test_ready_button_marks_ready(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Нажатие «Готов» переводит юзера в joined и вызывает _refresh_all_embeds."""
        cog._refresh_all_embeds = AsyncMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=3)
        view = PartyView(cog=cog, party=party)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=200)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await view.handle_ready(interaction)

        assert 200 in party.joined_order
        interaction.response.defer.assert_awaited_once()
        cog._refresh_all_embeds.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_decline_button_marks_declined(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Нажатие «Не готов» переводит юзера в declined."""
        cog._refresh_all_embeds = AsyncMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=3)
        view = PartyView(cog=cog, party=party)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=200)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await view.handle_decline(interaction)

        assert 200 in party.declined_order
        interaction.response.defer.assert_awaited_once()
        cog._refresh_all_embeds.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_cooldown_blocks_repeated_press(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Второе нажатие в пределах кулдауна — отказ ephemeral, embed не трогается."""
        cog._refresh_all_embeds = AsyncMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=3)
        view = PartyView(cog=cog, party=party)

        interaction1 = MagicMock(spec=discord.Interaction)
        interaction1.user = MagicMock(id=200)
        interaction1.response = MagicMock()
        interaction1.response.defer = AsyncMock()
        interaction1.response.send_message = AsyncMock()

        await view.handle_ready(interaction1)
        assert cog._refresh_all_embeds.await_count == 1

        # Второе нажатие сразу же — должно быть отвергнуто.
        interaction2 = MagicMock(spec=discord.Interaction)
        interaction2.user = MagicMock(id=200)
        interaction2.response = MagicMock()
        interaction2.response.defer = AsyncMock()
        interaction2.response.send_message = AsyncMock()

        await view.handle_decline(interaction2)

        # Defer не вызывался, ephemeral отправлен, embed не обновлялся.
        interaction2.response.defer.assert_not_called()
        interaction2.response.send_message.assert_awaited_once()
        assert "подожди" in interaction2.response.send_message.await_args.args[0]
        assert cog._refresh_all_embeds.await_count == 1

    @pytest.mark.asyncio
    async def test_finalized_party_blocks_press(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Если пати уже закрыт — кнопка отвечает ephemeral про закрытие."""
        cog._refresh_all_embeds = AsyncMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=3)
        view = PartyView(cog=cog, party=party)
        await cog.manager.cancel(party.id)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=200)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await view.handle_ready(interaction)

        interaction.response.defer.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        assert "закрыт" in interaction.response.send_message.await_args.args[0].lower()


class TestFinalize:
    """Тесты _finalize."""

    @pytest.mark.asyncio
    async def test_pings_ready_users(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
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

        party = _make_party(cog, count=2, comment="идём ранкед")
        await cog.manager.mark_ready(party.id, user_id=200)

        await cog._finalize(party)

        channel.send.assert_awaited_once()
        sent_text = channel.send.await_args.args[0]
        assert "<@100>" in sent_text
        assert "<@200>" in sent_text
        assert "идём ранкед" in sent_text
        assert "Гремлины" in sent_text
        assert "<@&42>" not in sent_text
        assert party.finalized is True

    @pytest.mark.asyncio
    async def test_incomplete_party_uses_empty_template(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Если набрано меньше count — empty_finished_message со списком готовых."""
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

        party = _make_party(cog, count=3, comment="тестим")

        await cog._finalize(party)

        channel.send.assert_awaited_once()
        sent_text = channel.send.await_args.args[0]
        assert "Не набрали состав" in sent_text
        # Состав не набран, но тех, кто был готов (инициатор), всё равно пингуем.
        assert "<@100>" in sent_text
        assert "<@&42>" not in sent_text

    @pytest.mark.asyncio
    async def test_finalize_disables_dm_buttons(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Финализация заменяет DM на карточку-финал без кнопок управления."""
        bot.get_guild.return_value = None  # без публикации в канал — не важно
        party = _make_party(cog, count=3)
        msg_a = MagicMock(spec=discord.Message)
        msg_a.edit = AsyncMock()
        party.dm_messages = {200: msg_a}

        await cog._finalize(party)

        msg_a.edit.assert_awaited_once()
        view = msg_a.edit.await_args.kwargs["view"]
        assert isinstance(view, discord.ui.LayoutView)
        # Карточка-финал: без интерактивных кнопок «Готов»/«Подтверждаю».
        assert not [c for c in view.walk_children() if isinstance(c, discord.ui.Button)]

    @pytest.mark.asyncio
    async def test_finalize_idempotent(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Повторный _finalize ничего не делает."""
        bot.get_guild.return_value = None
        party = _make_party(cog, count=1)
        party.finalized = True
        await cog._finalize(party)


class TestReadyCheck:
    """Фаза чека готовности: старт, подтверждение, частичный финал."""

    @pytest.mark.asyncio
    async def test_maybe_start_triggers_when_full(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """При полной основе чек стартует, кандидату ставится confirm-view."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        cog._start_check_loop = MagicMock()  # type: ignore[method-assign]

        party = _make_party(cog, count=2)
        await cog.manager.mark_ready(party.id, user_id=200)

        msg_init = MagicMock(spec=discord.Message)
        msg_init.edit = AsyncMock()
        msg_init.channel.send = AsyncMock()
        msg_member = MagicMock(spec=discord.Message)
        msg_member.edit = AsyncMock()
        msg_member.channel.send = AsyncMock()
        party.dm_messages = {100: msg_init, 200: msg_member}

        await cog._maybe_start_ready_check(party)

        assert party.phase is PartyPhase.READY_CHECK
        cog._start_check_loop.assert_called_once()
        # Подтверждённый инициатор — карточка без кнопок, кандидат — с confirm-view.
        init_view = msg_init.edit.await_args.kwargs["view"]
        assert isinstance(init_view, discord.ui.LayoutView)
        assert not isinstance(init_view, (PartyConfirmView, PartyView))
        assert isinstance(msg_member.edit.await_args.kwargs["view"], PartyConfirmView)
        # Кандидата (но не авто-подтверждённого инициатора) пингуем отдельным сообщением.
        msg_member.channel.send.assert_awaited_once()
        assert "<@200>" in msg_member.channel.send.await_args.args[0]
        msg_init.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_start_disabled_noop(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """С выключенным чеком фаза остаётся COLLECTING."""
        patched_settings.party.enable_ready_check = False
        cog._start_check_loop = MagicMock()  # type: ignore[method-assign]

        party = _make_party(cog, count=2)
        await cog.manager.mark_ready(party.id, user_id=200)

        await cog._maybe_start_ready_check(party)

        assert party.phase is PartyPhase.COLLECTING
        cog._start_check_loop.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_user_sends_ping_message(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """_nudge_user шлёт отдельное сообщение с упоминанием и текстом."""
        party = _make_party(cog, count=2)
        msg = MagicMock(spec=discord.Message)
        msg.channel.send = AsyncMock()
        party.dm_messages = {200: msg}

        await cog._nudge_user(party, 200, "подтвердись!")

        msg.channel.send.assert_awaited_once_with("<@200> подтвердись!")

    @pytest.mark.asyncio
    async def test_nudge_user_no_dm_is_noop(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Без DM-сообщения юзера нудж тихо ничего не делает."""
        party = _make_party(cog, count=2)
        party.dm_messages = {}

        await cog._nudge_user(party, 200, "подтвердись!")

    @pytest.mark.asyncio
    async def test_confirm_button_confirms_user(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Кнопка «Подтверждаю» переносит юзера в confirmed и зовёт _after_confirm."""
        cog._after_confirm = AsyncMock()  # type: ignore[method-assign]
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        cog._start_check_loop = MagicMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=2)
        await cog.manager.mark_ready(party.id, user_id=200)
        await cog._maybe_start_ready_check(party)

        view = PartyConfirmView(cog=cog, party=party)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=200)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await view.handle_confirm(interaction)

        assert 200 in party.confirmed
        interaction.response.defer.assert_awaited_once()
        cog._after_confirm.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_confirm_button_on_closed_party(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Если пати закрыт — confirm отвечает ephemeral, состояние не трогает."""
        cog._after_confirm = AsyncMock()  # type: ignore[method-assign]
        party = _make_party(cog, count=2)
        view = PartyConfirmView(cog=cog, party=party)
        await cog.manager.cancel(party.id)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=200)
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await view.handle_confirm(interaction)

        interaction.response.defer.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        cog._after_confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_after_confirm_finalizes_when_full(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """_after_confirm закрывает сбор, когда подтвердили весь состав."""
        cog._sync_check_views = AsyncMock()  # type: ignore[method-assign]
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        cog._finalize = AsyncMock()  # type: ignore[method-assign]

        party = _make_party(cog, count=2)
        party.confirmed = [100, 200]

        await cog._after_confirm(party)

        cog._finalize.assert_awaited_once_with(party)

    @pytest.mark.asyncio
    async def test_finalize_partial_pings_confirmed(
        self, cog: PartyCog, bot: MagicMock, patched_settings: BotSettings
    ) -> None:
        """Частичный финал после чека пингует только подтвердивших по partial-шаблону."""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 1
        role = MagicMock(spec=discord.Role)
        role.id = 42
        role.name = "Гремлины"
        guild.get_role = MagicMock(return_value=role)
        bot.get_guild.return_value = guild

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.send = AsyncMock()
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        bot.get_channel.return_value = channel

        party = _make_party(cog, count=3, comment="го")
        party.ready_check_started = True
        party.confirmed = [100, 200]
        party.not_confirmed = [300]

        await cog._finalize(party)

        sent_text = channel.send.await_args.args[0]
        assert "частично" in sent_text
        assert "<@100>" in sent_text
        assert "<@200>" in sent_text
        assert "<@300>" not in sent_text


def _slash_interaction(user_id: int = 100, guild_id: int | None = 1) -> MagicMock:
    """Готовит мок slash-Interaction для /party."""
    interaction = MagicMock(spec=discord.Interaction)
    if guild_id is None:
        interaction.guild = None
    else:
        guild = MagicMock(spec=discord.Guild, id=guild_id)
        guild.get_role = MagicMock(
            return_value=MagicMock(spec=discord.Role, id=42, name="Гремлины", mention="<@&42>")
        )
        interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member, id=user_id)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    return interaction


class TestPartySlashCommand:
    """Слэш-команда /party и пошаговый мастер."""

    @pytest.mark.asyncio
    async def test_dm_invocation_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Вне сервера мастер не открывается."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        interaction = _slash_interaction(guild_id=None)

        await cog.party.callback(cog, interaction, image=None)

        interaction.response.send_message.assert_awaited_once()
        assert "конфе" in interaction.response.send_message.await_args.kwargs["embed"].description

    @pytest.mark.asyncio
    async def test_blocked_user_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Забаненный инициатор получает отказ ещё до выбора роли."""
        cog.data_manager.is_blocked = AsyncMock(return_value=True)
        interaction = _slash_interaction()

        await cog.party.callback(cog, interaction, image=None)

        interaction.response.send_message.assert_awaited_once()
        assert (
            interaction.response.send_message.await_args.kwargs["embed"].description == "ты в бане"
        )

    @pytest.mark.asyncio
    async def test_cooldown_blocks_reopen(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Недавняя публикация держит кулдаун — мастер не открывается."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        cog._last_party[100] = datetime.now(UTC)
        interaction = _slash_interaction()

        await cog.party.callback(cog, interaction, image=None)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert "через" in embed.description

    @pytest.mark.asyncio
    async def test_no_roles_rejected(self, cog: PartyCog, patched_settings: BotSettings) -> None:
        """Без ролей из /role_assign мастер не открывается."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        cog.role_reaction_manager.get_all_role_reactions = AsyncMock(return_value=[])
        interaction = _slash_interaction()

        await cog.party.callback(cog, interaction, image=None)

        interaction.response.send_message.assert_awaited_once()
        assert (
            "Нет доступных ролей"
            in interaction.response.send_message.await_args.kwargs["embed"].description
        )

    @pytest.mark.asyncio
    async def test_opens_modal_with_roles(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """С доступными ролями ``/party`` открывает модалку сбора (Modal v2)."""
        cog.data_manager.is_blocked = AsyncMock(return_value=False)
        interaction = _slash_interaction()

        await cog.party.callback(cog, interaction, image=None)

        interaction.response.send_modal.assert_awaited_once()
        modal = interaction.response.send_modal.await_args.args[0]
        assert isinstance(modal, PartySetupModal)
        # send_message (с ошибкой) при успехе не дёргается.
        interaction.response.send_message.assert_not_called()


class TestPartySetupModal:
    """Единая модалка сбора (Modal v2): валидация и переход к превью."""

    def _make_modal(self, cog: PartyCog) -> PartySetupModal:
        initiator = MagicMock(spec=discord.Member, id=100)
        initiator.guild = MagicMock(spec=discord.Guild, id=1)
        role = MagicMock(spec=discord.Role, id=42, name="Гремлины", mention="<@&42>")
        return PartySetupModal(cog=cog, initiator=initiator, roles=[role], image_url=None)

    @pytest.mark.asyncio
    async def test_valid_submit_shows_publish_view(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Корректный ввод показывает превью с :class:`PartyPublishView`."""
        modal = self._make_modal(cog)
        modal._role_select = MagicMock(values=["42"])  # type: ignore[assignment]
        modal._duration_input = MagicMock(value=" 30 ")  # type: ignore[assignment]
        modal._size_input = MagicMock(value="5")  # type: ignore[assignment]
        modal._comment_input = MagicMock(value="  го  ")  # type: ignore[assignment]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.await_args.kwargs
        assert kwargs["ephemeral"] is True
        view = kwargs["view"]
        assert isinstance(view, PartyPublishView)
        assert view._draft == _PartyDraft(role_id=42, minutes=30, count=5, comment="го")

    @pytest.mark.asyncio
    async def test_non_numeric_minutes_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Нечисловое время — ephemeral-подсказка, превью не показывается."""
        modal = self._make_modal(cog)
        modal._role_select = MagicMock(values=["42"])  # type: ignore[assignment]
        modal._duration_input = MagicMock(value="скоро")  # type: ignore[assignment]
        modal._size_input = MagicMock(value="5")  # type: ignore[assignment]
        modal._comment_input = MagicMock(value="")  # type: ignore[assignment]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        assert "число" in interaction.response.send_message.await_args.args[0]
        assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_minutes_out_of_range_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Время за пределами лимитов отбраковывается без превью."""
        modal = self._make_modal(cog)
        modal._role_select = MagicMock(values=["42"])  # type: ignore[assignment]
        modal._duration_input = MagicMock(  # type: ignore[assignment]
            value=str(patched_settings.party.max_duration_minutes + 1)
        )
        modal._size_input = MagicMock(value="5")  # type: ignore[assignment]
        modal._comment_input = MagicMock(value="")  # type: ignore[assignment]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        assert "Время" in interaction.response.send_message.await_args.args[0]

    @pytest.mark.asyncio
    async def test_non_numeric_count_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Нечисловой состав — ephemeral-подсказка, превью не показывается."""
        modal = self._make_modal(cog)
        modal._role_select = MagicMock(values=["42"])  # type: ignore[assignment]
        modal._duration_input = MagicMock(value="30")  # type: ignore[assignment]
        modal._size_input = MagicMock(value="пятеро")  # type: ignore[assignment]
        modal._comment_input = MagicMock(value="")  # type: ignore[assignment]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        assert "Состав" in interaction.response.send_message.await_args.args[0]
        assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_count_out_of_range_rejected(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Состав за пределами лимитов отбраковывается без превью."""
        modal = self._make_modal(cog)
        modal._role_select = MagicMock(values=["42"])  # type: ignore[assignment]
        modal._duration_input = MagicMock(value="30")  # type: ignore[assignment]
        modal._size_input = MagicMock(  # type: ignore[assignment]
            value=str(patched_settings.party.max_count + 1)
        )
        modal._comment_input = MagicMock(value="")  # type: ignore[assignment]

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        assert "Состав" in interaction.response.send_message.await_args.args[0]


class TestPartyPublishView:
    """Превью сбора: публикация / переоткрытие модалки / отмена."""

    def _make_view(self, cog: PartyCog) -> PartyPublishView:
        initiator = MagicMock(spec=discord.Member, id=100)
        initiator.guild = MagicMock(spec=discord.Guild, id=1)
        role = MagicMock(spec=discord.Role, id=42, name="Гремлины", mention="<@&42>")
        draft = _PartyDraft(role_id=42, minutes=30, count=3, comment="го")
        return PartyPublishView(
            cog=cog, initiator=initiator, roles=[role], image_url=None, draft=draft
        )

    @pytest.mark.asyncio
    async def test_publish_calls_create_and_broadcast(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """«Опубликовать» зовёт _create_and_broadcast и закрывает превью."""
        cog._create_and_broadcast = AsyncMock(return_value=None)  # type: ignore[method-assign]
        view = self._make_view(cog)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock(spec=discord.Guild, id=1)
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        await view.handle_publish(interaction)

        interaction.response.edit_message.assert_awaited_once()
        cog._create_and_broadcast.assert_awaited_once()
        ca = cog._create_and_broadcast.await_args.kwargs
        assert ca["count"] == 3
        assert ca["duration"] == timedelta(minutes=30)

    @pytest.mark.asyncio
    async def test_edit_reopens_modal(self, cog: PartyCog, patched_settings: BotSettings) -> None:
        """«Изменить» переоткрывает модалку с уже заполненными значениями."""
        view = self._make_view(cog)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.send_modal = AsyncMock()

        await view.handle_edit(interaction)

        interaction.response.send_modal.assert_awaited_once()
        modal = interaction.response.send_modal.await_args.args[0]
        assert isinstance(modal, PartySetupModal)

    @pytest.mark.asyncio
    async def test_cancel_closes_preview(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """«Отмена» редактирует превью в служебное сообщение."""
        view = self._make_view(cog)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.edit_message = AsyncMock()

        await view.handle_cancel(interaction)

        interaction.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_only_author_passes_interaction_check(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Чужой пользователь не проходит interaction_check превью."""
        view = self._make_view(cog)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(id=999)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        assert await view.interaction_check(interaction) is False
        interaction.response.send_message.assert_awaited_once()


class TestCreateAndBroadcast:
    """Публикация сбора без привязки к Context (общий путь /party и панели)."""

    @pytest.mark.asyncio
    async def test_publishes_and_schedules(
        self, cog: PartyCog, patched_settings: BotSettings
    ) -> None:
        """Постит placeholder, создаёт пати, рассылает DM и заводит таймер."""
        cog._refresh_public_embed = AsyncMock()  # type: ignore[method-assign]
        cog._refresh_all_embeds = AsyncMock()  # type: ignore[method-assign]
        cog._send_dms = AsyncMock(return_value=0)  # type: ignore[method-assign]
        cog._finalize_after = AsyncMock()  # type: ignore[method-assign]

        guild = MagicMock(spec=discord.Guild, id=1)
        public = MagicMock(spec=discord.Message)
        public.id = 555
        public.channel = MagicMock()
        public.channel.id = 10
        channel = MagicMock()
        channel.send = AsyncMock(return_value=public)

        role = MagicMock(spec=discord.Role, id=42, name="x", members=[])
        initiator = make_member(100)

        party = await cog._create_and_broadcast(
            guild=guild,
            channel=channel,
            role=role,
            initiator=initiator,
            duration=timedelta(minutes=15),
            count=2,
            comment="c",
            image_url=None,
        )

        assert party is not None
        assert cog.manager.get(party.id) is party
        channel.send.assert_awaited_once()
        cog._send_dms.assert_awaited_once()
        assert party.id in cog._timers

        cog._timers[party.id].cancel()


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
        """party_unblock парсит строковый id из автокомплита и зовёт remove_block."""
        cog.data_manager.remove_block = AsyncMock(return_value=True)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(spec=discord.User, id=1)
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.party_unblock.callback(cog, interaction, "2")

        cog.data_manager.remove_block.assert_awaited_once_with(user_id=2)
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_party_unblock_invalid_id(self, cog: PartyCog) -> None:
        """Некорректный id не доходит до data_manager и отдаёт ошибку."""
        cog.data_manager.remove_block = AsyncMock(return_value=True)

        interaction = _slash_interaction()

        await cog.party_unblock.callback(cog, interaction, "не-число")

        cog.data_manager.remove_block.assert_not_awaited()
        embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert "Некорректный" in embed.description

    @pytest.mark.asyncio
    async def test_party_unblock_autocomplete(self, cog: PartyCog) -> None:
        """Автокомплит отдаёт только заблокированных и фильтрует по вводу."""
        cog.data_manager.list_blocks = AsyncMock(
            return_value=[
                {"user_id": 2, "blocked_by": 1, "reason": "спам"},
                {"user_id": 3, "blocked_by": 1, "reason": None},
            ]
        )

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = None

        choices = await cog.party_unblock_autocomplete(interaction, "")
        assert {c.value for c in choices} == {"2", "3"}
        assert any("спам" in c.name for c in choices)

        filtered = await cog.party_unblock_autocomplete(interaction, "2")
        assert [c.value for c in filtered] == ["2"]

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
        party = _make_party(cog, count=1)
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
