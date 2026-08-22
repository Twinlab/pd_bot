"""Тесты для main.py."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


class TestMainWithNewConfig:
    """Тесты для main.py с новой системой конфигурации."""

    @pytest.mark.asyncio
    async def test_main_imports_successfully(self):
        """Тест успешного импорта main.py с новой конфигурацией."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {"BOT_TOKEN": "test_token", "STRATZ_API_KEY": "test_key"}):
            # Патчим YAML файл
            with patch("pathlib.Path.exists", return_value=False):
                # Патчим другие зависимости
                with patch("main.setup_logging"), patch("main.initialize_database"):
                    # Импортируем main после патчинга
                    import importlib

                    if "main" in sys.modules:
                        main_module = importlib.reload(sys.modules["main"])
                    else:
                        import main as main_module

                    # Проверяем, что основные объекты созданы
                    assert hasattr(main_module, "settings")
                    assert hasattr(main_module, "bot")
                    assert main_module.settings.bot_token == "test_token"

    @pytest.mark.asyncio
    async def test_load_cogs_with_new_config(self):
        """Тест загрузки когов с новой системой конфигурации."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {"BOT_TOKEN": "test_token", "STRATZ_API_KEY": "test_key"}):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота
                mock_bot = MagicMock()
                mock_bot.load_extension = AsyncMock()

                # Патчим зависимости
                with (
                    patch("main.setup_logging"),
                    patch("main.initialize_database"),
                    patch("main.bot", mock_bot),
                    patch("pathlib.Path.glob") as mock_glob,
                ):
                    # Настраиваем мок для Path.glob
                    mock_glob.return_value = [
                        Path("cogs/admin.py"),
                        Path("cogs/activity.py"),
                        Path("cogs/__init__.py"),
                    ]

                    # Импортируем и вызываем функцию
                    import main as main_module

                    await main_module.load_cogs()

                    # Проверяем, что load_extension был вызван
                    assert mock_bot.load_extension.call_count >= 2

    @pytest.mark.asyncio
    async def test_main_function_with_new_config(self):
        """Тест основной функции main с новой конфигурацией."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {"BOT_TOKEN": "test_token", "STRATZ_API_KEY": "test_key"}):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота
                mock_bot = MagicMock()
                mock_bot.start = AsyncMock()

                # Патчим зависимости
                with (
                    patch("main.setup_logging"),
                    patch("main.initialize_database", AsyncMock()) as mock_init_db,
                    patch("main.prune_expired_cache", AsyncMock()) as mock_prune_cache,
                    patch("main.close_database", AsyncMock()) as mock_close_db,
                    patch("main.load_cogs", AsyncMock()) as mock_load_cogs,
                    patch("main.bot", mock_bot),
                ):
                    # Импортируем и вызываем функцию
                    import main as main_module

                    await main_module.main()

                    # Проверяем, что все функции были вызваны
                    mock_init_db.assert_called_once()
                    mock_prune_cache.assert_awaited_once()
                    mock_load_cogs.assert_called_once()
                    mock_bot.start.assert_called_once_with("test_token")

    def test_bot_creation_with_new_config(self):
        """Тест создания бота с новой системой конфигурации."""
        # Патчим переменные окружения
        with patch.dict(
            os.environ, {"BOT_TOKEN": "test_token", "STRATZ_API_KEY": "test_key", "BOT_PREFIX": "?"}
        ):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("main.setup_logging"), patch("main.initialize_database"):
                    # Импортируем main
                    import importlib

                    if "main" in sys.modules:
                        main_module = importlib.reload(sys.modules["main"])
                    else:
                        import main as main_module

                    # Проверяем, что бот создан с правильным префиксом
                    assert main_module.bot.command_prefix == "?"
                    assert hasattr(main_module.bot, "settings")

    @pytest.mark.asyncio
    async def test_setup_hook_calls_sync(self):
        """setup_hook делегирует синк команд в _sync_commands."""
        import main as main_module

        bot = main_module.bot
        with patch.object(bot, "_sync_commands", new_callable=AsyncMock) as mock_sync:
            await bot.setup_hook()

        mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_global_sync_when_no_guild_id(self):
        """Без guild_id — один глобальный синк, без copy_global_to/очистки."""
        import main as main_module

        bot = main_module.bot
        fake_settings = MagicMock()
        fake_settings.guild_id = None
        with (
            patch.object(bot.tree, "sync", new=AsyncMock(return_value=[MagicMock(name="c")])),
            patch.object(bot.tree, "copy_global_to") as mock_copy,
            patch("main.get_settings", return_value=fake_settings),
        ):
            await bot._sync_commands()

            bot.tree.sync.assert_awaited_once_with()
            mock_copy.assert_not_called()

    @pytest.mark.asyncio
    async def test_guild_scoped_sync_when_guild_id_set(self):
        """С guild_id команды копируются в гильдию, глобальные дубликаты сносятся."""
        import main as main_module

        bot = main_module.bot
        fake_settings = MagicMock()
        fake_settings.guild_id = 123456789
        with (
            patch.object(bot.tree, "sync", new=AsyncMock(return_value=[MagicMock(name="c")])),
            patch.object(bot.tree, "copy_global_to") as mock_copy,
            patch.object(bot.tree, "clear_commands") as mock_clear,
            patch("main.get_settings", return_value=fake_settings),
        ):
            await bot._sync_commands()

            mock_copy.assert_called_once()
            assert mock_copy.call_args.kwargs["guild"].id == 123456789
            mock_clear.assert_called_once_with(guild=None)
            assert bot.tree.sync.await_count == 2

    @pytest.mark.asyncio
    async def test_sync_handles_error(self):
        """Ошибка синка логируется, но не пробрасывается наружу."""
        import main as main_module

        bot = main_module.bot
        fake_settings = MagicMock()
        fake_settings.guild_id = None
        with (
            patch.object(bot.tree, "sync", new=AsyncMock(side_effect=Exception("boom"))),
            patch("main.get_settings", return_value=fake_settings),
            patch("main.logger") as mock_logger,
        ):
            await bot._sync_commands()

            mock_logger.error.assert_called_once()
            assert "Не удалось синхронизировать" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_error_handling_in_main(self):
        """Тест обработки ошибок в функции main."""
        # Патчим переменные окружения
        with patch.dict(os.environ, {"BOT_TOKEN": "test_token", "STRATZ_API_KEY": "test_key"}):
            with patch("pathlib.Path.exists", return_value=False):
                # Создаем мок бота с ошибкой
                mock_bot = MagicMock()
                mock_bot.start = AsyncMock(side_effect=Exception("Test error"))

                # Патчим зависимости
                with (
                    patch("main.setup_logging"),
                    patch("main.initialize_database", AsyncMock()),
                    patch("main.prune_expired_cache", AsyncMock()),
                    patch("main.close_database", AsyncMock()),
                    patch("main.load_cogs", AsyncMock()),
                    patch("main.bot", mock_bot),
                    patch("main.logger") as mock_logger,
                ):
                    # Импортируем и вызываем функцию
                    import main as main_module

                    with pytest.raises(Exception, match="Test error"):
                        await main_module.main()

                    # Проверяем, что ошибка была залогирована
                    mock_logger.exception.assert_called_once_with("Не удалось запустить бота")


