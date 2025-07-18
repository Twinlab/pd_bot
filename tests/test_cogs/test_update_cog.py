"""Тесты для кога UpdateCog."""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from cogs.update import UpdateCog


@pytest.fixture
def update_cog(mock_bot):
    """Создает экземпляр UpdateCog для тестирования."""
    return UpdateCog(mock_bot)


class TestUpdateCogInit:
    """Тесты инициализации UpdateCog."""

    def test_init_success(self, mock_bot):
        """Тест успешной инициализации кога."""
        cog = UpdateCog(mock_bot)
        assert isinstance(cog, UpdateCog)
        assert cog.bot == mock_bot

    def test_init_with_none_bot(self):
        """Тест инициализации с None в качестве бота."""
        cog = UpdateCog(None)
        assert cog.bot is None


class TestUpdateCogCommands:
    """Тесты команд UpdateCog."""

    def test_update_command_exists(self, update_cog):
        """Тест наличия команды update."""
        commands_list = [cmd.name for cmd in update_cog.get_commands()]
        assert "update" in commands_list

    def test_update_command_is_owner_only(self, update_cog):
        """Тест что команда update доступна только владельцу."""
        update_command = None
        for cmd in update_cog.get_commands():
            if cmd.name == "update":
                update_command = cmd
                break
        
        assert update_command is not None
        # Проверяем наличие декоратора is_owner
        checks = getattr(update_command, "checks", [])
        assert len(checks) > 0

    def test_update_command_is_hybrid(self, update_cog):
        """Тест что команда update является гибридной."""
        update_command = None
        for cmd in update_cog.get_commands():
            if cmd.name == "update":
                update_command = cmd
                break
        
        assert update_command is not None
        assert hasattr(update_command, "description")
        assert update_command.description == "Обновляет бота с GitHub и перезапускает его"


class TestUpdateCommand:
    """Тесты команды update."""

    @pytest.mark.asyncio
    async def test_update_already_up_to_date(self, update_cog, mock_context):
        """Тест обновления когда бот уже актуален."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        # Мокируем git pull с результатом "Already up to date"
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Already up to date.\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await update_cog.update(update_cog, mock_context)
        
        # Проверки
        mock_context.defer.assert_called_once_with(ephemeral=True)
        mock_context.send.assert_called_once_with("🔄 Проверка обновлений...", ephemeral=True)
        mock_message.edit.assert_called_with(content="✅ Бот уже обновлен до последней версии!")

    @pytest.mark.asyncio
    async def test_update_git_error(self, update_cog, mock_context):
        """Тест обработки ошибки git pull."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        # Мокируем git pull с ошибкой
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(
            return_value=(b"", b"fatal: not a git repository")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await update_cog.update(update_cog, mock_context)
        
        # Проверки
        mock_context.defer.assert_called_once_with(ephemeral=True)
        mock_message.edit.assert_called_with(
            content="❌ Ошибка Git: ```fatal: not a git repository```"
        )

    @pytest.mark.asyncio
    async def test_update_git_not_found(self, update_cog, mock_context):
        """Тест обработки отсутствия git."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        # Мокируем FileNotFoundError для git
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            await update_cog.update(update_cog, mock_context)
        
        # Проверки
        mock_context.defer.assert_called_once_with(ephemeral=True)
        mock_message.edit.assert_called_with(content="❌ Ошибка: команда 'git' не найдена.")

    @pytest.mark.asyncio
    async def test_update_successful_with_restart(self, update_cog, mock_context):
        """Тест успешного обновления с перезапуском."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        update_cog.bot.close = AsyncMock()
        
        # Мокируем git pull с обновлениями
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Updating abc123..def456\nFast-forward\n file.py | 2 +-\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell") as mock_shell, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            await update_cog.update(update_cog, mock_context)
        
        # Проверки
        mock_context.defer.assert_called_once_with(ephemeral=True)
        mock_shell.assert_called_once_with(
            update_cog.bot.settings.update.restart_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        update_cog.bot.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_successful_long_output(self, update_cog, mock_context):
        """Тест успешного обновления с длинным выводом (обрезка)."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        update_cog.bot.close = AsyncMock()
        
        # Создаем длинный вывод (больше 1900 символов)
        long_output = "Updating abc123..def456\n" + "x" * 2000
        
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(long_output.encode(), b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            await update_cog.update(update_cog, mock_context)
        
        # Проверяем что вывод был обрезан
        edit_calls = mock_message.edit.call_args_list
        update_message_call = None
        for call in edit_calls:
            if "✅ Обновление получено!" in call[1]["content"]:
                update_message_call = call
                break
        
        assert update_message_call is not None
        assert "... (truncated)" in update_message_call[1]["content"]

    @pytest.mark.asyncio
    async def test_update_restart_command_error(self, update_cog, mock_context):
        """Тест обработки ошибки команды перезапуска."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Updating abc123..def456\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell", side_effect=OSError("Permission denied")):
            
            await update_cog.update(update_cog, mock_context)
        
        # Проверяем что ошибка была обработана
        edit_calls = mock_message.edit.call_args_list
        error_message_call = None
        for call in edit_calls:
            if "не удалось инициировать перезапуск" in call[1]["content"]:
                error_message_call = call
                break
        
        assert error_message_call is not None

    @pytest.mark.asyncio
    async def test_update_restart_and_message_edit_both_fail(self, update_cog, mock_context):
        """Тест обработки ошибки когда и перезапуск и редактирование сообщения не удаются."""
        # Настройка моков
        mock_message = AsyncMock()
        # Первый edit проходит, второй (в обработке ошибки) падает
        mock_message.edit.side_effect = [None, Exception("Discord API error")]
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Updating abc123..def456\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell", side_effect=OSError("Permission denied")):
            
            # Не должно выбрасывать исключение даже если оба действия не удались
            await update_cog.update(update_cog, mock_context)
        
        # Проверяем что было несколько вызовов edit (последний упал в except)
        assert mock_message.edit.call_count >= 2

    @pytest.mark.asyncio
    async def test_update_message_edit_error(self, update_cog, mock_context):
        """Тест обработки ошибки редактирования сообщения."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_message.edit.side_effect = [None, Exception("Discord API error"), None]
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        update_cog.bot.close = AsyncMock()
        
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Updating abc123..def456\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            # Не должно выбрасывать исключение
            await update_cog.update(update_cog, mock_context)
        
        # Бот все равно должен закрыться
        update_cog.bot.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_unexpected_error(self, update_cog, mock_context):
        """Тест обработки неожиданной ошибки."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        # Мокируем неожиданную ошибку
        with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("Unexpected error")):
            await update_cog.update(update_cog, mock_context)
        
        # Проверки
        mock_message.edit.assert_called_with(
            content="❌ Непредвиденная ошибка при обновлении: Unexpected error"
        )


