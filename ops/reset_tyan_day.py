"""Разовый сброс /tyan за указанную дату с обязательной проверенной копией БД."""

import argparse
import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

logger = logging.getLogger("bot.ops.tyan_reset")


def reset_day(database: Path, day: date, backup_dir: Path) -> int:
    """Удаляет только выдачи указанного дня после проверенного SQLite-backup."""
    database = database.resolve(strict=True)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup_path = backup_dir / "before.db"
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=rw", uri=True, timeout=30)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Другой readonly-коннект делает backup, пока транзакция блокирует новые записи.
            with (
                closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as source,
                closing(sqlite3.connect(backup_path)) as backup,
            ):
                source.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Backup не прошёл integrity_check")
                if backup.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Backup не прошёл foreign_key_check")
            backup_path.chmod(0o600)
            sha256 = hashlib.sha256(backup_path.read_bytes()).hexdigest()
            cursor = conn.execute('DELETE FROM "tyan_rolls" WHERE "date" = ?', (day.isoformat(),))
            deleted = cursor.rowcount
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("База не прошла integrity_check после сброса")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    manifest = {"date": day.isoformat(), "deleted": deleted, "backup_sha256": sha256}
    manifest_path = backup_dir / "reset-result.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    logger.info("Сброс /tyan за %s: %s выдач; backup: %s", day, deleted, backup_path)
    return deleted


def main() -> None:
    """Применяет явно указанный сброс и сохраняет отдельную копию перед изменением."""
    parser = argparse.ArgumentParser(description="Разовый сброс дневных /tyan с backup")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    reset_day(args.database, args.date, args.backup_dir)


if __name__ == "__main__":
    main()
