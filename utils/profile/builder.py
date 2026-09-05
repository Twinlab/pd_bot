"""Сбор данных для интерактивного профиля пользователя."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from config import get_settings
from utils.activity_data_manager import ActivityDataManager
from utils.cs_links_data_manager import CsLinksDataManager
from utils.links_data_manager import LinksDataManager
from utils.time_utils import MOSCOW_TZ
from utils.top_reactions_data_manager import (
    AuthorLeaderboardEntry,
    PeriodType,
    TopReactionsDataManager,
)
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals

ProfileScope = Literal["month", "year", "all"]

MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


@dataclass(frozen=True, slots=True)
class ProfilePeriod:
    """Период, выбранный в профиле."""

    scope: ProfileScope
    year: int | None = None
    month: int | None = None

    def __post_init__(self) -> None:
        if self.scope == "month":
            if self.year is None or self.month is None or not 1 <= self.month <= 12:
                raise ValueError("Для месячного периода нужны корректные year и month.")
        elif self.scope == "year":
            if self.year is None or self.month is not None:
                raise ValueError("Для годового периода нужен только year.")
        elif self.scope == "all" and (self.year is not None or self.month is not None):
            raise ValueError("Период «всё время» не принимает year или month.")

    @classmethod
    def current_month(cls, now: datetime | None = None) -> ProfilePeriod:
        """Текущий месяц по московскому времени."""
        current = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
        return cls("month", current.year, current.month)

    @classmethod
    def current_year(cls, now: datetime | None = None) -> ProfilePeriod:
        """Текущий год по московскому времени."""
        current = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
        return cls("year", current.year)

    @classmethod
    def all_time(cls) -> ProfilePeriod:
        """Весь доступный период сбора данных."""
        return cls("all")

    @property
    def label(self) -> str:
        """Человекочитаемая подпись периода."""
        if self.scope == "month":
            assert self.month is not None
            assert self.year is not None
            return f"{MONTH_NAMES_RU[self.month]} {self.year}"
        if self.scope == "year":
            return f"{self.year} год"
        return "Всё время"

    @property
    def reaction_period(self) -> PeriodType:
        """Период в формате менеджера реакций."""
        return self.scope


@dataclass(frozen=True, slots=True)
class ProfileMoment:
    """Популярное сообщение пользователя."""

    content: str
    jump_url: str
    reactions: int


@dataclass(frozen=True, slots=True)
class FaceitAccount:
    """Сохранённая FACEIT-привязка."""

    player_id: str
    nickname: str


@dataclass(frozen=True, slots=True)
class ProfileAccounts:
    """Игровые аккаунты пользователя."""

    dota_ids: tuple[int, ...] = ()
    faceit: tuple[FaceitAccount, ...] = ()


@dataclass(slots=True)
class ProfileStats:
    """Сводная статистика пользователя за выбранный период."""

    period: ProfilePeriod
    messages: int = 0
    voice_seconds: int = 0
    reactions: int = 0
    top_games: list[tuple[str, int]] = field(default_factory=list)
    message_rank: int | None = None
    voice_rank: int | None = None
    reaction_rank: int | None = None
    current_game: str | None = None
    data_since: str | None = None

    @property
    def game_seconds(self) -> int:
        """Общее игровое время."""
        return sum(seconds for _, seconds in self.top_games)

    @property
    def favorite_game(self) -> tuple[str, int] | None:
        """Самая продолжительная игра периода."""
        return self.top_games[0] if self.top_games else None


class ProfileStatsBuilder:
    """Объединяет локальные источники статистики профиля."""

    def __init__(
        self,
        *,
        activity_manager: ActivityDataManager | None = None,
        user_stats_manager: UserStatsDataManager | None = None,
        reactions_manager: TopReactionsDataManager | None = None,
        links_manager: LinksDataManager | None = None,
        cs_links_manager: CsLinksDataManager | None = None,
    ) -> None:
        self.activity_manager = activity_manager or ActivityDataManager()
        self.user_stats_manager = user_stats_manager or UserStatsDataManager()
        self.reactions_manager = reactions_manager or TopReactionsDataManager()
        self.links_manager = links_manager or LinksDataManager()
        self.cs_links_manager = cs_links_manager or CsLinksDataManager()

    @staticmethod
    def _merge_games(*parts: dict[str, int]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for part in parts:
            for game, seconds in part.items():
                merged[game] = merged.get(game, 0) + seconds
        return merged

    async def _get_games(self, user_id: int, period: ProfilePeriod) -> dict[str, int]:
        if period.scope == "month":
            assert period.year is not None
            assert period.month is not None
            monthly, daily = await asyncio.gather(
                self.activity_manager.get_monthly_stats(user_id, period.year, period.month),
                self.activity_manager.get_daily_stats_by_prefix(
                    user_id, f"{period.year}-{period.month:02d}"
                ),
            )
            return self._merge_games(monthly, daily)

        if period.scope == "year":
            assert period.year is not None
            yearly, daily = await asyncio.gather(
                self.activity_manager.get_yearly_stats(user_id, period.year),
                self.activity_manager.get_daily_stats_by_prefix(user_id, str(period.year)),
            )
            return self._merge_games(yearly, daily)

        return await self.activity_manager.get_all_time_stats(user_id)

    async def _get_user_totals(self, period: ProfilePeriod) -> dict[int, UserTotals]:
        if period.scope == "month":
            assert period.year is not None
            assert period.month is not None
            monthly, daily = await asyncio.gather(
                self.user_stats_manager.get_monthly_totals(period.year, period.month),
                self.user_stats_manager.get_daily_totals_by_prefix(
                    f"{period.year}-{period.month:02d}"
                ),
            )
            return self.user_stats_manager.merge_totals(monthly, daily)

        if period.scope == "year":
            assert period.year is not None
            yearly, daily = await asyncio.gather(
                self.user_stats_manager.get_yearly_totals(period.year),
                self.user_stats_manager.get_daily_totals_by_prefix(str(period.year)),
            )
            return self.user_stats_manager.merge_totals(yearly, daily)

        return await self.user_stats_manager.get_all_time_totals()

    async def _get_reaction_authors(self, period: ProfilePeriod) -> list[AuthorLeaderboardEntry]:
        settings = get_settings().top_reactions
        return await self.reactions_manager.get_top_authors(
            period.reaction_period,
            1000,
            year=period.year,
            month=period.month,
            excluded_message_ids=set(settings.ignored_message_ids),
            ignore_self_reactions=settings.ignore_self_reactions,
            timezone=MOSCOW_TZ,
        )

    @staticmethod
    def _rank(
        totals: dict[int, UserTotals],
        user_id: int,
        *,
        metric: Literal["messages", "voice_seconds"],
    ) -> int | None:
        ranked = sorted(
            (total for total in totals.values() if getattr(total, metric) > 0),
            key=lambda total: getattr(total, metric),
            reverse=True,
        )
        return next(
            (index for index, total in enumerate(ranked, 1) if total.user_id == user_id), None
        )

    async def build_stats(
        self,
        *,
        user_id: int,
        period: ProfilePeriod,
        eligible_user_ids: set[int] | None = None,
        current_game: str | None = None,
    ) -> ProfileStats:
        """Собирает обзор и игровую статистику пользователя."""
        games, user_totals, reaction_authors = await asyncio.gather(
            self._get_games(user_id, period),
            self._get_user_totals(period),
            self._get_reaction_authors(period),
        )

        if eligible_user_ids is not None:
            user_totals = {
                uid: totals for uid, totals in user_totals.items() if uid in eligible_user_ids
            }
            reaction_authors = [
                entry for entry in reaction_authors if entry.author_id in eligible_user_ids
            ]

        mine = user_totals.get(user_id, UserTotals(user_id, 0, 0))
        reaction_entry = next(
            (entry for entry in reaction_authors if entry.author_id == user_id),
            None,
        )
        reaction_rank = next(
            (
                index
                for index, entry in enumerate(reaction_authors, 1)
                if entry.author_id == user_id
            ),
            None,
        )

        return ProfileStats(
            period=period,
            messages=mine.messages,
            voice_seconds=mine.voice_seconds,
            reactions=reaction_entry.total_reactions if reaction_entry else 0,
            top_games=sorted(games.items(), key=lambda item: item[1], reverse=True),
            message_rank=self._rank(user_totals, user_id, metric="messages"),
            voice_rank=self._rank(user_totals, user_id, metric="voice_seconds"),
            reaction_rank=reaction_rank,
            current_game=current_game,
            data_since=get_settings().user_stats.data_since,
        )

    async def build_moments(
        self,
        *,
        user_id: int,
        period: ProfilePeriod,
        allowed_channel_ids: set[int],
        limit: int = 3,
    ) -> list[ProfileMoment]:
        """Возвращает популярные сообщения пользователя из разрешённых каналов."""
        settings = get_settings().top_reactions
        entries = await self.reactions_manager.get_leaderboard(
            period.reaction_period,
            limit,
            year=period.year,
            month=period.month,
            author_id=user_id,
            allowed_channel_ids=allowed_channel_ids,
            excluded_message_ids=set(settings.ignored_message_ids),
            ignore_self_reactions=settings.ignore_self_reactions,
            timezone=MOSCOW_TZ,
        )
        return [
            ProfileMoment(
                content=entry.content,
                jump_url=entry.jump_url,
                reactions=entry.reactor_count,
            )
            for entry in entries
        ]

    async def build_accounts(self, user_id: int) -> ProfileAccounts:
        """Возвращает только сохранённые локальные игровые привязки."""
        dota_ids, faceit_links = await asyncio.gather(
            self.links_manager.get_links(user_id),
            self.cs_links_manager.get_links(user_id),
        )
        return ProfileAccounts(
            dota_ids=tuple(dota_ids),
            faceit=tuple(
                FaceitAccount(player_id=link.faceit_player_id, nickname=link.nickname)
                for link in faceit_links
            ),
        )