class TestUpdateCogErrorHandling:
    """Тесты обработки ошибок UpdateCog."""

    @pytest.mark.asyncio
    async def test_cog_command_error_not_owner(self, update_cog, mock_context):
        """Тест обработки ошибки NotOwner."""
        error = commands.NotOwner()
        mock_context.send = AsyncMock()
        mock_context.command = MagicMock()
        mock_context.command.name = "update"
        
        await update_cog.cog_command_error(mock_context, error)
        
        mock_context.send.assert_called_once_with(
            "❌ Эта команда доступна только владельцу бота.", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_cog_command_error_not_owner_no_command(self, update_cog, mock_context):
        """Тест обработки ошибки NotOwner без команды."""
        error = commands.NotOwner()
        mock_context.send = AsyncMock()
        mock_context.command = None
        
        await update_cog.cog_command_error(mock_context, error)
        
        mock_context.send.assert_called_once_with(
            "❌ Эта команда доступна только владельцу бота.", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_cog_command_error_other_error(self, update_cog, mock_context):
        """Тест обработки других ошибок."""
        error = ValueError("Test error")
        mock_context.send = AsyncMock()
        mock_context.command = MagicMock()
        mock_context.command.name = "update"
        
        await update_cog.cog_command_error(mock_context, error)
        
        mock_context.send.assert_called_once_with(
            "❌ Произошла ошибка: Test error", ephemeral=True
        )

    @pytest.mark.asyncio
    async def test_cog_command_error_other_error_no_command(self, update_cog, mock_context):
        """Тест обработки других ошибок без команды."""
        error = ValueError("Test error")
        mock_context.send = AsyncMock()
        mock_context.command = None
        
        await update_cog.cog_command_error(mock_context, error)
        
        mock_context.send.assert_called_once_with(
            "❌ Произошла ошибка: Test error", ephemeral=True
        )


class TestUpdateCogLifecycle:
    """Тесты жизненного цикла UpdateCog."""

    @pytest.mark.asyncio
    async def test_cog_unload(self, update_cog):
        """Тест выгрузки кога."""
        # Не должно выбрасывать исключение
        await update_cog.cog_unload()

    @pytest.mark.asyncio
    async def test_setup_function(self, mock_bot):
        """Тест функции setup."""
        mock_bot.add_cog = AsyncMock()
        
        # Импортируем функцию setup
        from cogs.update import setup
        
        await setup(mock_bot)
        
        # Проверяем что ког был добавлен
        mock_bot.add_cog.assert_called_once()
        args = mock_bot.add_cog.call_args[0]
        assert len(args) == 1
        assert isinstance(args[0], UpdateCog)


class TestUpdateCogIntegration:
    """Интеграционные тесты UpdateCog."""

    @pytest.mark.asyncio
    async def test_full_update_workflow_success(self, update_cog, mock_context):
        """Тест полного успешного workflow обновления."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        update_cog.bot.close = AsyncMock()
        
        # Последовательность вызовов edit
        edit_sequence = []
        
        def track_edit(**kwargs):
            edit_sequence.append(kwargs.get("content", ""))
            return AsyncMock()
        
        mock_message.edit.side_effect = track_edit
        
        # Мокируем git pull с обновлениями
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Updating abc123..def456\nFast-forward\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell") as mock_shell, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            await update_cog.update(update_cog, mock_context)
        
        # Проверяем последовательность сообщений
        assert len(edit_sequence) >= 2
        assert "🔄 Получение последних изменений..." in edit_sequence[0]
        assert "✅ Обновление получено!" in edit_sequence[1]
        assert "🔄 Перезапуск бота..." in edit_sequence[1]
        
        # Проверяем что команда перезапуска была вызвана
        mock_shell.assert_called_once()
        
        # Проверяем что бот закрылся
        update_cog.bot.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_update_workflow_no_changes(self, update_cog, mock_context):
        """Тест полного workflow когда нет изменений."""
        # Настройка моков
        mock_message = AsyncMock()
        mock_context.send = AsyncMock(return_value=mock_message)
        mock_context.defer = AsyncMock()
        
        # Мокируем git pull без изменений
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b"Already up to date.\n", b"")
        )
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
             patch("asyncio.create_subprocess_shell") as mock_shell:
            
            await update_cog.update(update_cog, mock_context)
        
        # Проверяем что команда перезапуска НЕ была вызвана
        mock_shell.assert_not_called()
        
        # Проверяем что бот НЕ закрылся
        update_cog.bot.close.assert_not_called()
