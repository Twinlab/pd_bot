"""Разовый аниме-постинг через вебхук без запуска Discord-бота."""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.anime_poster")
API = "https://danbooru.donmai.us/posts.json"
ARTIFACT_PREFIX = "anime-poster-state-"
MAX_STATE_BYTES = 2 * 1024**2


class _ApiError(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__(f"API вернул HTTP {status}")
        self.status = status


class _ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            if urllib.parse.urlsplit(newurl).scheme != "https":
                raise RuntimeError("Небезопасное перенаправление при скачивании журнала")
            if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
                redirected.remove_header("Authorization")
        return redirected


def request_json(
    url: str, *, headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None
) -> Any:
    """Выполняет ограниченный HTTP-запрос, не включая секретный URL в ошибки."""
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "PD-Room-Anime-Poster/1.0",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(8 * 1024**2 + 1)
        if len(raw) > 8 * 1024**2:
            raise RuntimeError("Слишком большой ответ API")
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise _ApiError(error.code) from None
    except (OSError, ValueError):
        raise RuntimeError("Сбой сети или некорректный ответ API") from None


def load_state(raw: bytes) -> dict[str, Any]:
    """Проверяет журнал; повреждение нельзя трактовать как пустую историю."""
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Журнал слишком большой")
    state = json.loads(raw)
    if not isinstance(state, dict) or set(state) != {"version", "posted_ids", "slots", "pending"}:
        raise ValueError("Неизвестный формат журнала")
    if type(state["version"]) is not int or state["version"] != 1:
        raise ValueError("Неизвестная версия журнала")
    ids = state["posted_ids"]
    slots = state["slots"]
    if not isinstance(ids, list) or any(type(v) is not int or v <= 0 for v in ids):
        raise ValueError("Некорректная история постов")
    if len(set(ids)) != len(ids):
        raise ValueError("Повторы в истории постов")
    if not isinstance(slots, list) or any(not isinstance(v, str) or not v for v in slots):
        raise ValueError("Некорректная история запусков")
    pending = state["pending"]
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {"slot", "post", "started_at"}:
            raise ValueError("Некорректная незавершённая отправка")
        if not isinstance(pending["slot"], str) or not pending["slot"]:
            raise ValueError("Отсутствует слот незавершённой отправки")
        post = pending["post"]
        if not isinstance(post, dict) or type(post.get("id")) is not int or post["id"] <= 0:
            raise ValueError("Отсутствует пост незавершённой отправки")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Атомарно сохраняет валидный журнал в рабочем каталоге задания."""
    raw = json.dumps(state, ensure_ascii=False, indent=2).encode()
    load_state(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def restore_state(seed: Path, *, initialize: bool = False) -> dict[str, Any]:
    """Восстанавливает новейший снимок Actions; потеря истории блокирует отправку."""
    repository = os.environ["GITHUB_REPOSITORY"]
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for page in range(1, 101):
        result = request_json(
            f"https://api.github.com/repos/{repository}/actions/artifacts?per_page=100&page={page}",
            headers=headers,
        )
        artifacts = result["artifacts"]
        candidates = [
            a
            for a in artifacts
            if a["name"].startswith(ARTIFACT_PREFIX)
            and a.get("workflow_run", {}).get("head_branch") == "main"
        ]
        if candidates:
            latest = max(candidates, key=lambda a: a["id"])
            if initialize:
                raise RuntimeError("История уже существует; повторная инициализация запрещена")
            if latest["expired"]:
                raise RuntimeError("Срок хранения журнала истёк; восстановите историю вручную")
            request = urllib.request.Request(latest["archive_download_url"], headers=headers)
            try:
                with urllib.request.build_opener(_ArtifactRedirect()).open(
                    request, timeout=30
                ) as response:
                    raw = response.read(MAX_STATE_BYTES + 1)
            except OSError:
                raise RuntimeError("Не удалось скачать журнал; отправка запрещена") from None
            if len(raw) > MAX_STATE_BYTES:
                raise RuntimeError("Архив журнала слишком большой")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if archive.namelist() != ["state.json"]:
                    raise ValueError("Неожиданное содержимое архива журнала")
                if archive.getinfo("state.json").file_size > MAX_STATE_BYTES:
                    raise ValueError("Журнал слишком большой")
                return load_state(archive.read("state.json"))
        if len(artifacts) < 100:
            if initialize:
                return load_state(seed.read_bytes())
            raise RuntimeError("Журнал не найден. Сначала выполните initialize-history")
    raise RuntimeError("Слишком много артефактов для безопасного поиска журнала")


def normalize_filters(rating: str, tag: str) -> tuple[str | None, str | None]:
    """Проверяет ручные параметры и запрещает подмену метатегов поиска."""
    rating = rating.strip().lower()
    tag = tag.strip()
    if rating not in {"", "auto", "g", "s", "q", "e"}:
        raise ValueError("Рейтинг должен быть auto, g, s, q или e")
    if tag and (
        len(tag) > 200
        or tag.startswith(("-", "~"))
        or any(char.isspace() or char in ":{}" for char in tag)
    ):
        raise ValueError(
            "Укажите один тег Danbooru без пробелов и метатегов, например genshin_impact"
        )
    return (None if rating in {"", "auto"} else rating), tag or None


def _fetch_posts(config: dict[str, Any], tags: str, page: int | None = None) -> Any:
    params = {"tags": tags, "limit": str(config["limit"])}
    if page is not None:
        params["page"] = str(page)
    login, key = os.getenv("DANBOORU_LOGIN"), os.getenv("DANBOORU_API_KEY")
    if login and key:
        params.update(login=login, api_key=key)
    return request_json(API + "?" + urllib.parse.urlencode(params))


def _select_tagged_post(
    config: dict[str, Any], seen: set[int], *, rating: str, tag: str
) -> dict[str, Any]:
    order, page = "order:random", 1
    for _ in range(5):
        tags = f"{tag} {order} rating:{rating} score:>={config['min_score']}"
        try:
            posts = _fetch_posts(config, tags, page if order == "order:id_desc" else None)
        except _ApiError as error:
            if error.status == 500 and order == "order:random":
                order = "order:id_desc"
            else:
                logger.warning("Поиск Danbooru не удался; следующая попытка")
            time.sleep(1)
            continue
        except RuntimeError:
            logger.warning("Поиск Danbooru не удался; следующая попытка")
            time.sleep(1)
            continue
        # Как в /post_anime: явный тег заменяет ограничения базового автоподбора.
        candidates = filter_posts(
            posts, config, seen, rating, require_girl=False, apply_excluded=False
        )
        if candidates:
            return random.choice(candidates)
        if order == "order:id_desc":
            if not posts:
                break
            page += 1
    raise RuntimeError("Не найдены новые картинки по выбранному тегу и рейтингу")


def select_post(
    config: dict[str, Any], seen: set[int], *, rating: str | None = None, tag: str | None = None
) -> dict[str, Any]:
    """Выбирает новый пост по конфигу или ручным параметрам одного запуска."""
    rating, tag = normalize_filters(rating or "auto", tag or "")
    if tag is not None:
        return _select_tagged_post(
            config, seen, rating=rating or random.choice(config["ratings"]), tag=tag
        )
    for extra in (True, False):
        for _ in range(5):
            chosen_rating = rating or random.choice(config["ratings"])
            franchise = None
            if extra and config["extra_tags"] and random.random() < config["extra_tag_chance"]:
                franchise = random.choice(config["extra_tags"])
            if franchise:
                tags = (
                    f"{franchise} order:random rating:{chosen_rating} score:>={config['min_score']}"
                )
            else:
                tags = f"{random.choice(config['base_tags'])} order:rank rating:{chosen_rating}"
            try:
                posts = _fetch_posts(config, tags)
            except RuntimeError:
                logger.warning("Поиск Danbooru не удался; следующая попытка")
                time.sleep(1)
                continue
            candidates = filter_posts(
                posts, config, seen, chosen_rating, require_girl=bool(franchise)
            )
            if candidates:
                return random.choice(candidates)
    raise RuntimeError("Не найдены новые картинки, соответствующие фильтрам")


def filter_posts(
    posts: Any,
    config: dict[str, Any],
    seen: set[int],
    rating: str,
    *,
    require_girl: bool,
    apply_excluded: bool = True,
) -> list[dict[str, Any]]:
    """Отбрасывает повторы, неподходящие рейтинги, теги и форматы изображений."""
    if not isinstance(posts, list):
        return []
    result = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = post.get("id")
        if type(post_id) is not int or post_id <= 0 or post_id in seen:
            continue
        if post.get("rating") != rating or post.get("file_ext", "").lower() not in {
            "jpg",
            "jpeg",
            "png",
            "gif",
            "webp",
        }:
            continue
        score = post.get("score")
        if type(score) is not int or score < config["min_score"]:
            continue
        tags = set(str(post.get("tag_string") or "").split())
        if apply_excluded and tags & set(config["excluded_tags"]):
            continue
        if require_girl and not tags & set(config["base_tags"]):
            continue
        url = post.get("file_url") or post.get("large_file_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        result.append(
            {
                "id": post_id,
                "url": url,
                "score": score,
                "rating": rating,
                "artists": str(post.get("tag_string_artist") or ""),
                "characters": str(post.get("tag_string_character") or ""),
            }
        )
    return result


def build_payload(post: dict[str, Any], color: int) -> dict[str, Any]:
    """Собирает карточку Components V2 без пингов пользователей и ролей."""
    title = ", ".join(v.replace("_", " ") for v in post["characters"].split())
    title = title.replace("[", "").replace("]", "")[:256]
    title = title or "Открыть на Danbooru"
    rating = {"g": "general", "s": "sensitive", "q": "questionable", "e": "explicit"}
    meta = f"-# score: {post['score']} · rating: {rating[post['rating']]}"
    if post["artists"]:
        artists = ", ".join(v.replace("_", " ") for v in post["artists"].split())[:1000]
        meta = f"**Художник:** {artists}\n{meta}"
    return {
        "flags": 32768,
        "allowed_mentions": {"parse": []},
        "components": [
            {
                "type": 17,
                "accent_color": color,
                "components": [
                    {
                        "type": 10,
                        "content": f"### [{title}](https://danbooru.donmai.us/posts/{post['id']})",
                    },
                    {"type": 12, "items": [{"media": {"url": post["url"]}}]},
                    {"type": 10, "content": meta},
                ],
            }
        ],
    }


def complete_pending(state: dict[str, Any]) -> None:
    """Фиксирует подтверждённую отправку и ограничивает размер истории."""
    pending = state["pending"]
    post_id = pending["post"]["id"]
    state["posted_ids"] = [v for v in state["posted_ids"] if v != post_id][-1999:] + [post_id]
    state["slots"] = list(dict.fromkeys([*state["slots"], pending["slot"]]))[-2000:]
    state["pending"] = None


def prepare(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    mode: str,
    slot: str,
    rating: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Резервирует отправку до HTTP-запроса; неопределённость требует ручной проверки."""
    if mode == "confirm-sent":
        if state["pending"] is None:
            raise RuntimeError("Нет незавершённой отправки для подтверждения")
        complete_pending(state)
        return state
    if mode == "confirm-not-sent":
        if state["pending"] is None:
            raise RuntimeError("Нет незавершённой отправки для отмены")
        state["pending"] = None
        return state
    if state["pending"] is not None:
        raise RuntimeError("Есть незавершённая отправка. Проверьте канал и подтвердите результат")
    if mode == "initialize-history" or slot in state["slots"]:
        return state
    post = select_post(config, set(state["posted_ids"]), rating=rating, tag=tag)
    logger.info(
        "Выбран Danbooru #%s, score=%s, rating=%s", post["id"], post["score"], post["rating"]
    )
    if mode == "preview":
        logger.info("Проверка без отправки: https://danbooru.donmai.us/posts/%s", post["id"])
        return state
    state["pending"] = {"slot": slot, "post": post, "started_at": datetime.now(UTC).isoformat()}
    return state


def send(state: dict[str, Any], config: dict[str, Any], webhook: str) -> dict[str, Any]:
    """Отправляет ровно один HTTP-запрос; после сетевой ошибки повторять автоматически нельзя."""
    if state["pending"] is None:
        logger.info("Отправка не требуется")
        return state
    if not re.fullmatch(r"https://discord\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+", webhook):
        raise ValueError("Некорректный адрес Discord-вебхука")
    response = request_json(
        webhook + "?wait=true&with_components=true",
        payload=build_payload(state["pending"]["post"], config["color"]),
    )
    if not isinstance(response, dict) or not str(response.get("id", "")).isdigit():
        raise RuntimeError("Discord не подтвердил ID сообщения; проверьте канал вручную")
    logger.info("Публикация подтверждена Discord, message_id=%s", response["id"])
    complete_pending(state)
    return state


def due_slot(state: dict[str, Any], config: dict[str, Any], now: datetime) -> str | None:
    """Возвращает первый пропущенный слот текущего UTC-дня; прошлые дни не догоняет."""
    if state["pending"] is not None:
        raise RuntimeError("Есть незавершённая отправка. Проверьте канал и подтвердите результат")
    if now.tzinfo is None:
        raise ValueError("Для проверки расписания требуется время с часовым поясом")
    now = now.astimezone(UTC)
    schedule = config["schedule"]
    for name in ("morning", "evening"):
        hour = schedule[f"{name}_hour"]
        minute = schedule[f"{name}_minute"]
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slot = f"scheduled:{now.date()}:{name}"
        legacy_slot = f"{now.date()}:{minute} {hour} * * *"
        if target <= now and slot not in state["slots"] and legacy_slot not in state["slots"]:
            return slot
    return None


def _workflow_outputs(*, persist: bool, send: bool) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"persist={str(persist).lower()}\nsend={str(send).lower()}\n")


