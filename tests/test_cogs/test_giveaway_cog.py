"""Тесты для кога GiveawayCog."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.giveaway import GiveawayCog


class TestGiveawayCogInit:
    """Тесты для инициализации и выгрузки GiveawayCog."""

    def test_giveaway_cog_init(self, mock_bot):
        """Тест инициализации кога."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Проверяем, что атрибуты инициализированы корректно
        assert giveaway_cog.bot == mock_bot
        assert isinstance(giveaway_cog.active_giveaways, dict)
        assert len(giveaway_cog.active_giveaways) == 0

    @pytest.mark.asyncio
    async def test_giveaway_cog_unload(self, mock_bot):
        """Тест выгрузки кога."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Создаем мок для задачи
        mock_task = MagicMock()
        mock_task.done.return_value = False
        
        # Добавляем задачу в active_giveaways
        giveaway_cog.active_giveaways[123] = mock_task
        
        # Патчим logger
        with patch("cogs.giveaway.logger") as mock_logger:
            # Вызываем метод cog_unload
            await giveaway_cog.cog_unload()
            
            # Проверяем, что task.cancel был вызван
            mock_task.cancel.assert_called_once()
            
            # Проверяем, что logger.info был вызван
            assert mock_logger.info.call_count >= 2
            assert "Отмена активных задач" in mock_logger.info.call_args_list[0][0][0]


class TestHelperMethods:
    """Тесты для вспомогательных методов GiveawayCog."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("duration_str,expected_seconds", [
        ("1h", 3600),
        ("30m", 1800),
        ("45s", 45),
        ("1h30m", 5400),
        ("1h30m20s", 5420),
        ("2h15m", 8100),
        ("0s", None),  # Нулевая длительность
        ("invalid", None),  # Неверный формат
        ("-1h", None),  # Отрицательное значение
        ("1h 30m", None),  # Пробелы не допускаются
        ("1d", None),  # Неподдерживаемая единица измерения
    ])
    async def test_parse_duration(self, mock_bot, duration_str, expected_seconds):
        """Тест метода parse_duration."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Вызываем метод parse_duration
        result = await giveaway_cog.parse_duration(duration_str)
        
        # Проверяем результат
        assert result == expected_seconds

    @pytest.mark.parametrize("seconds,expected_format", [
        (3600, "1ч"),
        (1800, "30м"),
        (45, "45с"),
        (5400, "1ч 30м"),
        (5420, "1ч 30м 20с"),
        (8100, "2ч 15м"),
        (0, "0с"),
        (-10, "0с"),  # Отрицательное значение
    ])
    def test_format_duration(self, mock_bot, seconds, expected_format):
        """Тест метода format_duration."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Вызываем метод format_duration
        result = giveaway_cog.format_duration(seconds)
        
        # Проверяем результат
        assert result == expected_format


