"""Тесты для модуля dota_match_utils."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.dota_match_utils import get_match_data, handle_lastmatch

_PNG = b"\x89PNG\r\n\x1a\n"


def _count_buttons(view: discord.ui.LayoutView) -> int:
    """Считает все кнопки внутри LayoutView (с обходом контейнеров и рядов)."""
    count = 0

    def walk(items) -> None:
        nonlocal count
        for item in items:
            if isinstance(item, discord.ui.Button):
                count += 1
            children = getattr(item, "children", None)
            if children:
                walk(children)

    walk(view.children)
    return count


class TestGetMatchData:
    """Тесты для функции get_match_data."""

    @pytest.mark.asyncio
    async def test_get_match_data_no_user_links(self):
        """Тест когда пользователь не найден в user_links."""
        user_links = {}
        user_id = "123456"
        stratz_api_key = "fake_key"

        result = await get_match_data(user_links, user_id, stratz_api_key)

        assert result == (None, None, None, None)

    @pytest.mark.asyncio
    async def test_get_match_data_empty_user_links(self):
        """Тест когда у пользователя пустой список привязок."""
        user_links = {"123456": []}
        user_id = "123456"
        stratz_api_key = "fake_key"

        result = await get_match_data(user_links, user_id, stratz_api_key)

        assert result == (None, None, None, None)

    @pytest.mark.asyncio
    async def test_get_match_data_no_api_key(self):
        """Тест когда не предоставлен API ключ."""
        user_links = {"123456": [12345]}
        user_id = "123456"
        stratz_api_key = ""

        result = await get_match_data(user_links, user_id, stratz_api_key)

        assert result == (None, None, None, None)

    @pytest.mark.asyncio
    async def test_get_match_data_no_matches_found(self):
        """Тест когда не найдено матчей."""
        user_links = {"123456": [12345]}
        user_id = "123456"
        stratz_api_key = "fake_key"

        with patch("utils.dota_match_utils.query_api_with_retry") as mock_query:
            mock_query.return_value = {"player": {"matches": []}}

            result = await get_match_data(user_links, user_id, stratz_api_key)

            assert result == (None, None, None, None)

    @pytest.mark.asyncio
    async def test_get_match_data_successful(self):
        """Тест успешного получения данных."""
        user_links = {"123456": [12345]}
        user_id = "123456"
        stratz_api_key = "fake_key"

        mock_matches_response = {
            "player": {"matches": [{"id": 7000000000, "startDateTime": 1640995200}]}
        }

        mock_match_response = {"match": {"players": [{"steamAccount": {"name": "TestPlayer"}}]}}

        mock_weekly_response = {"player": {"matches": []}}
        mock_items_dict = {"1": {"displayName": "Item"}}

        with (
            patch("utils.dota_match_utils.query_api_with_retry") as mock_query,
            patch("utils.dota_match_utils.fetch_items_data") as mock_items,
        ):
            mock_query.side_effect = [
                mock_matches_response,
                mock_match_response,
                mock_weekly_response,
            ]
            mock_items.return_value = mock_items_dict

            result = await get_match_data(user_links, user_id, stratz_api_key)

            match_data, weekly_data, match_id, items_dict = result
            assert match_data == mock_match_response
            assert match_id == 7000000000

    @pytest.mark.asyncio
    async def test_get_match_data_multiple_accounts(self):
        """Тест выбора самого свежего матча среди нескольких аккаунтов."""
        user_links = {"123456": [12345, 67890]}
        user_id = "123456"
        stratz_api_key = "fake_key"

        with (
            patch("utils.dota_match_utils.query_api_with_retry") as mock_query,
            patch("utils.dota_match_utils.fetch_items_data"),
        ):
            mock_query.side_effect = [
                {"player": {"matches": [{"id": 7000000001, "startDateTime": 1640995200}]}},
                {"player": {"matches": [{"id": 7000000002, "startDateTime": 1641081600}]}},
                {"match": {"players": [{"steamAccount": {"name": "Test"}}]}},
                {"player": {"matches": []}},
            ]

            result = await get_match_data(user_links, user_id, stratz_api_key)

            match_data, weekly_data, match_id, items_dict = result
            assert match_id == 7000000002  # Более свежий матч


class TestHandleLastmatch:
    """Тесты для функции handle_lastmatch.

    После перехода на PNG-карточку контент уезжает в картинку, поэтому проверяем
    не текст вью, а аргумент-дата-класс, который хендлер отдаёт в ``render_dota_card``,
    плюс факт отправки ``file`` + сохранённых accent-полосы и кнопок.
    """

    def setup_method(self):
        """Настройка для каждого теста."""
        self.mock_ctx = MagicMock()
        self.mock_ctx.send = AsyncMock()
        self.mock_ctx.author = MagicMock()
        self.mock_ctx.author.id = 123456
        self.mock_ctx.author.mention = "<@123456>"
        self.mock_ctx.bot = MagicMock()
        self.mock_ctx.bot.settings = MagicMock()
        self.mock_ctx.bot.settings.stratz_api_key = "fake_key"

    @pytest.mark.asyncio
    async def test_handle_lastmatch_no_api_key(self):
        """Тест когда нет API ключа в конфигурации."""
        self.mock_ctx.bot.settings.stratz_api_key = None
        user_links_list = [12345]

        await handle_lastmatch(self.mock_ctx, user_links_list)

        self.mock_ctx.send.assert_called_once_with(
            "Ошибка: STRATZ_API_KEY не найден в конфигурации бота."
        )

    @pytest.mark.asyncio
    async def test_handle_lastmatch_no_linked_accounts_self(self):
        """Тест когда у пользователя нет привязанных аккаунтов (для себя)."""
        user_links_list = []

        await handle_lastmatch(self.mock_ctx, user_links_list)

        expected_message = (
            "Сначала привяжите ваш аккаунт Discord к аккаунту Dota 2. "
            "Используйте команду `/link PLAYER_ID`."
        )
        self.mock_ctx.send.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_handle_lastmatch_no_linked_accounts_other_user(self):
        """Тест когда у другого пользователя нет привязанных аккаунтов."""
        user_links_list = []
        mock_member = MagicMock()
        mock_member.id = 789012
        mock_member.mention = "<@789012>"

        await handle_lastmatch(self.mock_ctx, user_links_list, mock_member)

        expected_message = (
            "Пользователь <@789012> не привязал свой аккаунт Dota 2. "
            "Используйте команду `/link PLAYER_ID`."
        )
        self.mock_ctx.send.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_handle_lastmatch_no_match_data(self):
        """Тест когда не удалось получить данные о матче."""
        user_links_list = [12345]

        with patch("utils.dota_match_utils.get_match_data") as mock_get_match:
            mock_get_match.return_value = (None, None, None, None)

            await handle_lastmatch(self.mock_ctx, user_links_list)

            expected_message = (
                "Не удалось получить данные о последнем матче. "
                "Убедитесь, что история матчей доступна в настройках Dota 2, "
                "или попробуйте позже."
            )
            self.mock_ctx.send.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_handle_lastmatch_invalid_player_data(self):
        """Тест когда данные игрока некорректны."""
        user_links_list = [12345]

        mock_match_data = {"match": {"players": []}}

        with patch("utils.dota_match_utils.get_match_data") as mock_get_match:
            mock_get_match.return_value = (mock_match_data, None, 7000000000, {})

            await handle_lastmatch(self.mock_ctx, user_links_list)

            self.mock_ctx.send.assert_called_once_with("Ошибка при обработке данных матча.")

    @pytest.mark.asyncio
    async def test_handle_lastmatch_successful_victory(self):
        """Победный матч: карточка-картинка + зелёный accent + 3 кнопки, вердикт/предметы в дата-классе."""
        user_links_list = [12345]

        mock_match_data = {
            "match": {
                "startDateTime": 1640995200,
                "durationSeconds": 1800,
                "rank": 3500,
                "gameMode": 1,
                "lobbyType": 0,
                "players": [
                    {
                        "steamAccount": {"name": "TestPlayer", "avatar": "avatar.jpg"},
                        "hero": {"shortName": "pudge"},
                        "position": "POSITION_5",
                        "kills": 8,
                        "deaths": 2,
                        "assists": 15,
                        "goldPerMinute": 450,
                        "experiencePerMinute": 550,
                        "networth": 15000,
                        "heroDamage": 20000,
                        "isVictory": True,
                        "item0Id": 1,
                        "neutral0Id": 100,
                    }
                ],
            }
        }

        mock_weekly_data = {
            "player": {"matches": [{"startDateTime": 1640995200, "players": [{"isVictory": True}]}]}
        }

        mock_items_dict = {
            1: {"name": "item_branches", "displayName": "Iron Branch"},
            100: {"name": "item_keen_optic", "displayName": "Keen Optic"},
        }

        with (
            patch("utils.dota_match_utils.get_match_data") as mock_get_match,
            patch("utils.dota_match_utils.render_dota_card", return_value=_PNG) as mock_render,
            patch("utils.dota_match_utils.fetch_image_bytes", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_get_match.return_value = (
                mock_match_data,
                mock_weekly_data,
                7000000000,
                mock_items_dict,
            )
            mock_fetch.return_value = None

            await handle_lastmatch(self.mock_ctx, user_links_list)

        self.mock_ctx.send.assert_called_once()
        call_args = self.mock_ctx.send.call_args
        assert "embed" not in call_args.kwargs
        assert call_args.kwargs["file"].filename == "dota_match.png"

        view = call_args.kwargs["view"]
        assert isinstance(view, discord.ui.LayoutView)
        assert view.children[0].accent_colour == discord.Color.green()
        assert _count_buttons(view) == 3

        card = mock_render.call_args.args[0]
        assert card.verdict == "красава разъебал"
        assert card.is_victory is True
        assert card.items[0].display_name == "Iron Branch"
        assert card.neutral is not None
        assert card.neutral.display_name == "Keen Optic"

    @pytest.mark.asyncio
    async def test_handle_lastmatch_defeat_poor_kda(self):
        """Поражение с плохим KDA: красный accent и соответствующий вердикт в дата-классе."""
        user_links_list = [12345]

        mock_match_data = {
            "match": {
                "startDateTime": 1640995200,
                "durationSeconds": 2400,
                "rank": 2000,
                "gameMode": 2,
                "lobbyType": 1,
                "players": [
                    {
                        "steamAccount": {"name": "BadPlayer"},
                        "hero": {"shortName": "invoker"},
                        "position": "POSITION_2",
                        "kills": 2,
                        "deaths": 10,
                        "assists": 3,
                        "goldPerMinute": 300,
                        "experiencePerMinute": 400,
                        "networth": 8000,
                        "heroDamage": 12000,
                        "isVictory": False,
                    }
                ],
            }
        }

        with (
            patch("utils.dota_match_utils.get_match_data") as mock_get_match,
            patch("utils.dota_match_utils.render_dota_card", return_value=_PNG) as mock_render,
            patch("utils.dota_match_utils.fetch_image_bytes", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_get_match.return_value = (mock_match_data, None, 7000000001, {})
            mock_fetch.return_value = None

            await handle_lastmatch(self.mock_ctx, user_links_list)

        view = self.mock_ctx.send.call_args.kwargs["view"]
        assert view.children[0].accent_colour == discord.Color.red()

        card = mock_render.call_args.args[0]
        assert card.verdict == "заруинил пидорас"
        assert card.is_victory is False

    @pytest.mark.asyncio
    async def test_handle_lastmatch_with_member_parameter(self):
        """Тест вызова для другого пользователя."""
        user_links_list = [67890]
        mock_member = MagicMock()
        mock_member.id = 789012
        mock_member.mention = "<@789012>"

        mock_match_data = {
            "match": {
                "startDateTime": 1640995200,
                "durationSeconds": 1500,
                "rank": 4000,
                "gameMode": 1,
                "lobbyType": 0,
                "players": [
                    {
                        "steamAccount": {"name": "OtherPlayer"},
                        "hero": {"shortName": "crystal_maiden"},
                        "position": "POSITION_5",
                        "kills": 3,
                        "deaths": 5,
                        "assists": 12,
                        "goldPerMinute": 350,
                        "experiencePerMinute": 450,
                        "networth": 10000,
                        "heroDamage": 8000,
                        "isVictory": True,
                    }
                ],
            }
        }

        with (
            patch("utils.dota_match_utils.get_match_data") as mock_get_match,
            patch("utils.dota_match_utils.render_dota_card", return_value=_PNG),
            patch("utils.dota_match_utils.fetch_image_bytes", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_get_match.return_value = (mock_match_data, None, 7000000002, {})
            mock_fetch.return_value = None

            await handle_lastmatch(self.mock_ctx, user_links_list, mock_member)

            mock_get_match.assert_called_once()
            call_args = mock_get_match.call_args[0]
            user_id = call_args[1]

            assert user_id == "789012"

    @pytest.mark.asyncio
    async def test_handle_lastmatch_items_in_card(self):
        """Предметы: валидные попадают в дата-класс с именами, нулевые/неизвестные → пустые слоты."""
        user_links_list = [12345]

        mock_match_data = {
            "match": {
                "startDateTime": 1640995200,
                "durationSeconds": 1800,
                "rank": 3000,
                "gameMode": 1,
                "lobbyType": 0,
                "players": [
                    {
                        "steamAccount": {"name": "ItemPlayer"},
                        "hero": {"shortName": "pudge"},
                        "position": "POSITION_5",
                        "kills": 5,
                        "deaths": 3,
                        "assists": 8,
                        "goldPerMinute": 400,
                        "experiencePerMinute": 500,
                        "networth": 12000,
                        "heroDamage": 15000,
                        "isVictory": True,
                        "item0Id": 1,
                        "item1Id": 0,
                        "item2Id": None,
                        "item3Id": 999,
                        "item4Id": 4,
                        "item5Id": 5,
                        "neutral0Id": 100,
                    }
                ],
            }
        }

        mock_items_dict = {
            1: {"name": "item_branches", "displayName": "Iron Branch"},
            4: {"name": "item_magic_stick", "displayName": "Magic Stick"},
            5: {"name": "item_ward_observer", "displayName": "Observer Ward"},
            100: {"name": "item_keen_optic", "displayName": "Keen Optic"},
        }

        with (
            patch("utils.dota_match_utils.get_match_data") as mock_get_match,
            patch("utils.dota_match_utils.render_dota_card", return_value=_PNG) as mock_render,
            patch("utils.dota_match_utils.fetch_image_bytes", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_get_match.return_value = (mock_match_data, None, 7000000003, mock_items_dict)
            mock_fetch.return_value = None

            await handle_lastmatch(self.mock_ctx, user_links_list)

        card = mock_render.call_args.args[0]
        names = [it.display_name for it in card.items]
        assert names == ["Iron Branch", "", "", "", "Magic Stick", "Observer Ward"]
        assert card.neutral is not None
        assert card.neutral.display_name == "Keen Optic"

    @pytest.mark.asyncio
    async def test_handle_lastmatch_no_items_data(self):
        """Когда предметов нет (items_dict=None): все слоты пустые, нейтралки нет."""
        user_links_list = [12345]

        mock_match_data = {
            "match": {
                "startDateTime": 1640995200,
                "durationSeconds": 1800,
                "rank": 3000,
                "gameMode": 1,
                "lobbyType": 0,
                "players": [
                    {
                        "steamAccount": {"name": "NoItemsPlayer"},
                        "hero": {"shortName": "pudge"},
                        "position": "POSITION_5",
                        "kills": 5,
                        "deaths": 3,
                        "assists": 8,
                        "goldPerMinute": 400,
                        "experiencePerMinute": 500,
                        "networth": 12000,
                        "heroDamage": 15000,
                        "isVictory": True,
                        "item0Id": 1,
                        "neutral0Id": 100,
                    }
                ],
            }
        }

        with (
            patch("utils.dota_match_utils.get_match_data") as mock_get_match,
            patch("utils.dota_match_utils.render_dota_card", return_value=_PNG) as mock_render,
            patch("utils.dota_match_utils.fetch_image_bytes", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_get_match.return_value = (mock_match_data, None, 7000000004, None)
            mock_fetch.return_value = None

            await handle_lastmatch(self.mock_ctx, user_links_list)

        card = mock_render.call_args.args[0]
        assert len(card.items) == 6
        assert all(it.display_name == "" and it.image is None for it in card.items)
        assert card.neutral is None
