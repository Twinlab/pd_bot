"""Тесты для кога LastMatchCog."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.lastmatch import LastMatchCog


@pytest.fixture
def mock_bot(mock_settings):
    """Создает мок бота Discord."""
    bot = MagicMock(spec=commands.Bot)
    bot.settings = mock_settings
    return bot


@pytest.fixture
def mock_context(mock_bot):
    """Создает мок контекста команды."""
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = mock_bot
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 123456789
    ctx.author.mention = "<@123456789>"
    ctx.send = AsyncMock()
    ctx.defer = AsyncMock()
    return ctx


@pytest.fixture
def mock_member():
    """Создает мок участника Discord."""
    member = MagicMock(spec=discord.Member)
    member.id = 987654321
    member.mention = "<@987654321>"
    return member


@pytest.fixture
def mock_links_cog():
    """Создает мок кога LinksCog."""
    links_cog = MagicMock()
    links_cog.links_manager = MagicMock()
    links_cog.links_manager.get_links = AsyncMock()
    return links_cog


@pytest.fixture
def lastmatch_cog(mock_bot):
    """Создает экземпляр LastMatchCog."""
    return LastMatchCog(mock_bot)


class TestLastMatchCogInit:
    """Тесты инициализации кога."""

    def test_lastmatch_cog_init(self, lastmatch_cog, mock_bot):
        """Тест корректной инициализации кога."""
        assert isinstance(lastmatch_cog, LastMatchCog)
        assert lastmatch_cog.bot == mock_bot

    def test_lastmatch_cog_registers_commands(self, lastmatch_cog):
        """Тест регистрации команд кога."""
        commands_list = [cmd.name for cmd in lastmatch_cog.get_commands()]
        assert isinstance(commands_list, list)
        assert len(commands_list) > 0
        assert "lastmatch" in commands_list


class TestLastMatchCommand:
    """Тесты команды lastmatch."""

    @pytest.mark.asyncio
    async def test_lastmatch_no_links_cog(self, lastmatch_cog, mock_context):
        """Тест когда ког LinksCog недоступен."""
        mock_context.bot.get_cog.return_value = None
        
        with patch('utils.error_handler.safe_send_error') as mock_safe_send:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            mock_safe_send.assert_called_once()
            error_arg = mock_safe_send.call_args[0][1]
            assert "не удалось получить доступ к модулю привязок аккаунтов" in str(error_arg)

    @pytest.mark.asyncio
    async def test_lastmatch_no_links_manager(self, lastmatch_cog, mock_context):
        """Тест когда у кога LinksCog нет links_manager."""
        mock_links_cog = MagicMock()
        # Удаляем атрибут links_manager
        if hasattr(mock_links_cog, 'links_manager'):
            delattr(mock_links_cog, 'links_manager')
        mock_context.bot.get_cog.return_value = mock_links_cog
        
        with patch('utils.error_handler.safe_send_error') as mock_safe_send:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            mock_safe_send.assert_called_once()
            error_arg = mock_safe_send.call_args[0][1]
            assert "внутренняя ошибка модуля привязок" in str(error_arg)

    @pytest.mark.asyncio
    async def test_lastmatch_links_manager_exception(self, lastmatch_cog, mock_context, mock_links_cog):
        """Тест обработки исключения при вызове links_manager.get_links."""
        mock_context.bot.get_cog.return_value = mock_links_cog
        mock_links_cog.links_manager.get_links.side_effect = Exception("Database error")
        
        with patch('utils.error_handler.safe_send_error') as mock_safe_send:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            mock_safe_send.assert_called_once()
            error_arg = mock_safe_send.call_args[0][1]
            assert "Ошибка при получении привязанных аккаунтов" in str(error_arg)

    @pytest.mark.asyncio
    async def test_lastmatch_successful_self(self, lastmatch_cog, mock_context, mock_links_cog):
        """Тест успешного выполнения команды для себя."""
        mock_context.bot.get_cog.return_value = mock_links_cog
        mock_links_cog.links_manager.get_links.return_value = [12345, 67890]
        
        with patch('cogs.lastmatch.handle_lastmatch') as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            mock_context.defer.assert_called_once()
            mock_handle.assert_called_once_with(mock_context, [12345, 67890], None)

    @pytest.mark.asyncio
    async def test_lastmatch_successful_other_member(self, lastmatch_cog, mock_context, mock_links_cog, mock_member):
        """Тест успешного выполнения команды для другого пользователя."""
        mock_context.bot.get_cog.return_value = mock_links_cog
        mock_links_cog.links_manager.get_links.return_value = [54321]
        
        with patch('cogs.lastmatch.handle_lastmatch') as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context, mock_member)
            
            mock_context.defer.assert_called_once()
            mock_links_cog.links_manager.get_links.assert_called_once_with(mock_member.id)
            mock_handle.assert_called_once_with(mock_context, [54321], mock_member)

    @pytest.mark.asyncio
    async def test_lastmatch_empty_links_list(self, lastmatch_cog, mock_context, mock_links_cog):
        """Тест когда список привязок пуст."""
        mock_context.bot.get_cog.return_value = mock_links_cog
        mock_links_cog.links_manager.get_links.return_value = []
        
        with patch('cogs.lastmatch.handle_lastmatch') as mock_handle:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            mock_context.defer.assert_called_once()
            mock_handle.assert_called_once_with(mock_context, [], None)


class TestCogLifecycle:
    """Тесты жизненного цикла кога."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, lastmatch_cog):
        """Тест выгрузки кога."""
        with patch('cogs.lastmatch.logger') as mock_logger:
            await lastmatch_cog.cog_unload()
            
            mock_logger.info.assert_called_once_with("Ког LastMatchCog выгружен.")

    @pytest.mark.asyncio
    async def test_cog_command_error_missing_permissions(self, lastmatch_cog, mock_context):
        """Тест обработки ошибки отсутствия прав."""
        error = commands.MissingPermissions(["administrator"])
        
        await lastmatch_cog.cog_command_error(mock_context, error)
        
        mock_context.send.assert_called_once_with(
            "У вас нет прав для выполнения этой команды.", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_cog_command_error_command_invoke_error(self, lastmatch_cog, mock_context):
        """Тест обработки ошибки выполнения команды."""
        original_error = ValueError("Test error")
        error = commands.CommandInvokeError(original_error)
        
        with patch('cogs.lastmatch.logger') as mock_logger:
            await lastmatch_cog.cog_command_error(mock_context, error)
            
            mock_logger.error.assert_called_once()
            mock_context.send.assert_called_once_with(
                f"Произошла ошибка: {original_error}", ephemeral=True
            )

    @pytest.mark.asyncio
    async def test_cog_command_error_unknown_error(self, lastmatch_cog, mock_context):
        """Тест обработки неизвестной ошибки."""
        error = Exception("Unknown error")
        
        with patch('cogs.lastmatch.logger') as mock_logger:
            await lastmatch_cog.cog_command_error(mock_context, error)
            
            mock_logger.error.assert_called_once()
            mock_context.send.assert_called_once_with(
                f"Произошла неизвестная ошибка: {error}", ephemeral=True
            )


class TestSetupFunction:
    """Тесты функции setup."""

    @pytest.mark.asyncio
    async def test_setup_function(self, mock_bot):
        """Тест функции setup кога."""
        from cogs.lastmatch import setup
        
        with patch('cogs.lastmatch.logger') as mock_logger:
            await setup(mock_bot)
            
            mock_bot.add_cog.assert_called_once()
            added_cog = mock_bot.add_cog.call_args[0][0]
            assert isinstance(added_cog, LastMatchCog)
            assert added_cog.bot == mock_bot
            
            mock_logger.info.assert_called_once_with("Ког LastMatchCog успешно загружен.")


class TestCommandDecorators:
    """Тесты декораторов команды."""

    def test_lastmatch_command_is_hybrid(self, lastmatch_cog):
        """Тест что команда lastmatch является hybrid командой."""
        lastmatch_command = None
        for cmd in lastmatch_cog.get_commands():
            if cmd.name == "lastmatch":
                lastmatch_command = cmd
                break
        
        assert lastmatch_command is not None
        assert hasattr(lastmatch_command, 'app_command')

    def test_lastmatch_command_has_error_handler(self, lastmatch_cog):
        """Тест что команда lastmatch имеет обработчик ошибок."""
        lastmatch_command = None
        for cmd in lastmatch_cog.get_commands():
            if cmd.name == "lastmatch":
                lastmatch_command = cmd
                break
        
        assert lastmatch_command is not None
        # Проверяем что команда обернута декоратором command_error_handler
        assert hasattr(lastmatch_command.callback, '__wrapped__')


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_full_workflow_success(self, lastmatch_cog, mock_context, mock_links_cog, mock_member):
        """Тест полного успешного workflow команды."""
        # Настройка моков
        mock_context.bot.get_cog.return_value = mock_links_cog
        mock_links_cog.links_manager.get_links.return_value = [12345]
        
        with patch('cogs.lastmatch.handle_lastmatch') as mock_handle:
            # Выполнение команды
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context, mock_member)
            
            # Проверки
            mock_context.bot.get_cog.assert_called_once_with("LinksCog")
            mock_links_cog.links_manager.get_links.assert_called_once_with(mock_member.id)
            mock_context.defer.assert_called_once()
            mock_handle.assert_called_once_with(mock_context, [12345], mock_member)

    @pytest.mark.asyncio
    async def test_full_workflow_error_chain(self, lastmatch_cog, mock_context):
        """Тест цепочки ошибок в workflow."""
        # Сценарий: нет кога LinksCog
        mock_context.bot.get_cog.return_value = None
        
        with patch('utils.error_handler.safe_send_error') as mock_safe_send:
            await lastmatch_cog.lastmatch.callback(lastmatch_cog, mock_context)
            
            # Проверяем что defer не вызывался при ошибке
            mock_context.defer.assert_not_called()
            mock_safe_send.assert_called_once()
