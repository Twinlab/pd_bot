#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

DB="${PD_BOT_DB_PATH:-/home/twinlab/pd_bot/data/bot_data.db}"
BACKUP_DIR="${PD_BOT_BACKUP_DIR:-/home/twinlab/pd_bot/backups/db}"
KEEP="${PD_BOT_BACKUP_KEEP:-14}"
ENV_FILE="${PD_BOT_BACKUP_ENV_FILE:-/home/twinlab/.pd_bot_backup.env}"
REQUIRE_UPLOAD="${PD_BOT_BACKUP_REQUIRE_UPLOAD:-1}"

if [[ -f "$ENV_FILE" ]]; then
    # Webhook хранится отдельно от репозитория и не должен попадать в логи.
    source "$ENV_FILE"
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
host="$(hostname)"
snapshot=""
restore_check=""

cleanup() {
    [[ -z "$snapshot" || ! -f "$snapshot" ]] || rm -f -- "$snapshot"
    [[ -z "$restore_check" || ! -f "$restore_check" ]] || rm -f -- "$restore_check"
}

notify_failure() {
    status=$?
    trap - ERR
    cleanup
    message="SQLite backup FAILED on $host at $timestamp (exit $status)"
    printf '%s\n' "$message" >&2
    if [[ -n "${DB_BACKUP_WEBHOOK_URL:-}" ]]; then
        curl -fsS -m 30 \
            --form-string "payload_json={\"content\":\"$message\"}" \
            "$DB_BACKUP_WEBHOOK_URL" >/dev/null || true
    fi
    exit "$status"
}

trap cleanup EXIT
trap notify_failure ERR

[[ -f "$DB" ]]
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]]
[[ "$REQUIRE_UPLOAD" == "0" || "$REQUIRE_UPLOAD" == "1" ]]
[[ "$DB" != *"'"* && "$BACKUP_DIR" != *"'"* ]]

mkdir -p "$BACKUP_DIR"
snapshot="$BACKUP_DIR/bot_data-$timestamp.db"
archive="$snapshot.gz"

sqlite3 "$DB" "PRAGMA busy_timeout=30000; VACUUM INTO '$snapshot';" >/dev/null

integrity="$(sqlite3 "$snapshot" "PRAGMA integrity_check;")"
[[ "$integrity" == "ok" ]]
[[ -z "$(sqlite3 "$snapshot" "PRAGMA foreign_key_check;")" ]]

gzip -f "$snapshot"
snapshot=""
gzip -t "$archive"

restore_check="$(mktemp "$BACKUP_DIR/.restore-check.XXXXXX.db")"
case "$restore_check" in
    "$BACKUP_DIR"/.restore-check.*.db) ;;
    *) exit 2 ;;
esac
gzip -dc "$archive" >"$restore_check"
restored_integrity="$(sqlite3 "$restore_check" "PRAGMA integrity_check;")"
[[ "$restored_integrity" == "ok" ]]
[[ -z "$(sqlite3 "$restore_check" "PRAGMA foreign_key_check;")" ]]
rm -f -- "$restore_check"
restore_check=""

size="$(du -h "$archive" | cut -f1)"
if [[ -n "${DB_BACKUP_WEBHOOK_URL:-}" ]]; then
    curl -fsS -m 120 \
        --form-string "payload_json={\"content\":\"Бэкап БД $host — $timestamp ($size), integrity ok\"}" \
        -F "file=@$archive" \
        "$DB_BACKUP_WEBHOOK_URL" >/dev/null
elif [[ "$REQUIRE_UPLOAD" == "1" ]]; then
    printf 'DB_BACKUP_WEBHOOK_URL is required for off-site backup\n' >&2
    exit 1
fi

mapfile -t backups < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'bot_data-*.db.gz' \
        -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
)
for ((index = KEEP; index < ${#backups[@]}; index++)); do
    candidate="${backups[$index]}"
    case "$candidate" in
        "$BACKUP_DIR"/bot_data-*.db.gz) rm -f -- "$candidate" ;;
        *) printf 'Refusing to remove unexpected path: %s\n' "$candidate" >&2; exit 2 ;;
    esac
done

printf '%s backup ok: %s (%s), restore integrity ok\n' \
    "$(date '+%F %T')" "$archive" "$size"
