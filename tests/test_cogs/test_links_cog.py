"""Тесты для LinksCog - команды привязки аккаунтов Dota 2."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.links import LinksCog


@pytest.fixture
def mock_links_manager():
    """Создает мок менеджера данных привязок."""
    manager = MagicMock()
    manager.get_links = AsyncMock()
    manager.add_link = AsyncMock()
    manager.remove_link = AsyncMock()
    manager.remove_all_links = AsyncMock()
    return manager


@pytest.fixture
def links_cog(mock_bot, mock_links_manager):
    """Создает экземпляр LinksCog с мок-зависимостями."""
    cog = LinksCog(mock_bot)
    cog.links_manager = mock_links_manager
    return cog


class TestLinksCogInit:
    """Тесты инициализации LinksCog."""

    def test_links_cog_init(self, mock_bot):
        """Тест корректной инициализации кога."""
        cog = LinksCog(mock_bot)
        assert isinstance(cog, LinksCog)
        assert cog.bot == mock_bot
        assert hasattr(cog, "links_manager")
        assert cog.cog_name == "Links"

    def test_links_cog_registers_commands(self, links_cog):
        """Тест регистрации команд кога."""
        commands = [cmd.name for cmd in links_cog.get_commands()]
        assert isinstance(commands, list)
        assert len(commands) == 3
        assert "link" in commands
        assert "unlink" in commands
        assert "links" in commands


class TestSendResponse:
    """Тесты метода send_response.

    После рефакторинга это тонкая обёртка над ``utils.error_handler.safe_send``.
    Прежняя ветвистая логика interaction/followup/DM-fallback живёт уже
    внутри safe_send и покрыта своими тестами. Здесь оставлена только
    проверка делегирования.
    """

    @pytest.mark.asyncio
    async def test_send_response_delegates_to_safe_send(self, links_cog, mock_context):
        """send_response должен звать safe_send с ephemeral=True."""
        with patch("cogs.links.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await links_cog.send_response(mock_context, "Тестовое сообщение")

        mock_safe_send.assert_awaited_once_with(
            mock_context, "Тестовое сообщение", ephemeral=True
        )


class TestLinkCommand:
    """Тесты команды link."""

    @pytest.mark.asyncio
    async def test_link_success_first_account(self, links_cog, mock_context, mock_links_manager):
        """Тест успешной привязки первого аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []
        mock_links_manager.add_link.return_value = True
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_links_manager.get_links.assert_called_once_with(123456789)
        mock_links_manager.add_link.assert_called_once_with(123456789, 987654321)
        mock_send.assert_called_once()
        assert "успешно привязан" in mock_send.call_args[0][1]
        assert "lastmatch" in mock_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_link_success_additional_account(self, links_cog, mock_context, mock_links_manager):
        """Тест успешной привязки дополнительного аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [111111111]
        mock_links_manager.add_link.return_value = True
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "успешно привязан" in message
        assert "несколько аккаунтов" in message
        assert "автоматически выберет" in message

    @pytest.mark.asyncio
    async def test_link_invalid_player_id_negative(self, links_cog, mock_context):
        """Тест привязки с отрицательным ID игрока."""
        mock_context.interaction = None
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, -123)
        
        mock_send.assert_called_once_with(
            mock_context, "ID игрока должен быть положительным числом."
        )

    @pytest.mark.asyncio
    async def test_link_invalid_player_id_zero(self, links_cog, mock_context):
        """Тест привязки с нулевым ID игрока."""
        mock_context.interaction = None
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 0)
        
        mock_send.assert_called_once_with(
            mock_context, "ID игрока должен быть положительным числом."
        )

    @pytest.mark.asyncio
    async def test_link_already_linked(self, links_cog, mock_context, mock_links_manager):
        """Тест привязки уже привязанного аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321, 111111111]
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once_with(
            mock_context, "Аккаунт Dota 2 с ID 987654321 уже привязан."
        )

    @pytest.mark.asyncio
    async def test_link_limit_reached(self, links_cog, mock_context, mock_links_manager):
        """Тест привязки при достижении лимита аккаунтов."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [1, 2, 3, 4, 5]  # 5 аккаунтов
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once_with(
            mock_context, "Вы достигли лимита в 5 привязанных аккаунтов."
        )

    @pytest.mark.asyncio
    async def test_link_database_error(self, links_cog, mock_context, mock_links_manager):
        """Тест обработки ошибки базы данных при привязке."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []
        mock_links_manager.add_link.return_value = False
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "Произошла ошибка при добавлении привязки" in message

    @pytest.mark.asyncio
    async def test_link_with_interaction_defer(self, links_cog, mock_context, mock_links_manager):
        """Тест команды link с interaction (должен вызвать defer)."""
        mock_interaction = MagicMock()
        mock_context.interaction = mock_interaction
        mock_context.defer = AsyncMock()  # defer вызывается на контексте, а не на interaction
        mock_context.author.id = 123456789
        mock_links_manager.get_links.return_value = []
        mock_links_manager.add_link.return_value = True
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock):
            await links_cog.link.callback(links_cog, mock_context, 987654321)
        
        mock_context.defer.assert_called_once_with(ephemeral=True)


