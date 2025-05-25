"""Тесты для модуля message_utils."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.message_utils import USER_REACTIONS, ReactionConfig, handle_message


class TestReactionConfig:
    """Тесты для типа ReactionConfig."""

    def test_reaction_config_type(self):
        """Тест что ReactionConfig является правильным TypedDict."""
        config: ReactionConfig = {"chance": 0.5, "response": "test"}
        assert "chance" in config
        assert "response" in config
        assert isinstance(config["chance"], float)
        assert isinstance(config["response"], str)


class TestUserReactions:
    """Тесты для константы USER_REACTIONS."""

    def test_user_reactions_structure(self):
        """Тест структуры USER_REACTIONS."""
        assert isinstance(USER_REACTIONS, dict)
        assert len(USER_REACTIONS) > 0
        
        for user_id, reaction_data in USER_REACTIONS.items():
            assert isinstance(user_id, int)
            assert isinstance(reaction_data, (dict, list))
            
            if isinstance(reaction_data, dict):
                assert "chance" in reaction_data
                assert "response" in reaction_data
                assert isinstance(reaction_data["chance"], float)
                assert isinstance(reaction_data["response"], str)
            elif isinstance(reaction_data, list):
                for reaction in reaction_data:
                    assert isinstance(reaction, dict)
                    assert "chance" in reaction
                    assert "response" in reaction
                    assert isinstance(reaction["chance"], float)
                    assert isinstance(reaction["response"], str)

    def test_user_reactions_specific_users(self):
        """Тест что определенные пользователи присутствуют в конфигурации."""
        expected_users = [
            154601435990982656,
            305650048904200202,
            138053844167950347,
            159347749991481344,
            245874719855738880
        ]
        
        for user_id in expected_users:
            assert user_id in USER_REACTIONS


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
        self.mock_message.author.id = 999999999  # ID не в USER_REACTIONS
        
        await handle_message(self.mock_message)
        
        self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_single_reaction_triggered(self):
        """Тест срабатывания одиночной реакции."""
        # Используем пользователя с одиночной реакцией
        user_id = 154601435990982656
        self.mock_message.author.id = user_id
        
        with patch('utils.message_utils.random.random', return_value=0.01):  # Меньше чем 0.05
            await handle_message(self.mock_message)
            
            self.mock_message.channel.send.assert_called_once_with("иди нахуй абасранер")

    @pytest.mark.asyncio
    async def test_handle_message_single_reaction_not_triggered(self):
        """Тест когда одиночная реакция не срабатывает."""
        user_id = 154601435990982656
        self.mock_message.author.id = user_id
        
        with patch('utils.message_utils.random.random', return_value=0.1):  # Больше чем 0.05
            await handle_message(self.mock_message)
            
            self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_first_triggered(self):
        """Тест срабатывания первой реакции из списка."""
        # Создаем тестового пользователя с множественными реакциями
        test_user_id = 999999998
        test_reactions = [
            {"chance": 0.5, "response": "first reaction"},
            {"chance": 0.5, "response": "second reaction"}
        ]
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reactions}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.3):  # Меньше 0.5
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_called_once_with("first reaction")

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_second_triggered(self):
        """Тест срабатывания второй реакции из списка."""
        test_user_id = 999999997
        test_reactions = [
            {"chance": 0.2, "response": "first reaction"},
            {"chance": 0.8, "response": "second reaction"}
        ]
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reactions}):
            self.mock_message.author.id = test_user_id
            
            # Первая реакция не срабатывает (0.5 > 0.2), вторая срабатывает (0.5 < 0.8)
            with patch('utils.message_utils.random.random', return_value=0.5):
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_called_once_with("second reaction")

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_none_triggered(self):
        """Тест когда ни одна реакция из списка не срабатывает."""
        test_user_id = 999999996
        test_reactions = [
            {"chance": 0.1, "response": "first reaction"},
            {"chance": 0.2, "response": "second reaction"}
        ]
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reactions}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.9):  # Больше всех шансов
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_multiple_reactions_only_first_sent(self):
        """Тест что отправляется только первая сработавшая реакция."""
        test_user_id = 999999995
        test_reactions = [
            {"chance": 0.8, "response": "first reaction"},
            {"chance": 0.8, "response": "second reaction"}
        ]
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reactions}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.5):  # Обе должны сработать
                await handle_message(self.mock_message)
                
                # Проверяем что вызвана только одна отправка
                self.mock_message.channel.send.assert_called_once_with("first reaction")

    @pytest.mark.asyncio
    async def test_handle_message_real_user_reactions(self):
        """Тест с реальными пользователями из конфигурации."""
        # Тестируем пользователя с очень низким шансом
        user_id = 305650048904200202  # deус
        self.mock_message.author.id = user_id
        
        # Принудительно срабатываем реакцию
        with patch('utils.message_utils.random.random', return_value=0.00005):  # Меньше 0.0001
            await handle_message(self.mock_message)
            
            self.mock_message.channel.send.assert_called_once_with("деус, не клоуничай")

    @pytest.mark.asyncio
    async def test_handle_message_channel_send_error(self):
        """Тест что ошибка при отправке сообщения пробрасывается наверх."""
        user_id = 154601435990982656
        self.mock_message.author.id = user_id
        
        # Создаем правильное исключение HTTPException
        response = MagicMock()
        response.status = 400
        self.mock_message.channel.send.side_effect = discord.HTTPException(response, "Send failed")
        
        with patch('utils.message_utils.random.random', return_value=0.01):
            # Функция должна пробросить исключение наверх
            with pytest.raises(discord.HTTPException):
                await handle_message(self.mock_message)
            
            self.mock_message.channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_edge_case_zero_chance(self):
        """Тест граничного случая с нулевым шансом."""
        test_user_id = 999999994
        test_reaction = {"chance": 0.0, "response": "never happens"}
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reaction}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.0):
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_edge_case_full_chance(self):
        """Тест граничного случая со 100% шансом."""
        test_user_id = 999999993
        test_reaction = {"chance": 1.0, "response": "always happens"}
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reaction}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.99):
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_called_once_with("always happens")

    @pytest.mark.asyncio
    async def test_handle_message_empty_response(self):
        """Тест с пустым ответом."""
        test_user_id = 999999992
        test_reaction = {"chance": 1.0, "response": ""}
        
        with patch.dict('utils.message_utils.USER_REACTIONS', {test_user_id: test_reaction}):
            self.mock_message.author.id = test_user_id
            
            with patch('utils.message_utils.random.random', return_value=0.5):
                await handle_message(self.mock_message)
                
                self.mock_message.channel.send.assert_called_once_with("")

    @pytest.mark.asyncio
    async def test_handle_message_unicode_response(self):
        """Тест с Unicode символами в ответе."""
        user_id = 138053844167950347  # Пользователь с эмодзи
        self.mock_message.author.id = user_id
        
        with patch('utils.message_utils.random.random', return_value=0.00005):
            await handle_message(self.mock_message)
            
            self.mock_message.channel.send.assert_called_once_with("🎤🐀")


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_full_workflow_with_real_message_mock(self):
        """Тест полного workflow с реалистичным моком сообщения."""
        # Создаем более реалистичный мок сообщения
        mock_message = MagicMock(spec=discord.Message)
        mock_message.author = MagicMock(spec=discord.Member)
        mock_message.author.id = 154601435990982656
        mock_message.channel = MagicMock(spec=discord.TextChannel)
        mock_message.channel.send = AsyncMock()
        mock_message.content = "Test message content"
        mock_message.guild = MagicMock(spec=discord.Guild)
        
        with patch('utils.message_utils.random.random', return_value=0.01):
            await handle_message(mock_message)
            
            mock_message.channel.send.assert_called_once_with("иди нахуй абасранер")

    def test_module_constants(self):
        """Тест что модуль экспортирует необходимые константы."""
        from utils.message_utils import USER_REACTIONS, ReactionConfig
        
        assert USER_REACTIONS is not None
        assert ReactionConfig is not None
        assert len(USER_REACTIONS) > 0
