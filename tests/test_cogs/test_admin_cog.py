"""Тесты для кога AdminCog."""

import asyncio
import datetime
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.admin import AdminCog # Предполагаем, что AdminCog находится в cogs.admin

# Устанавливаем уровень логгирования для тестов
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_guild():
    """Фикстура для мока гильдии."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.name = "Test Guild"
    guild.owner_id = 999 # ID владельца сервера
    guild.me = MagicMock(spec=discord.Member) # Мок для bot.guild.me
    guild.me.top_role = MagicMock(spec=discord.Role, position=5)
    return guild

@pytest.fixture
def mock_author(mock_guild: discord.Guild):
    """Фикстура для мока автора команды (администратора)."""
    author = MagicMock(spec=discord.Member)
    author.id = 100
    author.name = "TestAdmin"
    author.guild = mock_guild
    author.top_role = MagicMock(spec=discord.Role, position=10) # Роль выше, чем у бота и обычного юзера
    author.guild_permissions = MagicMock(manage_messages=True, kick_members=True)
    return author

@pytest.fixture
def mock_member_to_kick(mock_guild: discord.Guild):
    """Фикстура для мока участника, которого будут кикать."""
    member = MagicMock(spec=discord.Member)
    member.id = 200
    member.name = "UserToKick"
    member.mention = "<@200>"
    member.guild = mock_guild
    member.top_role = MagicMock(spec=discord.Role, position=3) # Роль ниже, чем у админа и бота
    member.send = AsyncMock()
    member.kick = AsyncMock()
    return member


@pytest.fixture
def mock_text_channel(mock_guild: discord.Guild):
    """Фикстура для мока текстового канала."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.name = "general"
    channel.guild = mock_guild
    channel.history = AsyncMock()
    channel.delete_messages = AsyncMock()
    channel.send = AsyncMock()
    return channel

@pytest.fixture
def mock_context(mock_bot: commands.Bot, mock_guild: discord.Guild, mock_author: discord.Member, mock_text_channel: discord.TextChannel):
    """Фикстура для мока контекста команды."""
    ctx = MagicMock(spec=commands.Context)
    ctx.bot = mock_bot
    ctx.guild = mock_guild
    ctx.author = mock_author
    ctx.channel = mock_text_channel
    ctx.send = AsyncMock()
    ctx.defer = AsyncMock()
    # Для гибридных команд
    ctx.interaction = None # По умолчанию нет взаимодействия (префиксная команда)
    ctx.command = MagicMock(name="test_command") # Для error_handler
    return ctx

@pytest.fixture
def mock_interaction_context(mock_context: commands.Context):
    """Фикстура для мока контекста с взаимодействием (slash-команда)."""
    mock_context.interaction = AsyncMock(spec=discord.Interaction)
    mock_context.interaction.followup = AsyncMock(spec=discord.Webhook)
    mock_context.interaction.followup.send = AsyncMock()
    mock_context.interaction.edit_original_response = AsyncMock()
    return mock_context


@pytest.fixture
def admin_cog(mock_bot: commands.Bot):
    """Фикстура для создания экземпляра AdminCog."""
    return AdminCog(mock_bot)


class TestAdminCogInit:
    """Тесты для инициализации AdminCog."""

    def test_init(self, admin_cog: AdminCog, mock_bot: commands.Bot):
        """Тест инициализации кога."""
        assert admin_cog.bot == mock_bot
        assert isinstance(admin_cog.recent_purges, dict)
        assert not admin_cog.recent_purges