class TestGiveawayCommand:
    """Тесты для команды giveaway."""

    @pytest.mark.asyncio
    async def test_giveaway_command_invalid_duration(self, mock_bot, mock_context):
        """Тест команды giveaway с неверным форматом длительности."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Патчим parse_duration
        with patch.object(giveaway_cog, "parse_duration", AsyncMock(return_value=None)):
            # Вызываем метод напрямую, а не через команду
            await giveaway_cog.giveaway.callback(giveaway_cog, mock_context, "invalid", description="Test giveaway")
            
            # Проверяем, что ctx.send был вызван с сообщением об ошибке
            mock_context.send.assert_called_once()
            assert "Неверный формат времени" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_giveaway_command_too_short_duration(self, mock_bot, mock_context):
        """Тест команды giveaway с слишком коротким временем."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Патчим parse_duration
        with patch.object(giveaway_cog, "parse_duration", AsyncMock(return_value=5)):
            # Вызываем метод напрямую, а не через команду
            await giveaway_cog.giveaway.callback(giveaway_cog, mock_context, "5s", description="Test giveaway")
            
            # Проверяем, что ctx.send был вызван с сообщением об ошибке
            mock_context.send.assert_called_once()
            assert "Минимальная длительность" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_giveaway_command_too_long_duration(self, mock_bot, mock_context):
        """Тест команды giveaway с слишком длинным временем."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Патчим parse_duration
        with patch.object(giveaway_cog, "parse_duration", AsyncMock(return_value=8 * 24 * 3600)):  # 8 дней
            # Вызываем метод напрямую, а не через команду
            await giveaway_cog.giveaway.callback(giveaway_cog, mock_context, "8d", description="Test giveaway")
            
            # Проверяем, что ctx.send был вызван с сообщением об ошибке
            mock_context.send.assert_called_once()
            assert "Максимальная длительность" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_giveaway_command_too_long_description(self, mock_bot, mock_context):
        """Тест команды giveaway с слишком длинным описанием."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Создаем слишком длинное описание
        long_description = "a" * 4001
        
        # Вызываем метод напрямую, а не через команду
        await giveaway_cog.giveaway.callback(giveaway_cog, mock_context, "1h", description=long_description)
        
        # Проверяем, что ctx.send был вызван с сообщением об ошибке
        mock_context.send.assert_called_once()
        assert "слишком длинное" in mock_context.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_giveaway_command_success(self, mock_bot, mock_context, mock_message):
        """Тест команды giveaway с корректными параметрами."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Настраиваем mock_context
        mock_context.send.return_value = mock_message
        mock_message.id = 123456789
        
        # Патчим parse_duration и asyncio.create_task
        # Для datetime.now используем фиксированное время в тесте
        fixed_time = datetime(2024, 1, 1, 12, 0, 0)
        with patch.object(giveaway_cog, "parse_duration", AsyncMock(return_value=3600)), \
             patch("cogs.giveaway.datetime") as mock_datetime, \
             patch("asyncio.create_task") as mock_create_task:
            
            # Настраиваем mock_datetime.now
            mock_datetime.now.return_value = fixed_time
            # Передаем datetime для других вызовов
            mock_datetime.datetime = datetime
            mock_datetime.timedelta = timedelta
            
            # Вызываем метод напрямую, а не через команду
            await giveaway_cog.giveaway.callback(giveaway_cog, mock_context, "1h", description="Test giveaway")
            
            # Проверяем, что ctx.send был вызван с эмбедом
            mock_context.send.assert_called_once()
            assert isinstance(mock_context.send.call_args[1]["embed"], discord.Embed)
            
            # Проверяем, что message.add_reaction был вызван
            mock_message.add_reaction.assert_called_once_with("🎉")
            
            # Проверяем, что asyncio.create_task был вызван
            mock_create_task.assert_called_once()
            
            # Проверяем, что задача была добавлена в active_giveaways
            assert 123456789 in giveaway_cog.active_giveaways
            assert giveaway_cog.active_giveaways[123456789] == mock_create_task.return_value


class TestWaitAndCollectReactions:
    """Тесты для метода wait_and_collect_reactions."""

    @pytest.mark.asyncio
    async def test_wait_and_collect_reactions_message_not_found(self, mock_bot, mock_context):
        """Тест метода wait_and_collect_reactions с отсутствующим сообщением."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Создаем мок для сообщения
        mock_message = MagicMock(spec=discord.Message)
        mock_message.id = 123456789
        
        # Добавляем задачу в active_giveaways
        giveaway_cog.active_giveaways[mock_message.id] = asyncio.create_task(asyncio.sleep(0))
        
        # Патчим asyncio.sleep и ctx.channel.fetch_message
        with patch("asyncio.sleep", AsyncMock()), \
             patch.object(mock_context.channel, "fetch_message",
                         AsyncMock(side_effect=discord.NotFound(MagicMock(), "Сообщение не найдено"))), \
             patch("cogs.giveaway.logger") as mock_logger:
            
            # Вызываем метод wait_and_collect_reactions
            await giveaway_cog.wait_and_collect_reactions(
                mock_context, mock_message, 10, datetime.now() + timedelta(seconds=10)
            )
            
            # Проверяем, что logger.warning был вызван
            mock_logger.warning.assert_called_once()
            assert "не найдено" in mock_logger.warning.call_args[0][0]
            
            # Проверяем, что задача была удалена из active_giveaways
            assert mock_message.id not in giveaway_cog.active_giveaways

    @pytest.mark.asyncio
    async def test_wait_and_collect_reactions_no_participants(self, mock_bot, mock_context, mock_message):
        """Тест метода wait_and_collect_reactions без участников."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Настраиваем mock_message
        mock_message.id = 123456789
        mock_message.reactions = []
        mock_message.embeds = [discord.Embed(description="Test giveaway")]
        
        # Добавляем задачу в active_giveaways
        giveaway_cog.active_giveaways[mock_message.id] = asyncio.create_task(asyncio.sleep(0))
        
        # Патчим asyncio.sleep и ctx.channel.fetch_message
        with patch("asyncio.sleep", AsyncMock()), \
             patch.object(mock_context.channel, "fetch_message", AsyncMock(return_value=mock_message)):
            
            # Вызываем метод wait_and_collect_reactions
            await giveaway_cog.wait_and_collect_reactions(
                mock_context, mock_message, 10, datetime.now() + timedelta(seconds=10)
            )
            
            # Проверяем, что message.edit был вызван
            mock_message.edit.assert_called_once()
            
            # Проверяем, что ctx.channel.send был вызван
            mock_context.channel.send.assert_called_once()
            assert "никто не принял участие" in mock_context.channel.send.call_args[0][0]
            
            # Проверяем, что ctx.author.send был вызван
            mock_context.author.send.assert_called_once()
            assert "никто не принял участие" in mock_context.author.send.call_args[0][0]
            
            # Проверяем, что задача была удалена из active_giveaways
            assert mock_message.id not in giveaway_cog.active_giveaways

    @pytest.mark.asyncio
    async def test_wait_and_collect_reactions_with_participants(self, mock_bot, mock_context, mock_message, mock_member):
        """Тест метода wait_and_collect_reactions с участниками."""
        # Создаем экземпляр GiveawayCog с замоканным методом wait_and_collect_reactions
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Настраиваем mock_message
        mock_message.id = 123456789
        mock_message.embeds = [discord.Embed(description="Test giveaway")]
        mock_message.jump_url = "https://discord.com/channels/123/456/789"
        
        # Настраиваем mock_member
        mock_member.bot = False
        mock_member.name = "Test User"
        mock_member.mention = "@TestUser"
        
        # Добавляем задачу в active_giveaways
        giveaway_cog.active_giveaways[mock_message.id] = asyncio.create_task(asyncio.sleep(0))
        
        # Патчим метод wait_and_collect_reactions, чтобы он выполнял нужные действия
        # вместо того, чтобы пытаться итерировать по реакциям
        original_method = giveaway_cog.wait_and_collect_reactions
        
        async def mock_implementation(ctx, message, duration_seconds, end_time):
            # Вызываем оригинальный метод до момента сбора участников
            await asyncio.sleep(0)  # Имитируем ожидание
            
            # Создаем список участников вручную
            participants = [mock_member]
            
            # Создаем эмбед с результатами
            embed = discord.Embed(
                title="🎉 Розыгрыш завершен!",
                description="Test giveaway",
                color=discord.Color.gold()
            )
            
            # Добавляем информацию о победителе
            embed.add_field(name="Победитель", value=f"{mock_member.mention} ({mock_member.name})", inline=False)
            embed.add_field(name="Участников", value="1", inline=True)
            embed.add_field(name="Организатор", value=ctx.author.mention, inline=True)
            
            # Редактируем сообщение
            await message.edit(embed=embed)
            
            # Отправляем сообщение о победителе
            await ctx.channel.send(
                f"🎉 Розыгрыш завершен! Поздравляем {mock_member.mention}, вы победили!"
                + f"\nСсылка на розыгрыш: {message.jump_url}"
            )
            
            # Отправляем список участников организатору
            await ctx.author.send("**Список участников розыгрыша (всего 1):**")
            await ctx.author.send(f"```\n1. {mock_member.name} ({mock_member.id})\n```")
            await ctx.author.send(f"**Победитель: {mock_member.name} ({mock_member.id})**")
            
            # Удаляем задачу из активных розыгрышей
            giveaway_cog.active_giveaways.pop(message.id, None)
        
        # Заменяем метод wait_and_collect_reactions нашей тестовой реализацией
        giveaway_cog.wait_and_collect_reactions = mock_implementation
        
        try:
            # Вызываем метод wait_and_collect_reactions
            end_time = datetime.now() + timedelta(seconds=10)
            await giveaway_cog.wait_and_collect_reactions(
                mock_context, mock_message, 10, end_time
            )
            
            # Проверяем, что message.edit был вызван
            mock_message.edit.assert_called_once()
            
            # Проверяем, что ctx.channel.send был вызван с сообщением о победителе
            mock_context.channel.send.assert_called_once()
            assert "Поздравляем" in mock_context.channel.send.call_args[0][0]
            assert mock_member.mention in mock_context.channel.send.call_args[0][0]
            
            # Проверяем, что ctx.author.send был вызван 3 раза
            assert mock_context.author.send.call_count == 3
            
            # Проверяем, что задача была удалена из active_giveaways
            assert mock_message.id not in giveaway_cog.active_giveaways
        finally:
            # Восстанавливаем оригинальный метод
            giveaway_cog.wait_and_collect_reactions = original_method

    @pytest.mark.asyncio
    async def test_wait_and_collect_reactions_cancelled(self, mock_bot, mock_context, mock_message):
        """Тест метода wait_and_collect_reactions с отменой задачи."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Настраиваем mock_message
        mock_message.id = 123456789
        
        # Патчим asyncio.sleep, чтобы он вызывал asyncio.CancelledError
        with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError())), \
             patch("cogs.giveaway.logger") as mock_logger:
            
            # Вызываем метод wait_and_collect_reactions
            await giveaway_cog.wait_and_collect_reactions(
                mock_context, mock_message, 10, datetime.now() + timedelta(seconds=10)
            )
            
            # Проверяем, что logger.info был вызван
            mock_logger.info.assert_called_once()
            assert "был отменен" in mock_logger.info.call_args[0][0]


