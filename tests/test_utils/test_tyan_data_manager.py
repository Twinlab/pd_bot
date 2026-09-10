"""Проверки ORM на ручной миграции и атомарности дневных выдач."""

import asyncio
import random
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from utils.models import TyanRoll
from utils.tyan.catalog import load_catalog
from utils.tyan.config import TyanConfig
from utils.tyan_data_manager import TyanDataManager

NOW = datetime(2026, 9, 10, 20, 59, tzinfo=UTC)
NORMAL = TyanConfig(mother_chance=0, none_chance=0, part_weights=(0, 0, 1))
CATALOG = load_catalog()


@pytest.fixture
async def tyan_db(tmp_path):
    url = f"sqlite://{tmp_path / 'tyan.sqlite3'}"
    await Tortoise.init(
        db_url=url, modules={"models": ["utils.models"]}, use_tz=False
    )
    sql = (Path(__file__).parents[2] / "ops/migrations/20260910_tyan.sql").read_text(
        encoding="utf-8"
    )
    await Tortoise.get_connection("default").execute_script(sql)
    yield url
    await Tortoise.close_connections()


async def get_roll(user_id=1, *, config=NORMAL, now=NOW, **kwargs):
    return await TyanDataManager().get_daily_roll(
        CATALOG, config, user_id=user_id, now=now, rng=random.Random(42), **kwargs
    )


@pytest.mark.parametrize("kind", ["normal", "mother", "none"])
async def test_daily_snapshot_survives_database_reconnect(tyan_db, kind):
    config = TyanConfig(
        mother_chance=1 if kind == "mother" else 0,
        none_chance=1 if kind == "none" else 0,
    )
    first = await get_roll(config=config, member_ids=[1, 2])
    assert first.kind == kind
    await Tortoise.close_connections()
    await Tortoise.init(
        db_url=tyan_db, modules={"models": ["utils.models"]}, use_tz=False
    )
    with patch("utils.tyan_data_manager.generate_roll", side_effect=AssertionError("reroll")):
        second = await get_roll(config=NORMAL, now=NOW + timedelta(seconds=30))
    assert second == first
    assert second.created_at.tzinfo is UTC
    assert await TyanRoll.all().count() == 1


async def test_same_user_concurrent_calls_save_one_snapshot(tyan_db):
    rolls = await asyncio.gather(*(get_roll() for _ in range(15)))
    assert len(set(rolls)) == 1
    assert await TyanRoll.all().count() == 1


@pytest.mark.parametrize("kind", ["mother", "none"])
async def test_concurrent_users_share_event_cooldown(tyan_db, kind):
    config = TyanConfig(
        mother_chance=1 if kind == "mother" else 0,
        none_chance=1 if kind == "none" else 0,
    )
    rolls = await asyncio.gather(*(
        get_roll(user_id, config=config, member_ids=list(range(1, 16)))
        for user_id in range(1, 16)
    ))
    assert sum(roll.kind == kind for roll in rolls) == 1
    assert sum(roll.kind == "normal" for roll in rolls) == 14
    assert len({roll.archetype_id for roll in rolls if roll.kind == "normal"}) == 14
    assert await TyanRoll.all().count() == 15


async def test_new_moscow_day_uses_persisted_history(tyan_db):
    first = await get_roll()
    second = await get_roll(now=NOW + timedelta(minutes=2))
    assert first.day.isoformat() == "2026-09-10"
    assert second.day.isoformat() == "2026-09-11"
    assert first.adjective_id != second.adjective_id
    assert first.archetype_id != second.archetype_id
    assert first.trait_id != second.trait_id
    assert await TyanRoll.all().count() == 2


async def test_input_timezone_is_stored_as_utc_and_restored(tyan_db):
    now = NOW.astimezone(timezone(timedelta(hours=7)))
    first = await get_roll(now=now)
    row = await TyanRoll.get(discord_user_id=1)
    assert row.created_at == NOW.replace(tzinfo=None)
    assert first.created_at == NOW
    assert await get_roll() == first


async def test_naive_clock_does_not_write_or_poison_transaction(tyan_db):
    with pytest.raises(ValueError, match="поясом"):
        await get_roll(now=NOW.replace(tzinfo=None))
    assert await TyanRoll.all().count() == 0
    assert (await get_roll()).kind == "normal"


async def test_failed_write_does_not_consume_event(tyan_db):
    config = TyanConfig(mother_chance=0, none_chance=1)
    with patch.object(TyanRoll, "create", side_effect=OperationalError("write failed")):
        with pytest.raises(OperationalError, match="write failed"):
            await get_roll(config=config)
    assert await TyanRoll.all().count() == 0
    assert (await get_roll(config=config)).kind == "none"


async def test_event_cooldown_uses_elapsed_time_across_restart(tyan_db):
    config = TyanConfig(mother_chance=0, none_chance=1)
    first = await get_roll(config=config)
    await Tortoise.close_connections()
    await Tortoise.init(
        db_url=tyan_db, modules={"models": ["utils.models"]}, use_tz=False
    )
    early = await get_roll(2, config=config, now=NOW + timedelta(days=14, seconds=-1))
    ready = await get_roll(3, config=config, now=NOW + timedelta(days=14))
    assert first.kind == ready.kind == "none"
    assert early.kind == "normal"


async def test_history_covers_configured_long_event_cooldown(tyan_db):
    config = TyanConfig(
        mother_chance=0, none_chance=1, event_cooldown_days=365,
        adjective_cooldown_days=1, archetype_cooldown_days=1,
        trait_cooldown_days=1, pair_cooldown_days=1,
    )
    await get_roll(config=config, now=NOW - timedelta(days=360))
    assert (await get_roll(2, config=config)).kind == "normal"


async def test_startup_schema_generation_keeps_manual_indexes_and_data(tyan_db):
    first = await get_roll()
    connection = Tortoise.get_connection("default")
    before = await connection.execute_query_dict("PRAGMA index_list('tyan_rolls')")
    await Tortoise.generate_schemas()
    after = await connection.execute_query_dict("PRAGMA index_list('tyan_rolls')")
    assert before == after
    assert await get_roll() == first
    assert await connection.execute_query_dict("PRAGMA integrity_check") == [
        {"integrity_check": "ok"}
    ]
