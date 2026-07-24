# Деплой

## TL;DR — что произойдёт при мердже в `main`

> ⚠️ **Важно: одного мерджа в `main` недостаточно при структурных изменениях.** Watchtower на VM обновляет только `image` существующих контейнеров — он **не** пуллит `docker-compose.yml` из git, **не** добавляет новые сервисы и **не** создаёт новые env-переменные. Если в PR появился новый сервис, env или volume — после мерджа нужно зайти на VM и выполнить `git pull && docker compose up -d` руками.

Что произойдёт автоматически:

1. CI прогонит Ruff и pytest, соберёт новый `ghcr.io/twinlab/pd_bot:latest` и запушит в GHCR.
2. Watchtower на VM через ≤60 секунд увидит новый image, остановит старый контейнер `pd_bot`, поднимет новый из того же `image`, с теми же volume/env/network что были на VM **до** этого момента.
3. Новый бот загрузится и фоном подключится к существующему сервису `lavalink:2333`.
4. При временной недоступности Lavalink остальные подсистемы продолжат работать, а музыкальные команды будут возвращать контролируемую ошибку до восстановления ноды.

---

## Архитектура CI/CD

```mermaid
graph LR
    A[Push в main] --> B[GitHub Actions: Ruff и pytest]
    B --> C[Сборка Docker-образа pd_bot]
    C --> D[Push в ghcr.io/twinlab/pd_bot:latest]
    D --> E[Watchtower на VM polls каждые 60s]
    E --> F[Обновление контейнера pd_bot]

    subgraph "только image"
        F
    end

    subgraph "вручную при изменении схемы"
        G[git pull на VM]
        H[Правка .env]
        I[docker compose up -d]
    end

    G -.-> I
    H -.-> I
```

GitHub Actions конфигурация: `.github/workflows/deploy.yml`. На VM достаточно одного `docker compose up -d`, чтобы запустить связку `bot + lavalink + yt-cipher + watchtower`. Watchtower автоматически обновляет бот с тегом `:latest` и `yt-cipher:master`; остальные инфраструктурные образы закреплены по версии и digest.

### Что Watchtower умеет и **не** умеет

| Умеет | Не умеет |
|-------|----------|
| Подтягивать новые `:latest` image-ы из GHCR | Подтягивать новый `docker-compose.yml` из git |
| Перезапускать контейнеры с label `com.centurylinklabs.watchtower.enable=true` | Создавать **новые** сервисы, появившиеся в compose-файле |
| Удалять старые image-ы (`--cleanup`) | Менять `env_file`, `environment`, `volumes`, `depends_on`, `networks` существующего сервиса |
| Авторизоваться в GHCR через `REPO_USER`/`REPO_PASS` | Читать ваши новые секреты из репозитория |

Поэтому любое **структурное** изменение docker-compose (новый сервис, новые env, новые volume) требует ручного шага на VM.

Отдельная gotcha: `lavalink/application.yml` — это volume-mount, поэтому после правок нужен `docker compose restart lavalink` руками (Watchtower не среагирует — образ не меняется).

### Обновление инфраструктуры и музыкальных плагинов

Python, Lavalink и Watchtower закреплены по версии и OCI digest. Плагины `youtube-source`
и LavaSrc закреплены Maven-координатами в `lavalink/application.yml`. Они тоже требуют
регулярного обновления, но обновляются отдельным PR вместе с проверкой совместимости
конфига, версии Lavalink и воспроизведения.

`yt-cipher` — исключение: сервис отслеживает частые изменения `player.js`, поэтому
использует `master` и автоматически обновляется Watchtower.

Для закреплённых компонентов:

1. Выбрать совместимую версию и прочитать release notes.
2. Проверить manifest командой `docker buildx imagetools inspect <image>`.
3. Обновить тег и digest в `Dockerfile` или `docker-compose.yml`.
4. Прогнать тесты и Docker build.
5. После мерджа выполнить на VM `git pull && docker compose up -d`.

`LAVALINK_SERVER_PASSWORD` обязателен. Compose завершит проверку конфигурации ошибкой, если переменная отсутствует; известного fallback-пароля нет.

---

## Сервис `yt-cipher`

Stateless-сервис [kikkia/yt-cipher](https://github.com/kikkia/yt-cipher) — выносит signature-decoding (`/s/player/<hash>/...`) из плагина `youtube-source` в отдельный контейнер, потому что YouTube часто меняет обфускацию player.js и плагин за ней не успевает. Подключение — `plugins.youtube.remoteCipher` в `lavalink/application.yml`.
