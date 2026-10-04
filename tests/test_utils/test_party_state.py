"""Снимок Party сохраняет состав и безопасно переживает сбой записи."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from utils.party.manager import Party, PartyPhase
from utils.party.state import PartyRecord, PartySnapshot, PartyStateStore

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone(timedelta(hours=3)))


@pytest.fixture
def party() -> Party:
    return Party(
        id="a" * 32,
        guild_id=100,
        channel_id=200,
        public_message_id=300,
        role_id=400,
        initiator_id=11,
        count=2,
        comment="Пати вечером — без спешки",
        created_at=NOW,
        deadline=NOW + timedelta(hours=2),
        image_url="https://example.org/party.png",
        finish_when_full=True,
        joined_order=[11, 12, 13, 14],
        declined_order=[15],
        dm_message_ids={11: (1011, 2011), 12: (1012, 2012), 15: (1015, 2015)},
        last_press={11: NOW + timedelta(seconds=2), 15: NOW + timedelta(seconds=4)},
        phase=PartyPhase.READY_CHECK,
        confirmed=[11],
        confirm_deadlines={12: NOW + timedelta(minutes=5)},
        not_confirmed=[16],
        ready_check_started=True,
        finalized=False,
        final_notice_attempted=False,
    )


@pytest.fixture
def snapshot(party: Party) -> PartySnapshot:
    return PartySnapshot(
        version=1,
        parties=[PartyRecord.from_party(party)],
        cooldowns={11: NOW + timedelta(minutes=10)},
    )


def test_missing_file_loads_empty_snapshot_without_creating_data(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "party_state.json"
    loaded = PartyStateStore(path).load()
    assert loaded == PartySnapshot(version=1, parties=[], cooldowns={})
    assert not path.exists()
    assert not path.parent.exists()


async def test_ready_check_roundtrip_preserves_roster_ids_deadlines_and_cooldowns(
    tmp_path: Path, party: Party, snapshot: PartySnapshot
) -> None:
    path = tmp_path / "nested" / "party_state.json"
    await PartyStateStore(path).save(snapshot)
    restored = PartyStateStore(path).load()
    assert restored == snapshot
    recovered = restored.parties[0].to_party()
    assert recovered == party
    assert recovered.phase is PartyPhase.READY_CHECK
    assert recovered.ready == [11, 12]
    assert recovered.bench == [13, 14]
    assert recovered.declined == [15]
    assert recovered.pending_confirm == [12]
    assert recovered.dm_message_ids[12] == (1012, 2012)
    assert recovered.confirm_deadlines[12] == NOW + timedelta(minutes=5)
    assert recovered.last_press[15] == NOW + timedelta(seconds=4)
    assert recovered.not_confirmed == [16]
    assert restored.cooldowns[11] == NOW + timedelta(minutes=10)
    assert recovered.deadline.utcoffset() == timedelta(hours=3)
    assert "Пати вечером" in path.read_text(encoding="utf-8")
    assert not path.with_suffix(".tmp").exists()


def test_record_is_detached_from_mutable_party_and_omits_discord_objects(party: Party) -> None:
    party.dm_messages[11] = object()
    record = PartyRecord.from_party(party)
    party.joined_order.append(99)
    party.dm_message_ids[11] = (9000, 9001)
    party.confirm_deadlines.clear()
    recovered = record.to_party()
    assert recovered.joined_order == [11, 12, 13, 14]
    assert recovered.dm_message_ids[11] == (1011, 2011)
    assert recovered.confirm_deadlines == {12: NOW + timedelta(minutes=5)}
    assert recovered.dm_messages == {}
    assert "dm_messages" not in record.model_dump()
    recovered.joined_order.clear()
    assert record.joined_order == [11, 12, 13, 14]


async def test_closed_party_and_final_notice_marker_survive_restart(
    tmp_path: Path, party: Party
) -> None:
    party.finalized = True
    party.final_notice_attempted = True
    store = PartyStateStore(tmp_path / "party_state.json")
    await store.save(
        PartySnapshot(version=1, parties=[PartyRecord.from_party(party)], cooldowns={})
    )
    recovered = PartyStateStore(store.path).load().parties[0].to_party()
    assert recovered.finalized is True
    assert recovered.final_notice_attempted is True
    assert recovered.ready_check_started is True


@pytest.mark.parametrize(
    "corruption",
    [
        "version",
        "missing_version",
        "missing_parties",
        "missing_cooldowns",
        "unknown_root",
        "missing_record_field",
        "unknown_record_field",
        "duplicate_party",
        "invalid_phase",
        "string_id",
        "boolean_id",
        "nonpositive_id",
        "naive_deadline",
        "invalid_cooldown",
        "deadline_before_creation",
        "duplicate_roster",
        "ready_and_declined",
        "reserve_confirmed",
        "confirmed_and_pending",
    ],
)
def test_invalid_snapshot_never_becomes_an_empty_success(
    tmp_path: Path, snapshot: PartySnapshot, corruption: str
) -> None:
    data = snapshot.model_dump(mode="json")
    record = data["parties"][0]
    if corruption == "version":
        data["version"] = 2
    elif corruption.startswith("missing_") and corruption != "missing_record_field":
        del data[corruption.removeprefix("missing_")]
    elif corruption == "unknown_root":
        data["unexpected"] = True
    elif corruption == "missing_record_field":
        del record["final_notice_attempted"]
    elif corruption == "unknown_record_field":
        record["dm_messages"] = {}
    elif corruption == "duplicate_party":
        data["parties"].append(record.copy())
    elif corruption == "invalid_phase":
        record["phase"] = "unknown"
    elif corruption == "string_id":
        record["guild_id"] = "100"
    elif corruption == "boolean_id":
        record["guild_id"] = True
    elif corruption == "nonpositive_id":
        record["dm_message_ids"]["11"] = [1011, 0]
    elif corruption == "naive_deadline":
        record["deadline"] = "2026-10-05T14:00:00"
    elif corruption == "invalid_cooldown":
        data["cooldowns"]["11"] = "not-a-date"
    elif corruption == "deadline_before_creation":
        record["deadline"] = (NOW - timedelta(seconds=1)).isoformat()
    elif corruption == "duplicate_roster":
        record["joined_order"].append(11)
    elif corruption == "ready_and_declined":
        record["declined_order"].append(11)
    elif corruption == "reserve_confirmed":
        record["confirmed"].append(13)
    else:
        record["confirm_deadlines"]["11"] = NOW.isoformat()
    path = tmp_path / "party_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        PartyStateStore(path).load()


@pytest.mark.parametrize("corruption", ["truncated", "duplicate_root_key", "duplicate_record_key"])
def test_corrupt_or_ambiguous_json_is_rejected(
    tmp_path: Path, snapshot: PartySnapshot, corruption: str
) -> None:
    raw = snapshot.model_dump_json(indent=2)
    if corruption == "truncated":
        raw = raw[: len(raw) // 2]
    elif corruption == "duplicate_root_key":
        raw = raw.replace('"version": 1', '"version": 2, "version": 1')
    else:
        raw = raw.replace('"count": 2', '"count": 1, "count": 2')
    path = tmp_path / "party_state.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        PartyStateStore(path).load()


@pytest.mark.parametrize("failed_operation", ["fsync", "replace"])
async def test_failed_atomic_write_keeps_previous_snapshot(
    tmp_path: Path, snapshot: PartySnapshot, monkeypatch: pytest.MonkeyPatch, failed_operation: str
) -> None:
    store = PartyStateStore(tmp_path / "party_state.json")
    await store.save(snapshot)
    previous_bytes = store.path.read_bytes()
    replacement = PartySnapshot(version=1, parties=[], cooldowns={11: datetime.now(UTC)})

    def fail(*args: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(f"utils.party.state.os.{failed_operation}", fail)
    with pytest.raises(OSError, match="simulated disk failure"):
        await store.save(replacement)
    assert store.path.read_bytes() == previous_bytes
    assert PartyStateStore(store.path).load() == snapshot


async def test_cancellation_waits_for_atomic_writer_before_propagating(
    tmp_path: Path, snapshot: PartySnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PartyStateStore(tmp_path / "party_state.json")
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = store._write

    def blocked_write(value: PartySnapshot) -> None:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release writer")
        original_write(value)

    monkeypatch.setattr(store, "_write", blocked_write)
    job = asyncio.create_task(store.save(snapshot))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        job.cancel()
        await asyncio.sleep(0)
        assert not job.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert PartyStateStore(store.path).load() == snapshot