class TestUnlinkCommand:
    """Тесты команды unlink."""

    @pytest.mark.asyncio
    async def test_unlink_no_links(self, links_cog, mock_context, mock_links_manager):
        """Тест отвязки когда нет привязанных аккаунтов."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context)
        
        mock_send.assert_called_once_with(
            mock_context, "У вас нет привязанных аккаунтов Dota 2."
        )

    @pytest.mark.asyncio
    async def test_unlink_specific_success_with_remaining(self, links_cog, mock_context, mock_links_manager):
        """Тест успешной отвязки конкретного аккаунта с оставшимися."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321, 111111111]
        mock_links_manager.remove_link.return_value = True
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context, 987654321)
        
        mock_links_manager.remove_link.assert_called_once_with(123456789, 987654321)
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "успешно отвязан" in message
        assert "остаются привязанными" in message

    @pytest.mark.asyncio
    async def test_unlink_specific_success_last_account(self, links_cog, mock_context, mock_links_manager):
        """Тест успешной отвязки последнего аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321]
        mock_links_manager.remove_link.return_value = True
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "успешно отвязан" in message
        assert "больше нет привязанных аккаунтов" in message

    @pytest.mark.asyncio
    async def test_unlink_specific_not_found(self, links_cog, mock_context, mock_links_manager):
        """Тест отвязки несуществующего аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [111111111, 222222222]
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "не привязан" in message
        assert "Ваши аккаунты:" in message

    @pytest.mark.asyncio
    async def test_unlink_specific_database_error(self, links_cog, mock_context, mock_links_manager):
        """Тест обработки ошибки базы данных при отвязке."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321]
        mock_links_manager.remove_link.return_value = False
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context, 987654321)
        
        mock_send.assert_called_once_with(
            mock_context, "Произошла ошибка при удалении привязки."
        )

    @pytest.mark.asyncio
    async def test_unlink_all_success(self, links_cog, mock_context, mock_links_manager):
        """Тест успешной отвязки всех аккаунтов."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [111111111, 222222222]
        mock_links_manager.remove_all_links.return_value = 2
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context)
        
        mock_links_manager.remove_all_links.assert_called_once_with(123456789)
        mock_send.assert_called_once_with(
            mock_context, "Все 2 аккаунтов Dota 2 были успешно отвязаны."
        )

    @pytest.mark.asyncio
    async def test_unlink_all_no_accounts_removed(self, links_cog, mock_context, mock_links_manager):
        """Тест отвязки всех аккаунтов когда ничего не удалено."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [111111111]
        mock_links_manager.remove_all_links.return_value = 0
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.unlink.callback(links_cog, mock_context)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "Не удалось отвязать аккаунты" in message


class TestLinksCommand:
    """Тесты команды links."""

    @pytest.mark.asyncio
    async def test_links_single_account(self, links_cog, mock_context, mock_links_manager):
        """Тест отображения одного привязанного аккаунта."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321]
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.links.callback(links_cog, mock_context)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "Ваш привязанный аккаунт Dota 2:" in message
        assert "987654321" in message

    @pytest.mark.asyncio
    async def test_links_multiple_accounts(self, links_cog, mock_context, mock_links_manager):
        """Тест отображения нескольких привязанных аккаунтов."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = [987654321, 111111111, 222222222]
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.links.callback(links_cog, mock_context)
        
        mock_send.assert_called_once()
        message = mock_send.call_args[0][1]
        assert "Ваши привязанные аккаунты Dota 2:" in message
        assert "987654321" in message
        assert "111111111" in message
        assert "222222222" in message
        assert "автоматически выберет" in message

    @pytest.mark.asyncio
    async def test_links_no_accounts(self, links_cog, mock_context, mock_links_manager):
        """Тест отображения когда нет привязанных аккаунтов."""
        mock_context.author.id = 123456789
        mock_context.interaction = None
        mock_links_manager.get_links.return_value = []
        
        with patch.object(links_cog, 'send_response', new_callable=AsyncMock) as mock_send:
            await links_cog.links.callback(links_cog, mock_context)
        
        mock_send.assert_called_once_with(
            mock_context, "У вас нет привязанных аккаунтов Dota 2. Используйте `/link PLAYER_ID`."
        )


# Локальный cog_command_error удалён — обработка ошибок централизована
# в handlers/events.py. Старые тесты вместе с ним выпилены.


class TestCogLifecycle:
    """Тесты жизненного цикла кога."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, links_cog):
        """Тест выгрузки кога."""
        # Не должно вызывать исключений
        await links_cog.cog_unload()

    @pytest.mark.asyncio
    async def test_setup_function(self, mock_bot):
        """Тест функции setup."""
        from cogs.links import setup
        
        mock_bot.add_cog = AsyncMock()
        await setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        added_cog = mock_bot.add_cog.call_args[0][0]
        assert isinstance(added_cog, LinksCog)
