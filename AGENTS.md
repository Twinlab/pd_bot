# PD Bot — AGENTS.md

Multifunctional Discord bot built with Python 3.13+ and `discord.py`. Features Dota 2 stats (Stratz GraphQL), music player (Lavalink v4 + wavelink 3.x), activity tracking, anime art posting, Twitch notifications, role reactions, top-reactions leaderboard and fun commands. **Single-guild design** — never iterate over `bot.guilds`.

## Tech Stack

- **Runtime**: Python 3.13+
- **Framework**: `discord.py[voice] >= 2.7` (with the `davey` E2EE library for the new Voice Gateway)
- **Config**: Pydantic v2 + `pydantic-settings` (`.env` + `config/bot_settings.yaml`)
- **DB**: SQLite via Tortoise ORM; миграции схемы делаются вручную при изменении моделей
- **Audio**: Lavalink v4 (separate JVM container) + `wavelink 3.x` Python client; plugins `youtube-source 1.18.x` (OAuth + multi-client bot-detection bypass) and `LavaSrc 4.x` (Spotify/Apple Music/Deezer/Yandex)
- **Lint/Format**: Ruff (line-length 100, double quotes)
- **Type-check**: mypy (strict-ish; see `pyproject.toml` overrides)
- **Tests**: pytest + pytest-asyncio (`asyncio_mode = "auto"`) + freezegun
- **Deployment**: CI → GHCR → ручное обновление закреплённого Docker image digest на отдельной VPS. Watchtower в текущем production отключён (см. ниже).

## Environment Setup

**Deployment topology (проверено 31.10.2026).** После переезда 29.10.2026 production работает на VPS HOSTKEY в Германии: `82.21.117.94`, SSH-пользователь `twinlab`, каталог `/home/twinlab/pd_bot`, контейнер `pd_bot`, Compose-сервис `bot`. Локальная машина разработчика используется только для тестов, линта, тайпчека и code-review.

CI после push/merge в `main` проверяет код и публикует образ в GHCR, но **не обновляет текущую VPS автоматически**. Production использует `docker-compose.yml` вместе с `compose.restore.yaml`; в override закреплён `ghcr.io/twinlab/pd_bot@sha256:...`, для бота установлено `com.centurylinklabs.watchtower.enable: "false"`, а Watchtower вынесен в профиль `auto-update-disabled`. Не включать автообновление и не заменять override обычным Compose-файлом без отдельного согласования.

### Production access and release verification

- Старый локальный SSH-алиас `discord` всё ещё указывает на прежнюю VM `62.84.121.113`. **Не использовать его для проверки или обновления текущего production.** Старые инструкции и memory skills с `ssh discord` относятся к прежней VM.
- Проверенный способ подключения из Windows (ключ не читать и не выводить):

  ```powershell
  ssh -F NUL -i C:/Users/twinl/.ssh/discord -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 twinlab@82.21.117.94
  ```

- Docker-команды на VPS выполнять через `sudo -n`. Перед релизом проверить точный SHA в label `org.opencontainers.image.revision` скачанного образа и текущего контейнера; сохранить текущий digest для отката.
- После успешного CI и разрешения на обновление: скачать образ нужного SHA, сделать резервную копию конфигурации и данных, изменить только digest сервиса `bot` в `compose.restore.yaml`, затем пересоздать только `bot` через оба Compose-файла и `up -d --no-deps bot`. При ошибке вернуть прежний override и образ. Сайт, Lavalink и yt-cipher не перезапускать без необходимости.
- Полный backup создаёт `/usr/local/lib/pdroom/full_backup.py`; локальная синхронизация — `D:\PD-Room-Backups\Sync-PDRoomBackup.ps1`, результат — `D:\PD-Room-Backups\last-sync.json`. Архивы содержат секреты: не выводить и не коммитить их содержимое. `ops/backup_db.sh` сохраняет только SQLite и не заменяет полный backup.
- После обновления проверить совпадение runtime SHA, `State.Status`, `RestartCount`, `OOMKilled` и ограниченное окно `docker logs` с сообщением «готов к работе» и отсутствием startup ERROR/CRITICAL/traceback. Для затронутой функции выполнить проверку без нежелательных публикаций. Успешный CI или push образа сами по себе не доказывают обновление бота.

Поэтому:
- **Не нужно** делать `python main.py` локально (нет прод-токенов, нет Lavalink-сервиса, нет голосовых соединений с Discord).
- **Не нужно** реинсталлить зависимости после каждого изменения `pyproject.toml` — они подтянутся в следующем Docker build. Локальный `.venv` обновляется только когда нужно прогнать mypy/pytest на новых API.
- **Не нужно** запускать `docker compose up` локально, если только не воспроизводишь конкретный баг в контейнере.

Локальный `.venv/` существует только для линта/тестов:

