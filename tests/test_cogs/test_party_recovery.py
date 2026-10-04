"""Восстановление сборов и гонки записи без доступа к runtime-файлам и Discord."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands
from freezegun import freeze_time

from cogs.party import PartyCog
from config.settings import BotSettings
from utils.party.manager import Party, PartyPhase
from utils.party.state import PartyRecord, PartySnapshot, PartyStateStore
from utils.party.views import PartyConfirmView, PartyView


@pytest.fixture
def settings():
    """Подменяет настройки, не читая .env."""
    value = BotSettings(_env_file=None)
    value.guild_id = 1
    value.party.dm_send_delay = 0
    with (
        patch("cogs.party.get_settings", return_value=value),
        patch("utils.party.views.get_settings", return_value=value),
    ):
        yield value


@pytest.fixture
def cog(settings) -> PartyCog:
    """Изолированный ког с памятью вместо реального файла."""
    bot = MagicMock(spec=commands.Bot)
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_role.return_value.name = "Игра"
    bot.get_guild.return_value = guild
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 10
    channel.fetch_message.return_value = MagicMock(spec=discord.Message)
    bot.get_channel.return_value = channel
    store = MagicMock(spec=PartyStateStore)
    store.load.return_value = PartySnapshot(version=1, parties=[], cooldowns={})
    store.save = AsyncMock()
    result = PartyCog(bot, state_store=store)
    result._loaded = True
    result._build_container = MagicMock(side_effect=lambda *a, **kw: discord.ui.Container())
    result.data_manager.is_blocked = AsyncMock(return_value=False)
    return result


def make_party(cog: PartyCog, *, count: int = 2) -> Party:
    """Создаёт обычный сбор с будущим абсолютным дедлайном."""
    now = datetime.now(UTC)
    return cog.manager.create(
        guild_id=1,
        channel_id=10,
        public_message_id=1000,
        role_id=42,
        initiator_id=100,
        count=count,
        comment="Играем",
        created_at=now - timedelta(minutes=10),
        deadline=now + timedelta(minutes=10),
        finish_when_full=True,
    )


def add_saved_dm(cog: PartyCog, party: Party, user_id: int) -> MagicMock:
    """Сохраняет ID приглашения и настраивает поиск того же сообщения при restore."""
    message = MagicMock(spec=discord.Message)
    message.id = 10000 + user_id
    message.channel.id = 20000 + user_id
    user = MagicMock(spec=discord.User)
    user.id = user_id
    dm = MagicMock(spec=discord.DMChannel)
    dm.id = message.channel.id
    dm.fetch_message.return_value = message
    user.create_dm.return_value = dm
    existing = getattr(cog.bot, "saved_users", {})
    if not isinstance(existing, dict):
        existing = {}
    existing[user_id] = user
    cog.bot.saved_users = existing
    cog.bot.get_user.side_effect = existing.get
    party.dm_message_ids[user_id] = (dm.id, message.id)
    return message


def interaction(user_id: int) -> MagicMock:
    """Интеракция с настоящими async response-методами."""
    value = MagicMock(spec=discord.Interaction)
    value.user.id = user_id
    value.response.defer = AsyncMock()
    value.response.send_message = AsyncMock()
    return value


async def restore_once(cog: PartyCog, snapshot: PartySnapshot) -> None:
    """Проходит один полный цикл восстановления, останавливая только retry sleep."""
    cog.manager = type(cog.manager)()
    cog._loaded = False
    cog._state_store.load.return_value = snapshot
    with patch("cogs.party.asyncio.sleep", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await cog._restore_loop()


async def test_restart_restores_pending_reserve_views_and_cooldowns(cog: PartyCog) -> None:
    """Рестарт сохраняет FIFO, личный deadline и привязывает кнопки к прежним DM."""
    party = make_party(cog)
    party.joined_order = [100, 200, 300]
    party.phase = PartyPhase.READY_CHECK
    party.ready_check_started = True
    party.confirmed = [100]
    personal_deadline = datetime.now(UTC) + timedelta(minutes=2)
    party.confirm_deadlines = {200: personal_deadline}
    pending_message = add_saved_dm(cog, party, 200)
    reserve_message = add_saved_dm(cog, party, 300)
    cooldown = datetime.now(UTC) - timedelta(seconds=30)
    party.last_press = {300: cooldown}
    snapshot = PartySnapshot(
        version=1, parties=[PartyRecord.from_party(party)], cooldowns={100: cooldown}
    )

    await restore_once(cog, PartySnapshot.model_validate_json(snapshot.model_dump_json()))

    restored = cog.manager.get(party.id)
    assert restored is not None
    assert restored.joined_order == [100, 200, 300]
    assert restored.confirm_deadlines == {200: personal_deadline}
    assert restored.confirmed == [100]
    assert restored.last_press == {300: cooldown}
    assert restored.deadline == party.deadline
    assert cog._last_party == {100: cooldown}
    assert isinstance(pending_message.edit.call_args.kwargs["view"], PartyConfirmView)
    assert isinstance(reserve_message.edit.call_args.kwargs["view"], PartyView)
    pending_message.channel.send.assert_not_called()
    reserve_message.channel.send.assert_not_called()
    assert party.id in cog._timers and party.id in cog._check_timers
    assert not cog._recovering
    await cog.cog_unload()


@pytest.mark.parametrize("deleted", [False, True])
async def test_expiry_closes_domain_before_inaccessible_public_fetch(
    cog: PartyCog, deleted: bool
) -> None:
    """Даже пропавший/закрытый канал не оставляет просроченный сбор активным."""
    party = make_party(cog)
    party.deadline = datetime.now(UTC) - timedelta(seconds=1)
    message = add_saved_dm(cog, party, 200)
    cog.bot.get_channel.return_value = None
    error_type = discord.NotFound if deleted else discord.Forbidden
    error = error_type(MagicMock(status=404 if deleted else 403), "unavailable")

    async def fetch_channel(_channel_id):
        assert cog.manager.get(party.id) is None
        assert cog._state_store.save.call_args.args[0].parties[0].finalized
        raise error

    cog.bot.fetch_channel.side_effect = fetch_channel
    finished = await cog._restore_party(party)

    assert party.finalized and party.final_notice_attempted
    assert cog.manager.get(party.id) is None
    message.edit.assert_awaited_once()
    message.channel.send.assert_not_called()
    assert finished is deleted
    assert (party.id in cog._closing) is not deleted


async def test_restore_sweeps_expired_confirmation_before_views(cog: PartyCog) -> None:
    """Старый кандидат выбывает до открытия кнопок, резерв поднимается по FIFO."""
    party = make_party(cog)
    party.phase = PartyPhase.READY_CHECK
    party.ready_check_started = True
    party.joined_order = [100, 200, 300, 400]
    party.confirmed = [100]
    party.confirm_deadlines = {200: datetime.now(UTC) - timedelta(seconds=1)}
    promoted = add_saved_dm(cog, party, 300)
    assert await cog._restore_party(party)
    assert party.joined_order == [100, 300, 400]
    assert party.not_confirmed == [200]
    assert list(party.confirm_deadlines) == [300]
    assert isinstance(promoted.edit.call_args.kwargs["view"], PartyConfirmView)
    promoted.channel.send.assert_not_called()
    await cog.cog_unload()


@freeze_time("2026-10-05 12:00:00")
@pytest.mark.parametrize("overall", [False, True])
async def test_confirm_rejects_absolute_deadline_boundary(cog: PartyCog, overall: bool) -> None:
    """Кнопка не принимает просроченный confirm до первого тика таймера."""
    party = make_party(cog)
    party.phase = PartyPhase.READY_CHECK
    party.ready_check_started = True
    party.joined_order = [100, 200]
    party.confirmed = [100]
    now = datetime.now(UTC)
    party.confirm_deadlines = {200: now + timedelta(seconds=10) if overall else now}
    if overall:
        party.deadline = now
    click = interaction(200)
    await PartyConfirmView(cog=cog, party=party).handle_confirm(click)
    assert party.confirmed == [100]
    click.response.defer.assert_not_awaited()
    click.response.send_message.assert_awaited_once()
    cog._state_store.save.assert_not_awaited()


async def test_write_failure_blocks_actions_without_success_refresh(cog: PartyCog) -> None:
    """Неудачная запись не подтверждается обновлением карточки и блокирует следующие клики."""
    party = make_party(cog)
    cog._state_store.save.side_effect = OSError("disk full")
    cog._refresh_all_embeds = AsyncMock()
    view = PartyView(cog=cog, party=party)
    with pytest.raises(OSError, match="disk full"):
        await view.handle_ready(interaction(200))
    assert cog._state_error
    cog._refresh_all_embeds.assert_not_awaited()
    with pytest.raises(RuntimeError):
        await view.handle_ready(interaction(300))
    assert 300 not in party.joined_order
    cog._state_store.save.assert_awaited_once()


async def test_corrupt_load_blocks_new_parties_and_does_not_save(cog: PartyCog) -> None:
    """Ошибка чтения не подменяется пустым файлом ни при restore, ни при unload."""
    cog._loaded = False
    cog._state_store.load.side_effect = ValueError("corrupt snapshot")
    await cog._restore_loop()
    assert cog._state_error
    with pytest.raises(RuntimeError):
        cog.ensure_available()
    await cog.cog_unload()
    cog._state_store.save.assert_not_awaited()


async def test_reconnect_does_not_reload_snapshot(cog: PartyCog) -> None:
    """Повторный ready использует ту же задачу, не откатывая состояние к файлу."""
    started = asyncio.Event()
    wait = asyncio.Event()

    async def restore():
        started.set()
        await wait.wait()

    cog._restore_loop = AsyncMock(side_effect=restore)
    await cog.on_ready()
    await started.wait()
    task = cog._restore_task
    await cog.on_ready()
    assert cog._restore_task is task
    cog._restore_loop.assert_awaited_once()
    await cog.cog_unload()


async def test_failed_claim_never_sends_final_notice(cog: PartyCog) -> None:
    """Финальный пинг разрешён только после сохранённого terminal marker."""
    party = make_party(cog)
    cog._state_store.save.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await cog._finalize(party)
    cog.bot.get_channel.return_value.send.assert_not_called()
    assert cog._state_error


async def test_crash_after_claim_does_not_repeat_final_notice(cog: PartyCog) -> None:
    """Неопределённый результат финального send после рестарта не повторяется."""
    party = make_party(cog)
    channel = cog.bot.get_channel.return_value
    channel.send.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await cog._finalize(party)
    recorded = cog._state_store.save.call_args.args[0]
    assert recorded.parties[0].finalized
    assert recorded.parties[0].final_notice_attempted
    channel.send.assert_awaited_once()
    channel.send.reset_mock()
    channel.send.side_effect = None

    await restore_once(cog, recorded)

    assert not cog.manager.all_active()
    assert not cog._closing
    channel.send.assert_not_called()
    assert cog._state_store.save.call_args.args[0].parties == []
    await cog.cog_unload()


async def test_finalize_keeps_tombstone_for_inflight_dm(cog: PartyCog) -> None:
    """Позднее принятое приглашение не теряется из cleanup journal."""
    party = make_party(cog)
    message = add_saved_dm(cog, party, 200)
    party.dm_message_ids.clear()
    message.edit.side_effect = discord.Forbidden(MagicMock(status=403), "edit denied")
    entered = asyncio.Event()
    release = asyncio.Event()
    member = MagicMock(spec=discord.Member)
    member.id, member.bot = 200, False

    async def send(**_kwargs):
        entered.set()
        await release.wait()
        return message

    member.send = AsyncMock(side_effect=send)
    role = MagicMock(spec=discord.Role)
    role.members = [member]
    initiator = MagicMock(id=100)
    broadcast = asyncio.create_task(cog._send_dms(party, role, initiator))
    await entered.wait()
    await cog._finalize(party)
    assert party.id in cog._closing
    release.set()
    await broadcast
    assert party.id in cog._closing
    assert party.dm_message_ids == {200: (20200, 10200)}
    message.edit.side_effect = None
    assert await cog._restore_party(party)
    assert party.id not in cog._closing
    cog.bot.get_channel.return_value.send.assert_awaited_once()


async def test_unload_waits_for_inflight_dm_before_last_save(cog: PartyCog) -> None:
    """Старый ког не записывает поздний send поверх состояния нового после unload."""
    party = make_party(cog)
    message = add_saved_dm(cog, party, 200)
    party.dm_message_ids.clear()
    entered = asyncio.Event()
    release = asyncio.Event()
    member = MagicMock(spec=discord.Member)
    member.id, member.bot = 200, False

    async def send(**_kwargs):
        entered.set()
        await release.wait()
        return message

    member.send = AsyncMock(side_effect=send)
    role = MagicMock(spec=discord.Role)
    role.members = [member]
    broadcast = asyncio.create_task(cog._send_dms(party, role, MagicMock(id=100)))
    await entered.wait()
    unload = asyncio.create_task(cog.cog_unload())
    await asyncio.sleep(0)
    assert not unload.done()
    release.set()
    await asyncio.gather(broadcast, unload)
    saved = cog._state_store.save.call_args.args[0]
    assert saved.parties[0].dm_message_ids == {200: (20200, 10200)}
    assert not saved.parties[0].finalized
    assert not cog._broadcast_tasks


async def test_late_finalize_callback_does_not_write_after_unload(cog: PartyCog) -> None:
    """Финализация из callback не перезаписывает файл после передачи новому когу."""
    party = make_party(cog)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(*_args, **_kwargs):
        entered.set()
        await release.wait()

    cog.bot.get_channel.return_value.send.side_effect = send
    finalizing = asyncio.create_task(cog._finalize(party))
    await entered.wait()
    await cog.cog_unload()
    saves = cog._state_store.save.await_count
    release.set()
    await finalizing
    assert cog._state_store.save.await_count == saves
    assert cog._state_store.save.call_args.args[0].parties[0].finalized


async def test_button_mutation_waits_for_previous_save(cog: PartyCog) -> None:
    """Второй клик не меняет снимок, пока первая атомарная запись не завершилась."""
    party = make_party(cog, count=5)
    cog._refresh_all_embeds = AsyncMock()
    cog._maybe_start_ready_check = AsyncMock()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def save(_snapshot):
        entered.set()
        await release.wait()

    cog._state_store.save.side_effect = save
    view = PartyView(cog=cog, party=party)
    first = asyncio.create_task(view.handle_ready(interaction(200)))
    await entered.wait()
    second = asyncio.create_task(view.handle_ready(interaction(300)))
    await asyncio.sleep(0)
    assert party.joined_order == [100, 200]
    release.set()
    await asyncio.gather(first, second)
    assert party.joined_order == [100, 200, 300]
    assert cog._state_store.save.await_count == 2
