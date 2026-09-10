"""Проверки разового сброса /tyan на отдельной локальной SQLite-базе."""

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from ops.reset_tyan_day import reset_day


def test_reset_only_selected_day_keeps_other_data_and_verified_backup(tmp_path):
    database = tmp_path / "test.db"
    migration = Path(__file__).parents[2] / "ops/migrations/20260910_tyan.sql"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.executescript("CREATE TABLE unrelated (value TEXT); INSERT INTO unrelated VALUES ('keep');")
        for user_id, day in [(1, "2026-09-10"), (1, "2026-09-11"), (2, "2026-09-11"),
                             (1, "2026-09-12")]:
            conn.execute("INSERT INTO tyan_rolls (discord_user_id, date, kind, text) VALUES (?, ?, ?, ?)",
                         (user_id, day, "normal", "saved"))
        conn.commit()
    backup_dir = tmp_path / "backup"
    assert reset_day(database, date(2026, 9, 11), backup_dir) == 2
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT date FROM tyan_rolls ORDER BY date").fetchall() == [
            ("2026-09-10",), ("2026-09-12",),
        ]
        assert conn.execute("SELECT value FROM unrelated").fetchall() == [("keep",)]
    with closing(sqlite3.connect(backup_dir / "before.db")) as backup:
        assert backup.execute("SELECT COUNT(*) FROM tyan_rolls").fetchone() == (4,)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert json.loads((backup_dir / "reset-result.json").read_text())["deleted"] == 2
    with pytest.raises(FileExistsError):
        reset_day(database, date(2026, 9, 11), backup_dir)