```bash
.venv/bin/pip install -e ".[dev]"      # один раз при клоне / при обновлении dev-deps
.venv/bin/pytest tests/...             # тесты
.venv/bin/ruff check .                 # линт
.venv/bin/mypy .                       # тайпчек
```

## Commands

### File-scoped (preferred — fast feedback)

```bash
.venv/bin/pytest tests/test_utils/test_dota_utils.py
.venv/bin/pytest tests/test_cogs/test_music_cog.py::TestClassName::test_method -v
.venv/bin/ruff check cogs/music.py
.venv/bin/ruff format cogs/music.py
.venv/bin/mypy utils/dota_api.py
```

### Full suite (only on explicit request or before commit)

```bash
.venv/bin/pytest                      # all tests
.venv/bin/pytest --cov                # with coverage
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/mypy .
docker compose up -d --build          # local Docker run
```

Pre-commit (`.pre-commit-config.yaml`) auto-runs `ruff --fix` and `ruff format`.

## Project Structure

- `main.py` — entry point: logging → config → Tortoise init → cog auto-discovery → bot start
- `cogs/` — auto-loaded discord.py extensions; **every file must expose `async def setup(bot)`**
- `handlers/` — non-cog extensions: `events.py` (on_ready, presence, voice), `message_handler.py`
- `config/` — `bot_settings.yaml` + `settings.py` (Pydantic models). Access via `bot.settings` or `get_settings()`
- `utils/` — shared logic; `*_data_manager.py` files own CRUD per module
 - `utils/music/` — modular wavelink wrapper (`player.py` with `MusicPlayer` subclass + `setup_node`, `ui.py`, `embeds.py`, `config.py`)
 - `lavalink/` — Lavalink server config (`application.yml`) and plugin volume mount-point; the JVM container is defined in `docker-compose.yml`
 - `utils/activity/` — activity tracking (views.py, reports.py, helpers.py)
  - `utils/dota_api.py` + `dota_match_utils.py` + `dota_utils.py` — Stratz GraphQL with in-memory + disk cache
  - `utils/models.py` — Tortoise ORM models; `utils/schemas.py` — Pydantic DTOs; `utils/database.py` — DB init
  - `utils/error_handler.py` — `@command_error_handler`, `safe_send()`, `safe_send_error()`
- `tests/` — mirrors source layout (`test_cogs/`, `test_utils/`, `test_handlers/`)
- `docs/` — MkDocs Material site (`architecture.md`, `commands.md`, `style-guide.md`, `deployment.md`)
- `assets/`, `downloads/`, `logs/`, `data/` — runtime artifacts (mostly gitignored)

## Code Style & Conventions

- **Language**: identifiers in English; **comments, docstrings, user-facing strings in Russian**
- **Type hints**: required on all public functions/methods. Modern syntax: `str | None`, `list[int]`, `dict[str, Any]` — never `Optional`/`List`/`Dict`/`Union`
- **Docstrings**: Google style, Russian text
- **Commands**: prefer `@commands.hybrid_command()` for new commands
- **Decorators**: wrap every command with `@command_error_handler` from `utils/error_handler.py`
- **Replies**: use `safe_send()` / `safe_send_error()` — never raw `ctx.send` for user-visible errors
- **Logging**: hierarchical `logging.getLogger("bot.<subsystem>")` (e.g. `bot.music`, `bot.dota`, `bot.cogs.activity`). For `utils/music/*` import the shared logger from `utils/music/config.py`. **Never use `print()`**
- **Wavelink usage**: stick to wavelink 3.x conventions — `await wavelink.Playable.search(query)` for resolution, `wavelink.Pool.connect(...)` for nodes, event listeners via `@commands.Cog.listener()` (`on_wavelink_track_start`, `on_wavelink_inactive_player`, etc.). Use our `MusicPlayer` subclass (`utils/music/player.py`) instead of bare `wavelink.Player` so the now-playing message and requester attribution work consistently.
- **Single guild**: do not write multi-guild logic, do not iterate `bot.guilds`
- **Imports**: stdlib → third-party → local, separated by blank lines (Ruff/isort enforced)
- **Комментарии**: пиши только то, что объясняет *почему* (нетривиальное намерение, гонка, обход бага, важный инвариант). Не дублируй то, что и так видно из кода или имени функции/переменной.
 - Запрещено: «# Импортируем X», «# Получаем Y», «# Возвращаем результат», «# Проверяем что X не None», «# Создаём экземпляр», «# Логируем», «# TODO без контекста», построчные «what»-комментарии над очевидными выражениями.
 - Запрещено вставлять «отчётные» комментарии вида «// Added missing check», «# Исправлено», «# Refactored to use safe_send» — историю правок несёт git, а не код.
 - Запрещено заменять docstring цепочкой однострочных комментариев: для публичных функций — Google-style docstring, для непубличных и внутри тел функций — минимум, объясняющий замысел.
 - Старые подробные комментарии, которые ты переписываешь, лучше укоротить до одной фразы или удалить, а не «дополнить» новыми абзацами.

## Testing

