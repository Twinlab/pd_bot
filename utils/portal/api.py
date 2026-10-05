"""Ограниченный API поверх живого бота и его существующих сервисов."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

import discord
from aiohttp import web
from discord.ext import commands

from config.settings import PortalApiConfig
from utils.profile.builder import ProfilePeriod, ProfileStatsBuilder
from utils.quotes.service import (
    QuotePermissionError,
    QuoteService,
    QuoteSourceUnavailableError,
)
from utils.quotes.store import QuoteRecord, QuoteStoreError

logger = logging.getLogger("bot.portal")
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_MAX_ID = 2**64 - 1
_MAX_IMAGE_BYTES = 8 * 1024**2
_ACTOR = "portal_actor"
_MEMBER = "portal_member"
_GUILD = "portal_guild"


class PortalError(Exception):
    """Ошибка со стабильным кодом, без внутренних подробностей."""

    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


class _QuotesCog(Protocol):
    @property
    def quotes(self) -> QuoteService: ...


def load_portal_token(config: PortalApiConfig) -> str:
    """Читает один секрет из окружения настроек или ограниченного файла."""
    if (config.token is None) == (config.token_file is None):
        raise ValueError("Для Portal API нужен ровно один источник служебного токена.")
    if config.token is not None:
        token = config.token.get_secret_value()
    else:
        assert config.token_file is not None
        try:
            with config.token_file.open("rb") as stream:
                raw = stream.read(1025)
            if len(raw) > 1024:
                raise ValueError
            token = raw.decode("ascii").strip()
        except (OSError, UnicodeError, ValueError):
            raise ValueError("Не удалось прочитать служебный токен Portal API.") from None
    if not 32 <= len(token) <= 512 or any(not 32 < ord(c) < 127 for c in token):
        raise ValueError(
            "Служебный токен Portal API должен содержать 32–512 печатных ASCII без пробелов."
        )
    return token


def _identifier(raw: str) -> int:
    if not _ID.fullmatch(raw) or int(raw) > _MAX_ID:
        raise PortalError(400, "invalid_request")
    return int(raw)


def _number(raw: str, minimum: int, maximum: int) -> int:
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 8:
        raise PortalError(400, "invalid_request")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise PortalError(400, "invalid_request")
    return value


def _query(request: web.Request, allowed: set[str]) -> None:
    if set(request.query) - allowed or any(
        len(request.query.getall(key)) != 1 for key in request.query
    ):
        raise PortalError(400, "invalid_request")


class PortalApi:
    """Обслуживает только доверенный backend сайта и проверяет каждого участника."""

    def __init__(
        self,
        bot: commands.Bot,
        config: PortalApiConfig,
        token: str,
        guild_id: int,
        *,
        builder: ProfileStatsBuilder | None = None,
    ) -> None:
        self.bot = bot
        self.config = config
        self.guild_id = guild_id
        self.builder = builder or ProfileStatsBuilder()
        self._authorization = f"Bearer {token}".encode("ascii")
        self._slots = asyncio.Semaphore(config.max_concurrent)
        self._members: OrderedDict[int, tuple[float, discord.Member]] = OrderedDict()
        self._requests: deque[float] = deque()
        self._user_requests: OrderedDict[int, deque[float]] = OrderedDict()

    def invalidate_member(self, user_id: int) -> None:
        """Не оставляет положительный кэш после события выхода или обновления."""
        self._members.pop(user_id, None)

    def _admit(self, actor_id: int) -> None:
        now = time.monotonic()
        while self._requests and self._requests[0] <= now - 60:
            self._requests.popleft()
        bucket = self._user_requests.setdefault(actor_id, deque())
        self._user_requests.move_to_end(actor_id)
        while len(self._user_requests) > self.config.member_cache_size:
            self._user_requests.popitem(last=False)
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if (
            len(self._requests) >= self.config.requests_per_minute
            or len(bucket) >= self.config.user_requests_per_minute
            or self._slots.locked()
        ):
            raise PortalError(429, "rate_limited")
        self._requests.append(now)
        bucket.append(now)

    def _guild(self) -> discord.Guild:
        if not self.bot.is_ready() or self.bot.is_closed():
            self._members.clear()
            raise PortalError(503, "bot_unavailable")
        guild = self.bot.get_guild(self.guild_id)
        if guild is None or guild.unavailable:
            self._members.clear()
            raise PortalError(503, "bot_unavailable")
        return guild

    async def _member(self, guild: discord.Guild, actor_id: int, *, fresh: bool) -> discord.Member:
        cached = self._members.get(actor_id)
        if not fresh and cached is not None and cached[0] > time.monotonic():
            self._members.move_to_end(actor_id)
            return cached[1]
        try:
            member = await guild.fetch_member(actor_id)
        except discord.NotFound:
            self.invalidate_member(actor_id)
            raise PortalError(403, "member_required") from None
        except discord.HTTPException:
            self.invalidate_member(actor_id)
            raise PortalError(503, "bot_unavailable") from None
        if member.bot:
            raise PortalError(403, "member_required")
        self._members[actor_id] = (time.monotonic() + self.config.member_cache_seconds, member)
        self._members.move_to_end(actor_id)
        while len(self._members) > self.config.member_cache_size:
            self._members.popitem(last=False)
        return member

    def _quotes(self) -> QuoteService:
        cog = cast(_QuotesCog | None, self.bot.get_cog("FunCog"))
        if cog is None or cog.quotes.closed:
            raise PortalError(503, "bot_unavailable")
        return cog.quotes

    @web.middleware
    async def guard(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        """Ограничивает запрос до обращения к Discord, ORM или файлам."""
        try:
            authorization = request.headers.getall("Authorization", [])
            if len(authorization) != 1 or not hmac.compare_digest(
                authorization[0].encode("utf-8"), self._authorization
            ):
                raise PortalError(401, "unauthorized")
            actor_headers = request.headers.getall("X-PDRoom-User-ID", [])
            if len(actor_headers) != 1 or request.can_read_body:
                raise PortalError(400, "invalid_request")
            actor = _identifier(actor_headers[0])
            self._admit(actor)
            async with self._slots, asyncio.timeout(self.config.request_timeout):
                guild = self._guild()
                member = await self._member(guild, actor, fresh=request.method == "DELETE")
                request[_ACTOR] = actor
                request[_MEMBER] = member
                request[_GUILD] = guild
                response = await handler(request)
        except PortalError as error:
            response = web.json_response({"error": error.code}, status=error.status)
        except QuotePermissionError:
            response = web.json_response({"error": "forbidden"}, status=403)
        except QuoteSourceUnavailableError:
            response = web.json_response({"error": "quote_not_found"}, status=404)
        except web.HTTPException as error:
            response = web.json_response({"error": "invalid_request"}, status=error.status)
        except (TimeoutError, QuoteStoreError, ValueError):
            response = web.json_response({"error": "bot_unavailable"}, status=503)
        except Exception as error:
            # Текст исключений внешних библиотек может содержать URL и секреты.
            logger.error("Сбой внутреннего Portal API: %s", type(error).__name__)
            response = web.json_response({"error": "bot_unavailable"}, status=503)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.status == 429:
            response.headers["Retry-After"] = "60"
        return response

    def create_app(self) -> web.Application:
        """Создаёт приложение без доступа к произвольным файлам или таблицам."""
        app = web.Application(middlewares=[self.guard], client_max_size=1024)
        app.add_routes(
            [
                web.get("/internal/v1/status", self.status),
                web.get("/internal/v1/profile", self.profile),
                web.get("/internal/v1/quotes", self.quotes),
                web.get("/internal/v1/quotes/{id}/image", self.image),
                web.delete("/internal/v1/quotes/{id}", self.delete),
            ]
        )
        return app

    async def status(self, request: web.Request) -> web.Response:
        """Подтверждает готовность бота и текущее членство пользователя."""
        _query(request, set())
        return web.json_response(
            {"ready": True, "is_owner": request[_ACTOR] == request[_GUILD].owner_id}
        )

    async def profile(self, request: web.Request) -> web.Response:
        """Возвращает личную статистику без рейтингов и чужих данных."""
        _query(request, {"period"})
        period_name = request.query.get("period", "month")
        periods = {
            "month": ProfilePeriod.current_month,
            "year": ProfilePeriod.current_year,
            "all": ProfilePeriod.all_time,
        }
        if period_name not in periods:
            raise PortalError(400, "invalid_request")
        member = request[_MEMBER]
        stats, accounts = await asyncio.gather(
            self.builder.build_stats(
                user_id=member.id,
                period=periods[period_name](),
                eligible_user_ids={member.id},
            ),
            self.builder.build_accounts(member.id),
        )
        return web.json_response(
            {
                "user": {
                    "id": str(member.id),
                    "username": member.name[:256],
                    "display_name": member.display_name[:256],
                    "avatar_url": str(member.display_avatar.with_size(128).url),
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                    "is_owner": member.id == request[_GUILD].owner_id,
                },
                "period": period_name,
                "stats": {
                    "messages": stats.messages,
                    "voice_seconds": stats.voice_seconds,
                    "reactions": stats.reactions,
                    "games": [
                        {"name": name[:256], "seconds": seconds}
                        for name, seconds in stats.top_games[:100]
                    ],
                },
                "accounts": {
                    "dota": [
                        {"id": str(pid), "name": accounts.dota_names.get(pid, str(pid))[:256]}
                        for pid in accounts.dota_ids[:100]
                    ],
                    "faceit": [
                        {"id": account.player_id, "name": account.nickname[:256]}
                        for account in accounts.faceit[:100]
                    ],
                },
                "data_since": stats.data_since,
            }
        )

    @staticmethod
    def _quote_dto(record: QuoteRecord, actor: int, owner: int | None) -> dict[str, object]:
        return {
            "id": str(record.message_id),
            "author_name": record.author_display_name,
            "created_at": record.created_at.isoformat(),
            "saved_at": record.saved_at.isoformat(),
            "saved_by": str(record.saved_by),
            "is_mine": record.saved_by == actor,
            "can_delete": QuoteService.can_delete(record, actor, owner),
            "jump_url": record.jump_url,
        }

    async def quotes(self, request: web.Request) -> web.Response:
        """Отдаёт ограниченную страницу новых карточек из доступных каналов."""
        _query(request, {"scope", "sort", "offset", "limit"})
        scope = request.query.get("scope", "mine")
        order = request.query.get("sort", "newest")
        if scope not in {"mine", "all"} or order not in {"newest", "oldest"}:
            raise PortalError(400, "invalid_request")
        offset = _number(request.query.get("offset", "0"), 0, 100000)
        limit = _number(request.query.get("limit", "24"), 1, 100)
        actor, guild = request[_ACTOR], request[_GUILD]
        if scope == "all" and actor != guild.owner_id:
            raise PortalError(403, "forbidden")
        records = [
            record
            for record in await self._quotes().visible_records(guild)
            if scope == "all" or record.saved_by == actor
        ]
        if scope == "all" and actor != guild.owner_id:
            raise PortalError(403, "forbidden")
        records.sort(
            key=lambda record: (record.saved_at, record.message_id), reverse=order == "newest"
        )
        total = len(records)
        return web.json_response(
            {
                "items": [
                    self._quote_dto(record, actor, guild.owner_id)
                    for record in records[offset : offset + limit]
                ],
                "total": total,
                "next_offset": offset + limit if offset + limit < total else None,
            }
        )

    async def image(self, request: web.Request) -> web.Response:
        """Проверяет владельца и канал перед выдачей локального webp."""
        _query(request, set())
        message_id = _identifier(request.match_info["id"])
        service = self._quotes()
        record = await service.removable_by(
            request[_GUILD], request[_ACTOR], message_id, require_visible=True
        )
        if record is None:
            raise PortalError(404, "quote_not_found")
        if record.size_bytes > _MAX_IMAGE_BYTES:
            raise PortalError(503, "bot_unavailable")
        try:
            data = await service.store.read(message_id)
        except QuoteStoreError:
            if await service.store.get(message_id) is None:
                raise PortalError(404, "quote_not_found") from None
            raise
        # Пока читали файл, канал мог стать закрытым через Gateway-событие.
        if record.channel_id not in service.public_channels(request[_GUILD]):
            raise PortalError(404, "quote_not_found")
        if not service.can_delete(record, request[_ACTOR], request[_GUILD].owner_id):
            raise PortalError(403, "forbidden")
        return web.Response(body=data, content_type="image/webp")

    async def delete(self, request: web.Request) -> web.Response:
        """Удаляет через единственный сервис бота после свежей проверки членства."""
        _query(request, set())
        message_id = _identifier(request.match_info["id"])
        deleted = await self._quotes().delete_by(
            request[_GUILD], request[_ACTOR], message_id, require_visible=True
        )
        return web.json_response({"deleted": deleted})