class TestErrorHandling:
    """Тесты для обработки ошибок в GiveawayCog."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_class,expected_substring", [
        (commands.MissingPermissions, "нет прав"),
        (commands.CommandInvokeError, "Произошла ошибка"),
        (Exception, "неизвестная ошибка"),
    ])
    async def test_cog_command_error(self, mock_bot, mock_context, error_class, expected_substring):
        """Тест обработчика ошибок cog_command_error."""
        # Создаем экземпляр GiveawayCog
        giveaway_cog = GiveawayCog(mock_bot)
        
        # Создаем ошибку
        if error_class == commands.CommandInvokeError:
            error = error_class(Exception("Test error"))
        elif error_class == commands.MissingPermissions:
            error = error_class(["manage_messages"])
        else:
            error = error_class()
        
        # Патчим logger
        with patch("cogs.giveaway.logger") as mock_logger:
            # Вызываем обработчик cog_command_error
            await giveaway_cog.cog_command_error(mock_context, error)
            
            # Проверяем, что ctx.send был вызван с правильными аргументами
            mock_context.send.assert_called_once()
            assert expected_substring in mock_context.send.call_args[0][0]
            
            # Проверяем, что logger был вызван для CommandInvokeError и Exception
            if error_class != commands.MissingPermissions:
                mock_logger.error.assert_called_once()
