"""Распознавание Steam, Dota и FACEIT для формы привязки аккаунтов."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import quote, unquote, urlsplit

import aiohttp

from config.settings import BotSettings
from utils.cs_api import FaceitNonRetryable, FaceitNotFound, FaceitRateLimited, faceit_get
from utils.dota_api import get_cached_response, save_to_cache
from utils.profile_accounts_data_manager import (
    AccountGame,
    AccountLinkError,
    ProfileAccountsDataManager,
)

STEAM_ID_BASE = 76561197960265728
MAX_ACCOUNT_ID = 2**32 - 1
_NICKNAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


@dataclass(frozen=True, slots=True)
class AccountInput:
    """Проверенный идентификатор из пользовательского ввода."""

    kind: Literal["steam", "vanity", "faceit"]
    value: str


@dataclass(frozen=True, slots=True)
class ResolvedAccount:
    """Аккаунт, который пользователь видит перед подтверждением привязки."""

    game: AccountGame
    identifier: str
    name: str
    url: str
    avatar: str | None = None


def _steam_id(value: str) -> str:
    if not value.isascii() or not value.isdecimal():
        raise AccountLinkError("ID должен содержать только цифры.")
    number = int(value)
    if 0 < number <= MAX_ACCOUNT_ID:
        return str(STEAM_ID_BASE + number)
    if STEAM_ID_BASE < number <= STEAM_ID_BASE + MAX_ACCOUNT_ID:
        return str(number)
    raise AccountLinkError("Не удалось распознать ID. Вставьте ссылку на профиль Steam.")


def parse_account_input(value: str, game: AccountGame) -> AccountInput:
    """Распознаёт разрешённые ссылки и ID, не обращаясь к произвольным сайтам."""
    value = value.strip().strip("<>")
    if not value or len(value) > 300:
        raise AccountLinkError("Вставьте ссылку на профиль или ID аккаунта.")
    if value.isascii() and value.isdecimal():
        if game == "cs" and len(value) < 17:
            return AccountInput("faceit", value)
        return AccountInput("steam", _steam_id(value))
    if "/" not in value and ":" not in value:
        if game == "cs" and _NICKNAME.fullmatch(value):
            return AccountInput("faceit", value)
        raise AccountLinkError(
            "Вставьте полную ссылку Steam или ID Dota 2. Логин Steam не подходит."
        )
    try:
        parsed = urlsplit(value if "://" in value else f"https://{value}")
        valid_origin = (
            parsed.scheme in {"http", "https"}
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 80, 443}
        )
    except ValueError as exc:
        raise AccountLinkError("Некорректная ссылка на профиль.") from exc
    if not valid_origin:
        raise AccountLinkError("Вставьте обычную ссылку на профиль Steam или FACEIT.")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if host == "steamcommunity.com" and len(parts) == 2:
        if parts[0] == "profiles":
            steam_id = _steam_id(parts[1])
            if steam_id != parts[1]:
                raise AccountLinkError("В ссылке /profiles/ должен быть полный Steam ID.")
            return AccountInput("steam", steam_id)
        if parts[0] == "id" and _NICKNAME.fullmatch(parts[1]):
            return AccountInput("vanity", parts[1])
    if host in {"dotabuff.com", "stratz.com", "opendota.com"}:
        if len(parts) >= 2 and parts[0] == "players":
            return AccountInput("steam", _steam_id(parts[1]))
    if host == "faceit.com":
        if len(parts) == 3 and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0]):
            parts = parts[1:]
        if len(parts) == 2 and parts[0] == "players" and _NICKNAME.fullmatch(parts[1]):
            return AccountInput("faceit", parts[1])
    raise AccountLinkError("Нужна ссылка на профиль Steam, FACEIT, Dotabuff, STRATZ или OpenDota.")


def _image_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("https://"):
        return value
    return None


class ProfileAccountService:
    """Разрешает ввод, кэширует публичные имена и сохраняет подтверждённые привязки."""

    def __init__(self, settings: BotSettings) -> None:
        self.settings = settings
        self.manager = ProfileAccountsDataManager()
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        """Закрывает HTTP-сессию при выгрузке профиля."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _steam_request(self, method: str, params: dict[str, str]) -> dict[str, Any]:
        key = self.settings.steam_api_key
        if not key:
            raise AccountLinkError(
                "Именные ссылки Steam пока недоступны. Укажите ID Dota 2 "
                "или ссылку Steam вида steamcommunity.com/profiles/7656…"
            )
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        try:
            async with self._session.get(
                f"https://api.steampowered.com/ISteamUser/{method}/",
                params={**params, "key": key},
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise AccountLinkError("Steam сейчас недоступен. Попробуйте привязать позже.")
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            # Исключения aiohttp могут содержать URL с API-ключом.
            raise AccountLinkError("Steam не ответил. Попробуйте ещё раз позже.") from None
        if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
            raise AccountLinkError("Steam вернул неполный ответ. Попробуйте позже.")
        return cast(dict[str, Any], data["response"])

    async def _faceit(self, params: dict[str, str]) -> dict[str, Any]:
        key = self.settings.faceit_api_key
        if not key:
            raise AccountLinkError(
                "Привязка FACEIT сейчас недоступна. Обратитесь к администратору."
            )
        try:
            data = await faceit_get(
                "/players",
                key,
                params=params,
                cache_key="profile_faceit:"
                + ":".join(f"{k}={v}" for k, v in sorted(params.items())),
                ttl=300,
            )
        except FaceitNotFound:
            raise AccountLinkError("Аккаунт FACEIT не найден. Проверьте ник или ссылку.") from None
        except FaceitRateLimited:
            raise AccountLinkError(
                "FACEIT просит подождать. Повторите попытку через минуту."
            ) from None
        except FaceitNonRetryable:
            raise AccountLinkError("FACEIT сейчас недоступен. Попробуйте позже.") from None
        if data is None:
            raise AccountLinkError("FACEIT не ответил. Попробуйте позже.")
        if not data.get("player_id") or not isinstance(data.get("nickname"), str):
            raise AccountLinkError("FACEIT вернул неполный профиль. Попробуйте позже.")
        if not isinstance(data.get("games"), dict) or not data["games"].get("cs2"):
            raise AccountLinkError("В этом профиле FACEIT не подключён Counter-Strike 2.")
        return data

    async def resolve(self, value: str, game: AccountGame) -> ResolvedAccount:
        """Находит аккаунт для предпросмотра, не создавая привязку."""
        try:
            async with asyncio.timeout(20):
                return await self._resolve(parse_account_input(value, game), game)
        except TimeoutError:
            raise AccountLinkError(
                "Проверка аккаунта заняла слишком много времени. Попробуйте позже."
            ) from None

    async def _resolve(self, parsed: AccountInput, game: AccountGame) -> ResolvedAccount:
        faceit: dict[str, Any] | None = None
        if parsed.kind == "faceit":
            faceit = await self._faceit({"nickname": parsed.value})
            steam_id = str(
                faceit.get("steam_id_64") or faceit["games"]["cs2"].get("game_player_id") or ""
            )
        elif parsed.kind == "vanity":
            response = await self._steam_request("ResolveVanityURL/v1", {"vanityurl": parsed.value})
            if response.get("success") != 1 or not response.get("steamid"):
                raise AccountLinkError("Профиль Steam не найден. Проверьте ссылку.")
            steam_id = _steam_id(str(response["steamid"]))
        else:
            steam_id = parsed.value

        if game == "cs":
            faceit = faceit or await self._faceit({"game": "cs2", "game_player_id": steam_id})
            return ResolvedAccount(
                game="cs",
                identifier=str(faceit["player_id"]),
                name=faceit["nickname"],
                url=f"https://www.faceit.com/en/players/{quote(faceit['nickname'], safe='')}",
                avatar=_image_url(faceit.get("avatar")),
            )

        steam_id = _steam_id(steam_id)
        player_id = int(steam_id) - STEAM_ID_BASE
        name = (
            str(faceit.get("steam_nickname") or faceit["nickname"]) if faceit else f"ID {player_id}"
        )
        avatar: str | None = None
        if self.settings.steam_api_key:
            response = await self._steam_request("GetPlayerSummaries/v2", {"steamids": steam_id})
            players = response.get("players")
            if not isinstance(players, list) or not players:
                raise AccountLinkError("Профиль Steam не найден. Проверьте ID.")
            player = next(
                (p for p in players if isinstance(p, dict) and str(p.get("steamid")) == steam_id),
                None,
            )
            if player is None:
                raise AccountLinkError("Steam не вернул запрошенный профиль. Попробуйте позже.")
            name = str(player.get("personaname") or name)
            avatar = _image_url(player.get("avatarfull"))
        if name != f"ID {player_id}":
            await save_to_cache(f"profile_dota_name:{player_id}", {"name": name}, ttl=86400 * 30)
        return ResolvedAccount(
            game="dota",
            identifier=str(player_id),
            name=name,
            url=f"https://steamcommunity.com/profiles/{steam_id}",
            avatar=avatar,
        )

    async def save(self, user_id: int, account: ResolvedAccount) -> None:
        """Сохраняет подтверждённый аккаунт с текущим лимитом привязок."""
        await self.manager.add_link(
            user_id,
            account.game,
            account.identifier,
            account.name,
            limit=self.settings.limits.links_max_per_user,
        )

    async def remove(self, user_id: int, account: ResolvedAccount) -> None:
        """Удаляет подтверждённую привязку пользователя."""
        await self.manager.remove_link(user_id, account.game, account.identifier)


async def cached_dota_names(player_ids: list[int]) -> dict[int, str]:
    """Читает сохранённые имена Dota без сетевых запросов при открытии профиля."""
    cached = await asyncio.gather(
        *(get_cached_response(f"profile_dota_name:{pid}") for pid in player_ids)
    )
    return {
        pid: data["name"]
        for pid, data in zip(player_ids, cached, strict=True)
        if data and isinstance(data.get("name"), str)
    }