- Frameworks: `pytest`, `pytest-asyncio` (auto mode), `pytest-cov`, `freezegun`
- Mock discord.py objects with `MagicMock` / `AsyncMock`
- Test files mirror source: `cogs/foo.py` ↔ `tests/test_cogs/test_foo_cog.py`, `utils/foo.py` ↔ `tests/test_utils/test_foo.py`
- Add tests for every new public function, command and data manager method
- Ruff and mypy must pass; CI (`.github/workflows/deploy.yml`) runs `ruff check`, `ruff format --check`, and `pytest` on every PR

## Good Patterns / What to Mirror

- Cog skeleton: `cogs/music.py`, `cogs/role_reaction.py` (hybrid commands, error decorator, `setup(bot)`)
- Data manager pattern: `utils/role_reaction_data_manager.py`, `utils/top_reactions_data_manager.py` (Tortoise queries isolated from cogs)
- Modular subsystem: `utils/music/` (split player/ui/embeds/integration)
- Pydantic config: `config/settings.py` (validates `.env` + YAML in one model)
- Error handling: `utils/error_handler.py` (`command_error_handler`, `ERROR_MESSAGES` mapping)

## Avoid

- `print()` instead of logging
- Raw `discord.py` exception handling inside commands — let `@command_error_handler` do it
- Multi-guild logic (`for guild in bot.guilds`, cross-guild membership checks)
- Hardcoded channel/role/user IDs in code — put them in `config/bot_settings.yaml`
- Adding `Optional[X]` / `List[X]` / `Dict[K,V]` / `Union[A,B]` — use modern syntax
- Editing files under `data/`, `downloads/`, `logs/`, `.venv/`, `site/`, `*_cache/` — runtime/build artifacts

## Permissions

### Allowed without asking

- Read any file (except `.env`)
- Run linters, formatters, type-checkers, single-file tests
- Edit code and add tests
- Update relevant docs in `docs/` when changing behaviour

### Require explicit approval

- Adding/removing dependencies in `pyproject.toml`
- `git push`, `git commit` (only on explicit user request)
- `git commit --amend`, force push, history rewrites
- Deleting files or directories
- Editing `.env`, `.env.example` secret values, anything under `.github/workflows/`
- `docker compose up/down`, manual deploy actions
- Изменение DB schema (`utils/models.py`) без согласованного плана ручной миграции прод-БД

## Git & PR Conventions

- Push/merge в `main` запускает CI и публикацию образа; текущая VPS обновляется отдельно с закреплением digest (см. Production access and release verification).
- Before committing: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest`
- Keep diffs small and focused on a single concern
- Commit messages: short imperative summary
- Update affected docs (`README.md`, `docs/architecture.md`, `docs/commands.md`, `docs/style-guide.md`) in the same PR

### Commit attribution (strict)

All commits in this repository belong to the repo owner. AI assistants must
not leave any trace of themselves in commit metadata or messages:

- **Never** add `Co-Authored-By:` trailers (Cursor, Claude, Anthropic, Copilot, anyone).
- **Never** add `Generated-by:` / `Assisted-by:` / `Signed-off-by:` for AI tools.
- **Never** put phrases like "Generated with Cursor", "Made with Claude", "AI-assisted" into commit messages, PR titles or PR bodies.
- **Never** change `git config user.name` / `user.email` to AI bot identities.
- **Never** push under a Cursor cloud agent / background agent identity. If you are running as such an agent, stop and ask the user to commit locally instead.
- The local `git config` already points to the repo owner. Don't override it via `-c user.name=...` / `-c user.email=...` flags either.

If you are unsure whether a `git` action will leak attribution, don't run it — show the diff and ask the user to commit manually.

## Secrets

- Real secrets live only in `.env` (gitignored) and the production server's environment
- `.env.example` documents the required keys: `BOT_TOKEN`, `STRATZ_API_KEY`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `BOT_PREFIX`, `BOT_ENVIRONMENT`, `PROXY_URL`, `REPO_USER`, `REPO_PASS`, `LAVALINK_HOST`, `LAVALINK_PORT`, `LAVALINK_SERVER_PASSWORD`, `YOUTUBE_REFRESH_TOKEN`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`
- Lavalink-секреты:
    - `LAVALINK_SERVER_PASSWORD` — случайная строка; пароль для подключения бота к ноде (`openssl rand -hex 32`)
    - `YOUTUBE_REFRESH_TOKEN` — OAuth refresh token от **burner-аккаунта Google** (не основной!); получается через device-flow при первом запуске Lavalink (см. `docs/deployment.md`)
    - `SPOTIFY_CLIENT_ID/SECRET` — опционально, для распознавания Spotify-ссылок (заводится на https://developer.spotify.com/dashboard)
- **Never** commit `.env`, hardcode tokens, or print secret values in logs

## When stuck

Ask a clarifying question instead of guessing. For schema, deployment, or dependency changes, propose a plan first and wait for confirmation.
