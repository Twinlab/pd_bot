"""Проверки годовых итогов, аватаров и геометрии нового wrapped."""

from dataclasses import replace
from datetime import date
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from utils.activity_data_manager import ActivityDataManager
from utils.top_reactions_data_manager import TopReactionsDataManager
from utils.user_stats_data_manager import UserStatsDataManager, UserTotals
from utils.wrapped import cards
from utils.wrapped.builder import NamedValue, PersonalWrapped, ServerWrapped, build_personal_wrapped, build_server_wrapped
from utils.wrapped_data_manager import MonthlySnapshot

MONTHS = frozenset(range(1, 13))


def snapshot(messages=100, games=None, user_months=MONTHS, game_months=MONTHS):
    return MonthlySnapshot({1: UserTotals(1, messages, 3660)}, games or {1: {"A": 3601}},
                           user_months, game_months)


async def server(current, old, since="2025-01-01", today=date(2027, 1, 1)):
    reactions = TopReactionsDataManager()
    reactions.get_leaderboard = AsyncMock(return_value=[])
    reactions.get_top_authors = AsyncMock(return_value=[])
    with patch("utils.wrapped_data_manager.WrappedDataManager.get_year",
               AsyncMock(side_effect=[current, old])) as read, \
         patch("utils.wrapped.monthly.moscow_today", return_value=today):
        result = await build_server_wrapped(
            scope="yearly", year=2026, month=None,
            stats_mgr=UserStatsDataManager(), activity_mgr=ActivityDataManager(),
            reactions_mgr=reactions, top_limit=5, data_since=since,
            allowed_channel_ids={10}, excluded_message_ids={20}, excluded_user_ids={30},
        )
    return result, read, reactions


async def test_yearly_totals_union_diversity_and_reaction_filters():
    current = snapshot(games={1: {"A": 3600, "B": 3601}, 2: {"A": 1800}})
    result, _, reactions = await server(current, snapshot(messages=0))
    assert result.total_messages == 100
    assert result.active_users == 2
    assert result.total_game_seconds == 9001
    assert result.previous["messages"] == 0
    noms = {n.title: n for n in result.nominations}
    assert set(noms) == {"Разнообразие игр", "Геймер"}
    assert noms["Разнообразие игр"].detail == "1 игра"
    for call in (reactions.get_leaderboard.await_args, reactions.get_top_authors.await_args):
        assert call.args[0] == "year"
        assert call.kwargs["strict"]
        assert call.kwargs["allowed_channel_ids"] == {10}
        assert call.kwargs["excluded_message_ids"] == {20}
        assert call.kwargs["excluded_user_ids"] == {30}


@pytest.mark.parametrize("old", [MonthlySnapshot({}, {}), RuntimeError("unavailable")])
async def test_missing_previous_year_is_not_zero(old):
    result, _, _ = await server(snapshot(), old)
    assert result.previous == {}


@pytest.mark.parametrize("since,today", [
    ("2026-06-01", date(2027,1,1)),
    ("2025-01-01", date(2026,12,31)),
    (None, date(2027,1,1)),
])
async def test_unfinished_or_partial_year_never_compares(since, today):
    result, read, _ = await server(snapshot(), snapshot(), since, today)
    assert result.previous == {}
    assert read.await_count == 1


async def test_metric_requires_all_months_in_both_years():
    result, _, _ = await server(snapshot(user_months=frozenset({1})), snapshot())
    assert result.previous == {"games": 3601}
    result, _, _ = await server(snapshot(), snapshot(game_months=frozenset({1})))
    assert set(result.previous) == {"messages", "voice"}


async def test_current_year_read_failure_aborts():
    with pytest.raises(RuntimeError, match="current"):
        await server(RuntimeError("current"), snapshot())


async def test_personal_uses_one_snapshot_and_zero_baseline():
    mgr = TopReactionsDataManager()
    mgr.get_top_authors = AsyncMock(return_value=[])
    with patch("utils.wrapped_data_manager.WrappedDataManager.get_year",
               AsyncMock(side_effect=[snapshot(), snapshot(messages=0)])) as read, \
         patch("utils.wrapped.monthly.moscow_today", return_value=date(2027,1,1)):
        result = await build_personal_wrapped(
            user_id=1, year=2026, stats_mgr=UserStatsDataManager(),
            activity_mgr=ActivityDataManager(), reactions_mgr=mgr, data_since="2025-01-01",
        )
    assert read.await_count == 2
    assert result.previous["messages"] == 0
    assert result.game_seconds == sum(value for _, value in result.top_games)
    assert result.message_rank == 1


def fixture():
    return ServerWrapped("2026 год", "yearly", 123, 3661, 3601, 1,
                         top_messages=[NamedValue(1,123)], top_voice=[NamedValue(1,3661)],
                         top_games=[("Game",3601)])


def check_boxes(canvas):
    for i, a in enumerate(canvas.boxes):
        for b in canvas.boxes[i+1:]:
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1])


@pytest.mark.parametrize("scope,label", [("yearly","2026 год"), ("monthly","Август 2026")])
def test_real_avatar_pixels_are_used_in_both_server_scopes(scope,label):
    avatar = Image.new("RGB",(100,200),(12,200,40))
    raw = BytesIO()
    avatar.save(raw,format="PNG")
    result=Image.open(BytesIO(cards.render_server(
        replace(fixture(),scope=scope,period_label=label),lambda uid:"Same name",{1:raw.getvalue()})))
    assert any(color == (12,200,40) for _, color in result.getcolors(result.width * result.height))


def test_bad_avatar_and_long_name_do_not_break_layout():
    data=fixture()
    png=cards.render_server(data,lambda uid:"Очень длинный ник "*40,{1:b"broken"})
    assert png.startswith(b"\x89PNG")
    canvas=cards._server(data,{1:"Очень длинный ник "*40},{})
    check_boxes(canvas)


def test_personal_centering_rank_hash_and_hidden_comparisons():
    personal=PersonalWrapped(1,"2026 год",100,100,100,0,None,message_rank=2,voice_rank=1)
    labels=[]
    original=cards._Canvas.text
    def record(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        labels.append((args[2],self.boxes[-1]))
        return result
    with patch.object(cards._Canvas,"text",record):
        canvas=cards._personal(personal,"mango",{})
    check_boxes(canvas)
    assert {"#1","#2"} <= {label for label,_ in labels}
    assert not any("%" in label or "Было" in label or "ПРОТОТИП" in label for label,_ in labels)
    bbox=next(box for label,box in labels if label=="mango")
    assert abs((bbox[0]+bbox[2])/2-600) <= 1


def test_largest_counts_remain_inside_canvas():
    data=replace(fixture(),total_messages=2**63-1,total_voice_seconds=2**63-1,
                 total_game_seconds=2**63-1,active_users=2**63-1,
                 previous=dict.fromkeys(["messages","voice","games","users"],1))
    check_boxes(cards._server(data,{1:"Name"},{}))
