"""Тесты для модуля message_utils."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from config.settings import BotSettings, ReactionsConfig, UserReaction
from utils.message_utils import handle_message


class TestHandleMessage:
    """Тесты для функции handle_message."""

    def setup_method(self):
        """Настройка для каждого теста."""
        self.mock_message = MagicMock(spec=discord.Message)
        self.mock_message.channel = MagicMock(spec=discord.TextChannel)
        self.mock_message.channel.send = AsyncMock()
        self.mock_message.author = MagicMock(spec=discord.Member)

    @pytest.mark.asyncio
    async def test_handle_message_no_reaction_user(self):
        """Тест обработки сообщения от пользователя без настроенных реакций."""
        self.mock_message.author.id = 999999999

        # Мокаем get_settings, чтобы вернуть пустые реакции
        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={})
        with patch('utils.message_utils.get_settings', return_value=mock_settings):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_single_reaction_triggered(self):
        """Тест срабатывания одиночной реакции."""
        # Используем пользователя с одиночной реакцией
        user_id = 12345
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=0.5, response="triggered")]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.1):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("triggered")

    @pytest.mark.asyncio
    async def test_handle_message_single_reaction_not_triggered(self):
        """Тест когда одиночная реакция не срабатывает."""
        user_id = 12345
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=0.5, response="not triggered")]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.9):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_first_triggered(self):
        """Тест срабатывания первой реакции из списка."""
        user_id = 999999998
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [
                UserReaction(chance=0.5, response="first reaction"),
                UserReaction(chance=0.5, response="second reaction")
            ]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.3):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("first reaction")

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_second_triggered(self):
        """Тест срабатывания второй реакции из списка."""
        user_id = 999999997
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [
                UserReaction(chance=0.2, response="first reaction"),
                UserReaction(chance=0.8, response="second reaction")
            ]
        })

        # Первая реакция не срабатывает (0.5 > 0.2), вторая срабатывает (0.5 < 0.8)
        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', side_effect=[0.5, 0.5]):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("second reaction")

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_none_triggered(self):
        """Тест когда ни одна реакция из списка не срабатывает."""
        user_id = 999999996
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [
                UserReaction(chance=0.1, response="first reaction"),
                UserReaction(chance=0.2, response="second reaction")
            ]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.9):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_only_first_sent(self):
        """Тест что отправляется только первая сработавшая реакция."""
        user_id = 999999995
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [
                UserReaction(chance=0.8, response="first reaction"),
                UserReaction(chance=0.8, response="second reaction")
            ]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.5):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("first reaction")

    @pytest.mark.asyncio
    async def test_handle_message_channel_send_error(self):
        """Тест что ошибка при отправке сообщения не пробрасывается наверх."""
        user_id = 154601435990982656
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=1.0, response="some response")]
        })

        response = MagicMock()
        response.status = 400
        self.mock_message.channel.send.side_effect = discord.HTTPException(response, "Send failed")

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.1), \
             patch('utils.message_utils.logger.error'):
            # Функция не должна пробрасывать исключение
            try:
                await handle_message(self.mock_message)
            except discord.HTTPException:
                pytest.fail("HTTPException should not be raised from handle_message")

            self.mock_message.channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_edge_case_zero_chance(self):
        """Тест граничного случая с нулевым шансом."""
        user_id = 999999994
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=0.0, response="never happens")]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.0):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_edge_case_full_chance(self):
        """Тест граничного случая со 100% шансом."""
        user_id = 999999993
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=1.0, response="always happens")]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.99):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("always happens")

    @pytest.mark.asyncio
    async def test_handle_message_disabled_reaction_skipped(self):
        """Реакция с enabled=False не срабатывает даже при гарантированном шансе."""
        user_id = 154601435990982656
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=1.0, response="иди нахуй абасранер", enabled=False)]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.0):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_disabled_reaction_falls_through_to_next(self):
        """Выключенная реакция пропускается, проверяется следующая в списке."""
        user_id = 555000111
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [
                UserReaction(chance=1.0, response="disabled", enabled=False),
                UserReaction(chance=1.0, response="enabled"),
            ]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.1):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("enabled")

    @pytest.mark.asyncio
    async def test_handle_message_empty_response(self):
        """Тест с пустым ответом."""
        user_id = 999999992
        self.mock_message.author.id = user_id

        mock_settings = BotSettings()
        mock_settings.reactions = ReactionsConfig(user_reactions={
            user_id: [UserReaction(chance=1.0, response="")]
        })

        with patch('utils.message_utils.get_settings', return_value=mock_settings), \
             patch('utils.message_utils.random.random', return_value=0.5):
            await handle_message(self.mock_message)

        self.mock_message.channel.send.assert_called_once_with("")
