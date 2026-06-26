"""Тесты для модуля cs_match_utils."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.cs_match_utils import (
    _compute_hltv1_rating,
    _compute_lobby_avg_level,
    _compute_recent_wl,
    _extract_match_stats,
    _item_is_win,
    _player_faction,
    _to_float,
    _to_int,
    get_cs_match_data,
    handle_cs_lastmatch,
    resolve_player_by_nickname,
)


def _sample_item(winner: str | None = "faction1", finished_at: int = 2000) -> dict:
    """Образец элемента истории FACEIT."""
    item = {
        "match_id": "1-match",
        "finished_at": finished_at,
        "started_at": finished_at - 1000,
        "faceit_url": "https://www.faceit.com/{lang}/cs2/room/1-match",
        "teams": {
            "faction1": {
                "players": [
                    {"player_id": "p1", "skill_level": "10"},
                    {"player_id": "x", "skill_level": "8"},
                ]
            },
            "faction2": {"players": [{"player_id": "y", "skill_level": "6"}]},
        },
        "results": {"winner": winner} if winner else {},
    }
    return item


def _sample_stats() -> dict:
    """Образец ответа /matches/{id}/stats."""
    return {
        "rounds": [
            {
                "round_stats": {"Map": "de_mirage", "Score": "16 / 13", "Rounds": "29"},
                "teams": [
                    {
                        "team_stats": {"Team Win": "1", "Final Score": "16"},
                        "players": [
                            {
                                "player_id": "p1",
                                "player_stats": {
                                    "Kills": "20",
                                    "Deaths": "10",
                                    "Assists": "5",
                                    "K/D Ratio": "2.0",
                                    "Headshots %": "50",
                                    "MVPs": "3",
                                    "ADR": "95.5",
                                    "Double Kills": "4",
                                    "Triple Kills": "2",
                                    "Quadro Kills": "1",
                                    "Penta Kills": "0",
                                },
                            }
                        ],
                    },
                    {
                        "team_stats": {"Team Win": "0", "Final Score": "13"},
                        "players": [{"player_id": "y", "player_stats": {}}],
                    },
                ],
            }
        ]
    }


def _sample_player() -> dict:
    """Образец ответа /players/{id}."""
    return {
        "nickname": "Coolguy",
        "avatar": "http://av",
        "games": {"cs2": {"faceit_elo": 2500, "skill_level": 10}},
    }


class TestPureHelpers:
    """Тесты чистых функций-помощников."""

    def test_player_faction(self):
        assert _player_faction(_sample_item(), "p1") == "faction1"
        assert _player_faction(_sample_item(), "y") == "faction2"
        assert _player_faction(_sample_item(), "unknown") is None

    def test_item_is_win(self):
        assert _item_is_win(_sample_item(winner="faction1"), "p1") is True
        assert _item_is_win(_sample_item(winner="faction2"), "p1") is False
        assert _item_is_win(_sample_item(winner=None), "p1") is None
        assert _item_is_win(_sample_item(), "unknown") is None

    def test_compute_lobby_avg_level(self):
        assert _compute_lobby_avg_level(_sample_item()) == 8.0
        assert _compute_lobby_avg_level({"teams": {}}) is None
        assert _compute_lobby_avg_level({}) is None

    def test_compute_recent_wl(self):
        items = [
            _sample_item(winner="faction1"),
            _sample_item(winner="faction2"),
            _sample_item(winner="faction1"),
            _sample_item(winner=None),
        ]
        wins, losses = _compute_recent_wl(items, "p1")
        assert wins == 2
        assert losses == 1

    def test_extract_match_stats(self):
        result = _extract_match_stats(_sample_stats(), "p1")
        assert result is not None
        round_stats, player_stats, player_team, other_team = result
        assert round_stats["Map"] == "de_mirage"
        assert player_stats["Kills"] == "20"
        assert player_team["team_stats"]["Final Score"] == "16"
        assert other_team["team_stats"]["Final Score"] == "13"

    def test_extract_match_stats_no_rounds(self):
        assert _extract_match_stats({"rounds": []}, "p1") is None

    def test_extract_match_stats_player_missing(self):
        assert _extract_match_stats(_sample_stats(), "nobody") is None

    def test_to_int(self):
        assert _to_int("20") == 20
        assert _to_int("2.7") == 2
        assert _to_int(None) == 0
        assert _to_int("abc", default=-1) == -1

    def test_to_float(self):
        assert _to_float("2.5") == 2.5
        assert _to_float(None) == 0.0
        assert _to_float("abc", default=1.0) == 1.0

    def test_compute_hltv1_rating_zero_rounds(self):
        assert _compute_hltv1_rating({"Kills": "20"}, 0) is None
        assert _compute_hltv1_rating({"Kills": "20"}, -1) is None

    def test_compute_hltv1_rating_average_player(self):
        # Игрок ровно по средним league-значениям должен дать рейтинг около 1.0.
        stats = {"Kills": "20", "Deaths": "20", "Double Kills": "5"}
        rating = _compute_hltv1_rating(stats, 30)
        assert rating is not None
        assert 0.85 < rating < 1.15

    def test_compute_hltv1_rating_strong_player(self):
        stats = {
            "Kills": "30",
            "Deaths": "10",
            "Double Kills": "5",
            "Triple Kills": "2",
            "Quadro Kills": "1",
            "Penta Kills": "0",
        }
        rating = _compute_hltv1_rating(stats, 25)
        assert rating is not None
        assert rating > 1.3

    def test_compute_hltv1_rating_weak_player(self):
        stats = {"Kills": "5", "Deaths": "20"}
        rating = _compute_hltv1_rating(stats, 25)
        assert rating is not None
        assert rating < 0.7


class TestResolvePlayer:
    """Тесты resolve_player_by_nickname."""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"player_id": "p1", "games": {"cs2": {}}}
            result = await resolve_player_by_nickname("Coolguy", "key")
            assert result is not None
            assert result["player_id"] == "p1"

    @pytest.mark.asyncio
    async def test_not_found(self):
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            assert await resolve_player_by_nickname("Nope", "key") is None

    @pytest.mark.asyncio
    async def test_no_cs2(self):
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"player_id": "p1", "games": {"csgo": {}}}
            assert await resolve_player_by_nickname("Coolguy", "key") is None


class TestGetCsMatchData:
    """Тесты get_cs_match_data."""

    @pytest.mark.asyncio
    async def test_returns_structure(self):
        history = {"items": [_sample_item()]}
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [history, _sample_stats(), _sample_player()]
            data = await get_cs_match_data(["p1"], "key", 20)

        assert data is not None
        assert data["player_id"] == "p1"
        assert data["recent_wl"] == (1, 0)
        assert data["item"]["match_id"] == "1-match"
        assert data["stats"]["rounds"]

    @pytest.mark.asyncio
    async def test_picks_latest_across_accounts(self):
        old_history = {"items": [_sample_item(finished_at=1000)]}
        new_item = _sample_item(finished_at=5000)
        new_history = {"items": [new_item]}
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [
                old_history,
                new_history,
                _sample_stats(),
                _sample_player(),
            ]
            data = await get_cs_match_data(["p1", "p2"], "key", 20)

        assert data is not None
        assert data["player_id"] == "p2"

    @pytest.mark.asyncio
    async def test_no_matches(self):
        with patch(
            "utils.cs_match_utils.faceit_get_with_retry", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"items": []}
            assert await get_cs_match_data(["p1"], "key", 20) is None

    @pytest.mark.asyncio
    async def test_empty_player_ids(self):
        assert await get_cs_match_data([], "key", 20) is None


class TestHandleCsLastmatch:
    """Тесты handle_cs_lastmatch."""

    def _ctx(self):
        ctx = MagicMock()
        ctx.bot.settings.faceit_api_key = "key"
        ctx.bot.settings.cs.recent_matches_count = 20
        ctx.send = AsyncMock()
        ctx.author.mention = "<@1>"
        return ctx

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        ctx = self._ctx()
        ctx.bot.settings.faceit_api_key = None
        await handle_cs_lastmatch(ctx, [MagicMock()], None)
        ctx.send.assert_awaited_once()
        assert "FACEIT_API_KEY" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_links(self):
        ctx = self._ctx()
        await handle_cs_lastmatch(ctx, [], None)
        ctx.send.assert_awaited_once()
        assert "cslink" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_data(self):
        ctx = self._ctx()
        link = MagicMock()
        link.faceit_player_id = "p1"
        link.nickname = "Coolguy"
        with patch("utils.cs_match_utils.get_cs_match_data", new_callable=AsyncMock) as mock_data:
            mock_data.return_value = None
            await handle_cs_lastmatch(ctx, [link], None)
        ctx.send.assert_awaited_once()
        assert "Не удалось" in ctx.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_happy_path_sends_view(self):
        ctx = self._ctx()
        link = MagicMock()
        link.faceit_player_id = "p1"
        link.nickname = "Coolguy"
        data = {
            "item": _sample_item(),
            "stats": _sample_stats(),
            "player": _sample_player(),
            "recent_wl": (5, 3),
            "player_id": "p1",
        }
        with patch("utils.cs_match_utils.get_cs_match_data", new_callable=AsyncMock) as mock_data:
            mock_data.return_value = data
            await handle_cs_lastmatch(ctx, [link], None)

        ctx.send.assert_awaited_once()
        assert "view" in ctx.send.call_args.kwargs
