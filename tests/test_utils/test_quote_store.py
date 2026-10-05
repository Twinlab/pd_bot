"""Цитаты сохраняются атомарно, переживают рестарт и не обходят ограничения."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from utils.quotes.store import QuoteLimitError, QuoteRecord, QuoteStore, QuoteStoreError

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def record(message_id: int = 100, data: bytes = b"webp", **changes: object) -> QuoteRecord:
    values = {
        "message_id": message_id,
        "guild_id": 1,
        "channel_id": 2,
        "author_id": 3,
        "author_name": "author",
        "author_display_name": "Имя автора",
        "created_at": NOW - timedelta(days=1),
        "saved_by": 4,
        "saved_at": NOW,
        "size_bytes": len(data),
    }
    values.update(changes)
    return QuoteRecord(**values)


def store(tmp_path: Path, **limits: int) -> QuoteStore:
    return QuoteStore(tmp_path / "quotes", min_free_bytes=0, **limits)


async def test_empty_reads_do_not_create_storage(tmp_path: Path) -> None:
    service = store(tmp_path)
    assert await service.list_records() == []
    assert await service.get(100) is None
    assert await service.remove(100) is False
    with pytest.raises(QuoteStoreError, match="не найдена"):
        await service.read(100)
    assert not service.root.exists()


async def test_roundtrip_restart_and_filename_ignore_author_name(tmp_path: Path) -> None:
    service = store(tmp_path)
    quote = record(author_name="../../different-name", author_display_name="Новое имя")
    assert await service.save(quote, b"webp") is True
    restarted = store(tmp_path)
    assert await restarted.get(100) == quote
    assert await restarted.read(100) == b"webp"
    assert await restarted.list_records() == [quote]
    assert quote.filename == "100.webp"
    assert quote.jump_url == "https://discord.com/channels/1/2/100"
    assert {item.name for item in service.root.iterdir()} == {"100.webp", "index.json"}


async def test_duplicate_message_is_global_and_does_not_replace_first_card(tmp_path: Path) -> None:
    service = store(tmp_path)
    first = record()
    assert await service.save(first, b"webp") is True
    assert await service.save(record(data=b"other", author_id=33, channel_id=22), b"other") is False
    assert await service.read(100) == b"webp"
    assert await service.get(100) == first
    assert len(await service.list_records()) == 1


async def test_list_is_newest_first_with_stable_order_for_equal_timestamps(tmp_path: Path) -> None:
    service = store(tmp_path)
    for quote in [record(101), record(100), record(102, saved_at=NOW + timedelta(seconds=1))]:
        await service.save(quote, b"webp")
    assert [quote.message_id for quote in await service.list_records()] == [102, 101, 100]


async def test_parallel_duplicate_saves_commit_once(tmp_path: Path) -> None:
    service = store(tmp_path)
    results = await asyncio.gather(*(service.save(record(), b"webp") for _ in range(5)))
    assert results.count(True) == 1
    assert results.count(False) == 4
    assert len(await service.list_records()) == 1


async def test_parallel_saves_cannot_overrun_total_quota(tmp_path: Path) -> None:
    service = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    data = b"x" * 700
    results = await asyncio.gather(
        service.save(record(100, data), data),
        service.save(record(101, data), data),
        return_exceptions=True,
    )
    assert sum(result is True for result in results) == 1
    assert sum(isinstance(result, QuoteLimitError) for result in results) == 1
    assert sum(path.stat().st_size for path in service.root.iterdir()) <= 2000
    assert len(await service.list_records()) == 1


@pytest.mark.parametrize("data,size", [(b"too large", 9), (b"small", 4)])
async def test_card_bound_and_actual_size_checked_before_write(
    tmp_path: Path, data: bytes, size: int
) -> None:
    service = store(tmp_path, max_card_bytes=8)
    with pytest.raises(QuoteStoreError):
        await service.save(record(size_bytes=size), data)
    assert not service.root.exists()


async def test_low_disk_space_uses_nearest_existing_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def disk_usage(path: Path) -> SimpleNamespace:
        seen.append(path)
        return SimpleNamespace(free=4096)

    monkeypatch.setattr("utils.quotes.store.shutil.disk_usage", disk_usage)
    service = QuoteStore(tmp_path / "nested" / "quotes", min_free_bytes=4096)
    with pytest.raises(QuoteLimitError, match="свободного места"):
        await service.save(record(), b"webp")
    assert seen == [tmp_path]
    assert not service.root.exists()


async def test_orphans_temporary_and_nested_files_count_toward_quota(tmp_path: Path) -> None:
    service = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    await service.save(record(), b"webp")
    await service.remove(100)
    (service.root / "999.webp").write_bytes(b"orphan" * 100)
    (service.root / ".old.tmp").write_bytes(b"leftover" * 100)
    (service.root / "nested").mkdir()
    (service.root / "nested" / "extra.webp").write_bytes(b"extra" * 100)
    with pytest.raises(QuoteLimitError, match="заполнено"):
        await service.save(record(101), b"webp")
    assert await service.list_records() == []
    assert not (service.root / "101.webp").exists()


async def test_remove_frees_quota_and_survives_restart(tmp_path: Path) -> None:
    service = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    data = b"x" * 700
    await service.save(record(100, data), data)
    assert await service.remove(100) is True
    assert await service.remove(100) is False
    restarted = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    assert await restarted.get(100) is None
    assert not (service.root / "100.webp").exists()
    assert await restarted.save(record(101, data), data) is True


async def test_failed_index_write_keeps_old_index_and_retry_replaces_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    await service.save(record(), b"webp")
    await service.remove(100)
    previous = service.index_path.read_bytes()
    original = service._atomic_write
    data = b"x" * 700

    def fail_index(path: Path, payload: bytes) -> None:
        if path == service.index_path:
            raise OSError("disk full")
        original(path, payload)

    with monkeypatch.context() as local:
        local.setattr(service, "_atomic_write", fail_index)
        with pytest.raises(QuoteStoreError):
            await service.save(record(101, data), data)
    assert service.index_path.read_bytes() == previous
    assert await service.get(101) is None
    assert (service.root / "101.webp").read_bytes() == data
    restarted = store(tmp_path, max_total_bytes=2000, max_card_bytes=1024)
    replacement = b"y" * 800
    assert await restarted.save(record(101, replacement), replacement) is True
    assert await restarted.read(101) == replacement
    assert len(await restarted.list_records()) == 1


@pytest.mark.parametrize("failure", ["fsync", "replace"])
async def test_atomic_write_failure_does_not_replace_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    service = store(tmp_path)
    await service.save(record(), b"webp")
    previous = service.index_path.read_bytes()

    def fail(*args: object) -> None:
        raise OSError("simulated failure")

    with monkeypatch.context() as local:
        local.setattr(f"utils.quotes.store.os.{failure}", fail)
        with pytest.raises(QuoteStoreError):
            await service.save(record(101), b"webp")
    assert service.index_path.read_bytes() == previous
    assert await store(tmp_path).read(100) == b"webp"
    assert await service.get(101) is None
    assert not any(path.suffix == ".tmp" for path in service.root.iterdir())


async def test_failed_unlink_keeps_removed_record_out_of_index_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = store(tmp_path)
    await service.save(record(), b"webp")
    card_path = service.root / "100.webp"
    original_unlink = Path.unlink

    def fail_card(path: Path, *args: object, **kwargs: object) -> None:
        if path == card_path:
            raise PermissionError("busy")
        original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(Path, "unlink", fail_card)
        with pytest.raises(QuoteStoreError):
            await service.remove(100)
    restarted = store(tmp_path)
    assert await restarted.get(100) is None
    assert card_path.exists()
    assert await restarted.remove(100) is True
    assert not card_path.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated",
        "version",
        "bool_version",
        "missing_records",
        "unknown",
        "missing_field",
        "key_mismatch",
        "duplicate_root",
        "duplicate_record",
    ],
)
async def test_corrupt_index_fails_closed_for_every_operation(
    tmp_path: Path, corruption: str
) -> None:
    service = store(tmp_path)
    await service.save(record(), b"webp")
    data = json.loads(service.index_path.read_text(encoding="utf-8"))
    if corruption == "version":
        data["version"] = 2
    elif corruption == "bool_version":
        data["version"] = True
    elif corruption == "missing_records":
        del data["records"]
    elif corruption == "unknown":
        data["unknown"] = []
    elif corruption == "missing_field":
        del data["records"]["100"]["saved_by"]
    elif corruption == "key_mismatch":
        data["records"]["00100"] = data["records"].pop("100")
    raw = json.dumps(data)
    if corruption == "truncated":
        raw = raw[: len(raw) // 2]
    elif corruption == "duplicate_root":
        raw = raw.replace('"version": 1', '"version": 2, "version": 1')
    elif corruption == "duplicate_record":
        raw = raw.replace('"size_bytes": 4', '"size_bytes": 2, "size_bytes": 4')
    service.index_path.write_text(raw, encoding="utf-8")
    restarted = store(tmp_path)
    for operation in [
        restarted.list_records,
        lambda: restarted.get(100),
        lambda: restarted.read(100),
        lambda: restarted.remove(100),
        lambda: restarted.save(record(101), b"webp"),
    ]:
        with pytest.raises(QuoteStoreError, match="повреждён"):
            await operation()
        assert service.index_path.read_text(encoding="utf-8") == raw
        assert (service.root / "100.webp").read_bytes() == b"webp"
        assert not (service.root / "101.webp").exists()


async def test_missing_index_with_existing_cards_is_not_treated_as_empty(tmp_path: Path) -> None:
    service = store(tmp_path)
    await service.save(record(), b"webp")
    service.index_path.unlink()
    with pytest.raises(QuoteStoreError, match="отсутствует"):
        await store(tmp_path).save(record(101), b"webp")
    assert not service.index_path.exists()


@pytest.mark.parametrize("message_id", [0, -1, True, 1.0, "../../outside", 2**64])
async def test_message_id_cannot_be_used_as_a_path(tmp_path: Path, message_id: object) -> None:
    service = store(tmp_path)
    for method in [service.get, service.read, service.remove]:
        with pytest.raises(QuoteStoreError, match="ID"):
            await method(message_id)
    with pytest.raises(ValidationError):
        record(message_id)
    assert not service.root.exists()


@pytest.mark.parametrize("data", [b"short", b"x" * 33])
async def test_read_rejects_changed_or_oversized_card(tmp_path: Path, data: bytes) -> None:
    service = store(tmp_path, max_card_bytes=32)
    await service.save(record(), b"webp")
    (service.root / "100.webp").write_bytes(data)
    with pytest.raises(QuoteStoreError, match="повреждён"):
        await service.read(100)


async def test_index_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = store(tmp_path)
    service.root.mkdir()
    service.index_path.write_bytes(b" " * 101)
    monkeypatch.setattr("utils.quotes.store._MAX_INDEX_BYTES", 100)
    with pytest.raises(QuoteStoreError, match="повреждён"):
        await service.list_records()


async def test_repeated_cancellation_keeps_lock_until_card_and_index_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = store(tmp_path)
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = service._atomic_write

    def delayed(path: Path, data: bytes) -> None:
        if path.name == "100.webp":
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=5):
                raise TimeoutError("writer was not released")
        original(path, data)

    monkeypatch.setattr(service, "_atomic_write", delayed)
    first = asyncio.create_task(service.save(record(), b"webp"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        first.cancel()
        await asyncio.sleep(0)
        second = asyncio.create_task(service.save(record(), b"webp"))
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()
        assert not second.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second is False
    assert await store(tmp_path).read(100) == b"webp"
