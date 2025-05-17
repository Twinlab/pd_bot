"""Тесты для кога FunCog."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.fun import FunCog


class TestFunCogInit:
    """Тесты для инициализации и выгрузки FunCog."""

    def test_fun_cog_init(self, mock_bot):
        """Тест инициализации кога."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Проверяем, что атрибуты инициализированы корректно
        assert fun_cog.bot == mock_bot

    @pytest.mark.asyncio
    async def test_fun_cog_unload(self, mock_bot):
        """Тест выгрузки кога."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим logger
        with patch("cogs.fun.logger") as mock_logger:
            # Вызываем метод cog_unload
            await fun_cog.cog_unload()
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert "выгружен" in mock_logger.info.call_args[0][0]


class TestEventHandlers:
    """Тесты для обработчика событий FunCog."""

    @pytest.mark.asyncio
    async def test_on_message_delete(self, mock_bot, mock_message):
        """Тест обработчика on_message_delete."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим save_deleted_message
        with patch("cogs.fun.save_deleted_message") as mock_save:
            # Вызываем обработчик on_message_delete
            await fun_cog.on_message_delete(mock_message)
            
            # Проверяем, что save_deleted_message был вызван с правильными аргументами
            mock_save.assert_called_once_with(mock_message)


class TestCommands:
    """Тесты для команд FunCog."""

    @pytest.mark.asyncio
    async def test_deathbattle_command(self, mock_bot, mock_context, mock_member):
        """Тест команды deathbattle."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим run_battle
        with patch("cogs.fun.run_battle") as mock_run_battle:
            # Вызываем метод напрямую, а не через команду
            await fun_cog.deathbattle.callback(fun_cog, mock_context, mock_member, None)
            
            # Проверяем, что run_battle был вызван с правильными аргументами
            mock_run_battle.assert_called_once_with(mock_context, mock_member, None)

    @pytest.mark.asyncio
    async def test_snipe_command(self, mock_bot, mock_context):
        """Тест команды snipe."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим show_sniped_message
        with patch("cogs.fun.show_sniped_message") as mock_show:
            # Вызываем метод напрямую, а не через команду
            await fun_cog.snipe.callback(fun_cog, mock_context)
            
            # Проверяем, что show_sniped_message был вызван с правильными аргументами
            mock_show.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_penis_command(self, mock_bot, mock_context, mock_member):
        """Тест команды penis."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим measure_penis
        with patch("cogs.fun.measure_penis") as mock_measure:
            # Вызываем метод напрямую, а не через команду
            await fun_cog.penis.callback(fun_cog, mock_context, mock_member)
            
            # Проверяем, что measure_penis был вызван с правильными аргументами
            mock_measure.assert_called_once_with(mock_context, mock_member)

    @pytest.mark.asyncio
    async def test_avatar_command(self, mock_bot, mock_context, mock_member):
        """Тест команды avatar."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Патчим display_avatar
        with patch("cogs.fun.display_avatar") as mock_display:
            # Вызываем метод напрямую, а не через команду
            await fun_cog.avatar.callback(fun_cog, mock_context, mock_member)
            
            # Проверяем, что display_avatar был вызван с правильными аргументами
            mock_display.assert_called_once_with(mock_context, mock_member)


class TestErrorHandling:
    """Тесты для обработки ошибок в FunCog."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_class,expected_substring", [
        (commands.MissingPermissions, "нет прав"),
        (commands.CommandInvokeError, "Произошла ошибка"),
        (Exception, "неизвестная ошибка"),
    ])
    async def test_cog_command_error(self, mock_bot, mock_context, error_class, expected_substring):
        """Тест обработчика ошибок cog_command_error."""
        # Создаем экземпляр FunCog
        fun_cog = FunCog(mock_bot)
        
        # Создаем ошибку
        if error_class == commands.CommandInvokeError:
            error = error_class(Exception("Test error"))
        elif error_class == commands.MissingPermissions:
            error = error_class(["manage_messages"])
        else:
            error = error_class()
        
        # Патчим logger
        with patch("cogs.fun.logger") as mock_logger:
            # Вызываем обработчик cog_command_error
            await fun_cog.cog_command_error(mock_context, error)
            
            # Проверяем, что ctx.send был вызван с правильными аргументами
            mock_context.send.assert_called_once()
            assert expected_substring in mock_context.send.call_args[0][0]
            
            # Проверяем, что logger был вызван для CommandInvokeError и Exception
            if error_class != commands.MissingPermissions:
                mock_logger.error.assert_called_once()