class TestGracefulShutdown:
    """Ограниченное по времени завершение процесса и ресурсов."""

    @pytest.mark.asyncio
    async def test_cleanup_step_times_out_without_raising(self) -> None:
        import main as main_module

        blocker = asyncio.Event()

        async def never_finishes() -> None:
            await blocker.wait()

        with patch("main.logger") as mock_logger:
            result = await main_module._run_cleanup_step("test", never_finishes, 0.01)

        assert result is False
        mock_logger.error.assert_called_once_with(
            "Таймаут %.1f с при закрытии ресурса %s",
            0.01,
            "test",
        )

    @pytest.mark.asyncio
    async def test_cleanup_step_logs_exception_and_continues(self) -> None:
        import main as main_module

        async def fails() -> None:
            raise RuntimeError("boom")

        with patch("main.logger") as mock_logger:
            result = await main_module._run_cleanup_step("test", fails, 1.0)

        assert result is False
        mock_logger.exception.assert_called_once_with(
            "Ошибка при закрытии ресурса %s",
            "test",
        )

    @pytest.mark.asyncio
    async def test_database_closes_even_when_network_cleanup_times_out(self) -> None:
        import main as main_module

        blocker = asyncio.Event()

        async def never_finishes() -> None:
            await blocker.wait()

        close_dota = AsyncMock(side_effect=never_finishes)
        close_cs = AsyncMock()
        close_deathbattle = AsyncMock()
        close_match_card = AsyncMock()
        close_nodes = AsyncMock()
        close_database = AsyncMock()

        with (
            patch("utils.dota_api.close_session", close_dota),
            patch("utils.cs_api.close_session", close_cs),
            patch("utils.deathbattle_utils.close_session", close_deathbattle),
            patch("utils.match_card.close_session", close_match_card),
            patch("utils.music.close_nodes", close_nodes),
            patch("main.close_database", close_database),
            patch("main.RESOURCE_CLOSE_TIMEOUT_SECONDS", 0.01),
        ):
            await main_module._shutdown_resources(database_initialized=True)

        close_dota.assert_awaited_once()
        close_cs.assert_awaited_once()
        close_deathbattle.assert_awaited_once()
        close_match_card.assert_awaited_once()
        close_nodes.assert_awaited_once()
        close_database.assert_awaited_once()

    def test_signal_handler_requests_task_cancellation(self) -> None:
        import main as main_module

        task = MagicMock(spec=asyncio.Task)
        task.done.return_value = False
        task.cancelling.return_value = 0
        loop = MagicMock()

        with patch("main.asyncio.get_running_loop", return_value=loop):
            installed = main_module._install_shutdown_handlers(task)

        assert installed == [main_module.signal.SIGINT, main_module.signal.SIGTERM]
        first_call = loop.add_signal_handler.call_args_list[0]
        callback = first_call.args[1]
        callback(*first_call.args[2:])
        task.cancel.assert_called_once_with()
