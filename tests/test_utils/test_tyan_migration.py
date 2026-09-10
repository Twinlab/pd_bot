"""Безопасность согласуемой ручной миграции на изолированной SQLite."""

import sqlite3
from pathlib import Path

import pytest


def test_migration_is_repeatable_and_preserves_existing_data():
    sql = (Path(__file__).parents[2] / "ops/migrations/20260910_tyan.sql").read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE existing_data (value TEXT)")
        connection.execute("INSERT INTO existing_data VALUES ('keep')")
        connection.executescript(sql)
        connection.executescript(sql)
        assert connection.execute("SELECT value FROM existing_data").fetchone() == ("keep",)
        connection.execute(
            "INSERT INTO tyan_rolls (discord_user_id,date,kind,text) VALUES (1,?,?,?)",
            ("2026-09-10", "normal", "snapshot"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO tyan_rolls (discord_user_id,date,kind,text) VALUES (1,?,?,?)",
                ("2026-09-10", "none", "duplicate"),
            )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