def main() -> None:
    """Запускает подготовку или отправку отдельного задания GitHub Actions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "send", "local-preview"])
    parser.add_argument(
        "--mode",
        default="preview",
        choices=[
            "initialize-history",
            "preview",
            "publish",
            "scheduled",
            "confirm-sent",
            "confirm-not-sent",
        ],
    )
    parser.add_argument("--state", type=Path, default=Path(".anime-poster/state.json"))
    parser.add_argument("--rating", default=os.getenv("ANIME_RATING", "auto"))
    parser.add_argument("--tag", default=os.getenv("ANIME_TAG", ""))
    args = parser.parse_args()
    scheduled = args.mode == "scheduled" or bool(os.getenv("ANIME_SCHEDULE"))
    rating, tag = (None, None) if scheduled else normalize_filters(args.rating, args.tag)
    config = json.loads(Path("config/anime_poster.json").read_text(encoding="utf-8"))
    if args.phase == "local-preview":
        state = load_state(Path("ops/anime-poster-seed.json").read_bytes())
        prepare(state, config, mode="preview", slot="local-preview", rating=rating, tag=tag)
        return
    if args.phase == "prepare":
        state = restore_state(
            Path("ops/anime-poster-seed.json"), initialize=args.mode == "initialize-history"
        )
        before = json.dumps(state, sort_keys=True)
        if scheduled:
            slot = due_slot(state, config, datetime.now(UTC))
            if slot is None:
                logger.info("Плановая публикация сейчас не требуется; поиск и отправка пропущены")
                _workflow_outputs(persist=False, send=False)
                return
        else:
            slot = f"manual:{os.environ['GITHUB_RUN_ID']}"
        mode = "publish" if args.mode == "scheduled" else args.mode
        state = prepare(state, config, mode=mode, slot=slot, rating=rating, tag=tag)
        changed = before != json.dumps(state, sort_keys=True) or mode == "initialize-history"
        _workflow_outputs(persist=changed, send=mode == "publish" and state["pending"] is not None)
        if not changed:
            return
    else:
        state = load_state(args.state.read_bytes())
        state = send(state, config, os.environ["ANIME_WEBHOOK_URL"].strip())
    save_state(args.state, state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        main()
    except Exception as error:
        logger.error(
            "%s",
            str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__,
        )
        raise SystemExit(1) from None