class TestClearCommand:
    """Тесты для команды clear."""

    @pytest.mark.asyncio
    async def test_clear_invalid_count_too_low(self, admin_cog: AdminCog, mock_context: commands.Context):
        """Тест clear с количеством сообщений меньше 1."""
        # Мокаем safe_send, так как он используется внутри команды
        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.clear.callback(admin_cog, mock_context, count=0)
            mock_safe_send.assert_called_once_with(mock_context, "Количество сообщений должно быть от 1 до 100.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_clear_invalid_count_too_high(self, admin_cog: AdminCog, mock_context: commands.Context):
        """Тест clear с количеством сообщений больше 100."""
        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.clear.callback(admin_cog, mock_context, count=101)
            mock_safe_send.assert_called_once_with(mock_context, "Количество сообщений должно быть от 1 до 100.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_clear_spam_protection(self, admin_cog: AdminCog, mock_context: commands.Context):
        """Тест защиты от спама команды clear."""
        channel_id = mock_context.channel.id
        admin_cog.recent_purges[channel_id] = (time.monotonic() - 5, 15) # 5 секунд назад, 15 сообщений

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.clear.callback(admin_cog, mock_context, count=20) # Пытаемся удалить > 10
            mock_safe_send.assert_called_once()
            assert "Вы недавно удалили 15 сообщений." in mock_safe_send.call_args[0][1] # Второй аргумент safe_send

    @pytest.mark.asyncio
    async def test_clear_spam_protection_allows_small_purge(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест, что защита от спама позволяет небольшую очистку."""
        channel_id = mock_context.channel.id
        admin_cog.recent_purges[channel_id] = (time.monotonic() - 5, 15)
        admin_cog._clear_messages_helper = AsyncMock(return_value=5) # Мокаем хелпер

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            # Вызываем clear.callback только один раз внутри patch
            await admin_cog.clear.callback(admin_cog, mock_context, count=5)
            admin_cog._clear_messages_helper.assert_called_once_with(mock_context, count=5, user=None)
            mock_safe_send.assert_called_once_with(mock_context, "Удалено 5 сообщений.", ephemeral=False, delete_after=5)


    @pytest.mark.asyncio
    async def test_clear_successful_prefix_command(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест успешного выполнения clear как префиксной команды."""
        admin_cog._clear_messages_helper = AsyncMock(return_value=10)
        mock_context.interaction = None # Убедимся, что это префиксная команда

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.clear.callback(admin_cog, mock_context, count=10, user=None)

            admin_cog._clear_messages_helper.assert_called_once_with(mock_context, count=10, user=None)
            mock_safe_send.assert_called_once_with(mock_context, "Удалено 10 сообщений.", ephemeral=False, delete_after=5)
            assert mock_context.channel.id in admin_cog.recent_purges
            assert admin_cog.recent_purges[mock_context.channel.id][1] == 10

    @pytest.mark.asyncio
    async def test_clear_successful_slash_command(self, admin_cog: AdminCog, mock_interaction_context: commands.Context):
        """Тест успешного выполнения clear как slash-команды."""
        admin_cog._clear_messages_helper = AsyncMock(return_value=5)

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            # Вызываем clear.callback только один раз внутри patch
            await admin_cog.clear.callback(admin_cog, mock_interaction_context, count=5, user=None)

            mock_interaction_context.defer.assert_called_once_with(ephemeral=True)
            admin_cog._clear_messages_helper.assert_called_once_with(mock_interaction_context, count=5, user=None)
            mock_safe_send.assert_called_once_with(mock_interaction_context, "Удалено 5 сообщений.", ephemeral=True, delete_after=None)

    @pytest.mark.asyncio
    async def test_clear_with_user_filter(self, admin_cog: AdminCog, mock_context: commands.Context, mock_member_to_kick: discord.Member):
        """Тест clear с фильтром по пользователю."""
        admin_cog._clear_messages_helper = AsyncMock(return_value=3)

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            # Вызываем clear.callback только один раз внутри patch
            await admin_cog.clear.callback(admin_cog, mock_context, count=5, user=mock_member_to_kick)

            admin_cog._clear_messages_helper.assert_called_once_with(mock_context, count=5, user=mock_member_to_kick)
            expected_message = f"Удалено 3 сообщений пользователя {mock_member_to_kick.display_name}."
            mock_safe_send.assert_called_once_with(mock_context, expected_message, ephemeral=False, delete_after=5)

    # Тесты для _clear_messages_helper
    @pytest.mark.asyncio
    async def test_clear_messages_helper_no_messages_to_delete(self, admin_cog: AdminCog, mock_context: commands.Context):
        """Тест _clear_messages_helper, когда нет сообщений для удаления."""
        mock_context.channel.history = MagicMock() # history - обычный метод
        mock_context.channel.history.return_value = mock_history_iterator([])
        deleted_count = await admin_cog._clear_messages_helper(mock_context, 5)
        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_clear_messages_helper_only_recent_messages(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест _clear_messages_helper только с новыми сообщениями."""
        now = datetime.datetime.now(datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_msg1 = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(hours=1))
        recent_msg2 = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(hours=2))
        messages = [recent_msg1, recent_msg2]
        mock_context.channel.history = MagicMock()
        mock_context.channel.history.return_value = mock_history_iterator(messages)
        mock_context.channel.delete_messages = AsyncMock() # Успешное массовое удаление

        deleted_count = await admin_cog._clear_messages_helper(mock_context, 2)

        assert deleted_count == 2
        mock_context.channel.delete_messages.assert_called_once_with(messages)


    @pytest.mark.asyncio
    async def test_clear_messages_helper_only_old_messages(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест _clear_messages_helper только со старыми сообщениями."""
        old_msg1 = MagicMock(spec=discord.Message, created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=20))
        old_msg1.delete = AsyncMock()
        old_msg2 = MagicMock(spec=discord.Message, created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=21))
        old_msg2.delete = AsyncMock()
        messages = [old_msg1, old_msg2]
        mock_context.channel.history = MagicMock()
        mock_context.channel.history.return_value = mock_history_iterator(messages)
        mock_context.channel.delete_messages = AsyncMock() # Добавляем мок, чтобы не было AttributeError

        deleted_count = await admin_cog._clear_messages_helper(mock_context, 2)

        assert deleted_count == 2
        old_msg1.delete.assert_called_once()
        old_msg2.delete.assert_called_once()
        mock_context.channel.delete_messages.assert_not_called() # Массовое не должно вызываться

    @pytest.mark.asyncio
    async def test_clear_messages_helper_mixed_messages(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест _clear_messages_helper со смешанными (новыми и старыми) сообщениями."""
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_msg = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(hours=1))
        old_msg = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(days=20))
        old_msg.delete = AsyncMock()
        messages = [recent_msg, old_msg] # Порядок важен для history
        mock_context.channel.history = MagicMock()
        mock_context.channel.history.return_value = mock_history_iterator(messages)
        mock_context.channel.delete_messages = AsyncMock()

        deleted_count = await admin_cog._clear_messages_helper(mock_context, 2)

        assert deleted_count == 2
        mock_context.channel.delete_messages.assert_called_once_with([recent_msg])
        old_msg.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_messages_helper_bulk_delete_fails_fallback(self, admin_cog: AdminCog, mock_context: commands.Context, mock_text_channel: discord.TextChannel):
        """Тест _clear_messages_helper, когда массовое удаление падает, и происходит откат к поштучному."""
        now = datetime.datetime.now(datetime.timezone.utc)
        recent_msg1 = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(hours=1))
        recent_msg1.delete = AsyncMock()
        recent_msg2 = MagicMock(spec=discord.Message, created_at=now - datetime.timedelta(hours=2))
        recent_msg2.delete = AsyncMock()
        messages = [recent_msg1, recent_msg2]
        mock_context.channel.history = MagicMock()
        mock_context.channel.history.return_value = mock_history_iterator(messages)
        mock_context.channel.delete_messages = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "Bulk delete failed"))

        deleted_count = await admin_cog._clear_messages_helper(mock_context, 2)
        assert deleted_count == 2
        recent_msg1.delete.assert_called_once()
        recent_msg2.delete.assert_called_once()

# Вспомогательная функция для создания асинхронного итератора
def mock_history_iterator(items):
    async def iterator():
        for item in items:
            yield item
    return iterator()


class TestKickCommand:
    """Тесты для команды kick."""

    @pytest.mark.asyncio
    async def test_kick_successful(self, admin_cog: AdminCog, mock_context: commands.Context, mock_member_to_kick: discord.Member):
        """Тест успешного кика пользователя."""
        mock_context.command = MagicMock(name="kick") # Для error_handler
        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.kick.callback(admin_cog, mock_context, member=mock_member_to_kick, reason="Test reason")

            mock_member_to_kick.send.assert_called_once_with(f"Вы были кикнуты с сервера **{mock_context.guild.name}**. Причина: Test reason")
            mock_member_to_kick.kick.assert_called_once_with(reason=f"Кикнут {mock_context.author.name}: Test reason")
            mock_safe_send.assert_called_once_with(mock_context, f"Пользователь {mock_member_to_kick.mention} ({mock_member_to_kick.name}) был кикнут. Причина: Test reason")

    @pytest.mark.asyncio
    async def test_kick_higher_role_author(self, admin_cog: AdminCog, mock_context: commands.Context, mock_member_to_kick: discord.Member):
        """Тест попытки кика пользователя с более высокой ролью, чем у автора команды."""
        mock_context.command = MagicMock(name="kick")
        # Устанавливаем позиции ролей так, чтобы роль участника была выше
        mock_context.author.top_role = MagicMock(position=5)
        mock_member_to_kick.top_role = MagicMock(position=6)


        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.kick.callback(admin_cog, mock_context, member=mock_member_to_kick, reason="Test")
            mock_safe_send.assert_called_once_with(mock_context, "Вы не можете кикнуть участника с равной или более высокой ролью.", ephemeral=True)
            mock_member_to_kick.kick.assert_not_called()

    @pytest.mark.asyncio
    async def test_kick_higher_role_bot(self, admin_cog: AdminCog, mock_context: commands.Context, mock_member_to_kick: discord.Member):
        """Тест попытки кика пользователя с более высокой ролью, чем у бота."""
        mock_context.command = MagicMock(name="kick")
        # Устанавливаем позиции ролей так, чтобы роль участника была выше роли бота
        mock_context.guild.me.top_role = MagicMock(position=2)
        mock_member_to_kick.top_role = MagicMock(position=3)
        mock_context.author.top_role = MagicMock(position=5) # Роль автора выше их обоих

        with patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.kick.callback(admin_cog, mock_context, member=mock_member_to_kick, reason="Test")
            mock_safe_send.assert_called_once_with(mock_context, "У бота недостаточно прав для кика этого участника.", ephemeral=True)
            mock_member_to_kick.kick.assert_not_called()

    @pytest.mark.asyncio
    async def test_kick_dm_forbidden(self, admin_cog: AdminCog, mock_context: commands.Context, mock_member_to_kick: discord.Member):
        """Тест кика, когда отправка DM пользователю запрещена."""
        mock_context.command = MagicMock(name="kick")
        mock_member_to_kick.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "DM forbidden"))
        # Убедимся, что роли настроены корректно для успешного кика (если бы не ошибка DM)
        mock_context.author.top_role = MagicMock(position=10)
        mock_context.guild.me.top_role = MagicMock(position=5)
        mock_member_to_kick.top_role = MagicMock(position=3)


        with patch("cogs.admin.logger.warning") as mock_logger_warning, \
             patch("cogs.admin.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await admin_cog.kick.callback(admin_cog, mock_context, member=mock_member_to_kick, reason="Test reason")

            mock_member_to_kick.kick.assert_called_once() # Кик все равно должен произойти
            mock_logger_warning.assert_called_once()
            assert f"Не удалось отправить DM пользователю {mock_member_to_kick}" in mock_logger_warning.call_args[0][0]
            mock_safe_send.assert_called_once() # Сообщение в канал о кике


class TestRestartCommand:
    """Тесты для команды restart."""

    def test_restart_is_hidden_from_regular_members(self, admin_cog: AdminCog) -> None:
        permissions = admin_cog.restart.app_command.default_permissions

        assert permissions is not None
        assert permissions.administrator is True
        assert admin_cog.restart.app_command.guild_only is True

    @pytest.mark.asyncio
    async def test_restart_successful_prefix(self, admin_cog: AdminCog, mock_context: commands.Context, mock_bot: commands.Bot):
        """Тест успешного перезапуска как префиксной команды."""
        mock_bot.close = AsyncMock()
        mock_context.interaction = None # Префиксная команда
        
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await admin_cog.restart.callback(admin_cog, mock_context)

        mock_context.send.assert_called_once_with("🔄 Перезапуск бота...")
        mock_bot.close.assert_called_once()


    @pytest.mark.asyncio
    async def test_restart_successful_slash(self, admin_cog: AdminCog, mock_interaction_context: commands.Context, mock_bot: commands.Bot):
        """Тест успешного перезапуска как slash-команды."""
        mock_bot.close = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await admin_cog.restart.callback(admin_cog, mock_interaction_context)

        mock_interaction_context.defer.assert_called_once_with(ephemeral=True)
        mock_interaction_context.interaction.followup.send.assert_called_once_with("🔄 Перезапуск бота...", ephemeral=True)
        mock_bot.close.assert_called_once()


# Локальный cog_command_error удалён — обработка ошибок централизована
# в handlers/events.py (`on_command_error`).


@pytest.mark.asyncio
async def test_setup_function(mock_bot: commands.Bot):
    """Тест функции setup."""
    from cogs.admin import setup as setup_admin_cog # Импортируем setup из модуля кога

    mock_bot.add_cog = AsyncMock()
    with patch("cogs.admin.logger.info") as mock_logger_info:
        await setup_admin_cog(mock_bot)
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], AdminCog)
        mock_logger_info.assert_called_once_with("Ког AdminCog успешно загружен.")
