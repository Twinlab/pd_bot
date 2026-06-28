"""Тесты для кога RoleReactionCog (роли через persistent-кнопки)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from cogs.role_reaction import RoleReactionCog
from utils.role_reaction_data_manager import RoleReactionDataManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.name = "Test Guild"
    guild.get_role = MagicMock()
    guild.get_channel = MagicMock()
    guild.fetch_member = AsyncMock()
    guild.get_member = MagicMock()
    return guild


@pytest.fixture
def mock_role():
    role = MagicMock(spec=discord.Role)
    role.id = 101
    role.name = "Test Role"
    role.mention = "<@&101>"
    return role


@pytest.fixture
def mock_member():
    member = MagicMock(spec=discord.Member)
    member.id = 201
    member.name = "TestUser"
    member.display_name = "TestUser"
    member.bot = False
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


@pytest.fixture
def mock_text_channel(mock_guild: discord.Guild):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 301
    channel.name = "test-channel"
    channel.guild = mock_guild
    channel.send = AsyncMock()
    channel.fetch_message = AsyncMock()
    return channel


@pytest.fixture
def mock_message(mock_text_channel: discord.TextChannel, mock_guild: discord.Guild):
    message = MagicMock(spec=discord.Message)
    message.id = 401
    message.channel = mock_text_channel
    message.guild = mock_guild
    message.edit = AsyncMock()
    return message


@pytest.fixture
def mock_interaction(
    mock_guild: discord.Guild,
    mock_member: discord.Member,
    mock_text_channel: discord.TextChannel,
):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_guild
    interaction.guild_id = mock_guild.id
    interaction.user = mock_member
    interaction.channel = mock_text_channel
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    return interaction


@pytest.fixture
@patch("utils.role_reaction_data_manager.RoleReactionDataManager", spec=RoleReactionDataManager)
def mock_data_manager(MockDataManager):
    manager = MockDataManager.return_value
    manager.get_message_info = AsyncMock(return_value=None)
    manager.add_role_reaction = AsyncMock(return_value=True)
    manager.remove_role_reaction = AsyncMock(return_value=True)
    manager.get_role_by_emoji = AsyncMock(return_value=None)
    manager.get_all_role_reactions = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def role_reaction_cog(mock_bot: commands.Bot, mock_data_manager: RoleReactionDataManager):
    with patch("cogs.role_reaction.RoleReactionDataManager", return_value=mock_data_manager):
        cog = RoleReactionCog(mock_bot)
        assert cog.data_manager is mock_data_manager
        return cog


@pytest.fixture
def mock_ctx(
    mock_guild: discord.Guild,
    mock_member: discord.Member,
    mock_text_channel: discord.TextChannel,
    mock_bot: commands.Bot,
):
    """Фикстура для мока контекста команды."""
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.channel = mock_text_channel
    ctx.bot = mock_bot
    ctx.author = mock_member
    ctx.send = AsyncMock()
    ctx.command = MagicMock(name="test_command")
    return ctx


class TestRoleReactionCogInitAndLoad:
    def test_init(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_data_manager: RoleReactionDataManager,
    ):
        assert role_reaction_cog.bot == mock_bot
        assert role_reaction_cog.data_manager == mock_data_manager
        assert isinstance(role_reaction_cog.message_cache, dict)
        assert not role_reaction_cog.message_cache

    @pytest.mark.asyncio
    async def test_cog_load_registers_buttons(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot
    ):
        """cog_load только регистрирует persistent-кнопки (кеш грузится в on_ready)."""
        from utils.role_reaction_views import RoleButton

        role_reaction_cog.load_message_cache = AsyncMock()
        await role_reaction_cog.cog_load()
        mock_bot.add_dynamic_items.assert_called_once_with(RoleButton)
        role_reaction_cog.load_message_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_ready_migrates_once(self, role_reaction_cog: RoleReactionCog):
        """on_ready грузит кеш и перерисовывает сообщение ровно один раз за процесс."""
        role_reaction_cog.load_message_cache = AsyncMock()
        role_reaction_cog.update_reaction_message = AsyncMock()
        role_reaction_cog.message_cache = {123: (1, 2)}

        await role_reaction_cog.on_ready()
        await role_reaction_cog.on_ready()  # повторный реконнект не должен мигрировать снова

        role_reaction_cog.load_message_cache.assert_called_once()
        role_reaction_cog.update_reaction_message.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_load_message_cache_empty(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_data_manager: RoleReactionDataManager,
    ):
        mock_bot.guilds = []
        await role_reaction_cog.load_message_cache()
        mock_data_manager.get_message_info.assert_not_called()
        assert not role_reaction_cog.message_cache

    @pytest.mark.asyncio
    async def test_load_message_cache_with_data(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_data_manager: RoleReactionDataManager,
    ):
        mock_bot.guilds = [mock_guild]
        mock_data_manager.get_message_info.return_value = (123, 456)
        await role_reaction_cog.load_message_cache()
        mock_data_manager.get_message_info.assert_called_once_with(mock_guild.id)
        assert role_reaction_cog.message_cache[mock_guild.id] == (123, 456)


class TestSetupRoleMessageCommand:
    @pytest.mark.asyncio
    async def test_setup_role_message_success_current_channel(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager,
        mock_text_channel: discord.TextChannel,
        mock_message: discord.Message,
        mock_guild: discord.Guild,
        mock_member: discord.Member,
        mock_ctx: commands.Context,
    ):
        mock_text_channel.send = AsyncMock(return_value=mock_message)
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = mock_text_channel

        def get_channel_side_effect_current(id_to_get):
            if id_to_get == mock_text_channel.id:
                return None
            return MagicMock(spec=discord.TextChannel)

        role_reaction_cog.bot.get_channel = MagicMock(side_effect=get_channel_side_effect_current)

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)

            mock_text_channel.send.assert_called_once_with("Нужна роль? Нажми на кнопку ниже.")
            mock_data_manager.add_role_reaction.assert_called_once_with(
                mock_guild.id,
                mock_text_channel.id,
                mock_message.id,
                "✅",
                0,
                "Системная запись - не удалять",
            )
            assert role_reaction_cog.message_cache[mock_guild.id] == (
                mock_text_channel.id,
                mock_message.id,
            )
            mock_safe_send.assert_called_once()
            assert (
                f"Сообщение для получения ролей создано в канале <#{mock_text_channel.id}>"
                in mock_safe_send.call_args[0][1]
            )

    @pytest.mark.asyncio
    async def test_setup_role_message_already_exists(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager,
        mock_guild: discord.Guild,
        mock_member: discord.Member,
        mock_ctx: commands.Context,
    ):
        existing_channel_id = 123
        mock_data_manager.get_message_info.return_value = (existing_channel_id, 456)

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)
            mock_safe_send.assert_called_once()
            assert (
                f"Сообщение с реакциями уже существует в канале <#{existing_channel_id}>"
                in mock_safe_send.call_args[0][1]
            )
            mock_data_manager.add_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_role_message_discord_forbidden(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager,
        mock_text_channel: discord.TextChannel,
        mock_guild: discord.Guild,
        mock_member: discord.Member,
        mock_ctx: commands.Context,
    ):
        mock_text_channel.send = AsyncMock(
            side_effect=discord.Forbidden(MagicMock(), "Cannot send messages")
        )
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = mock_text_channel

        def get_channel_side_effect_forbidden(id_to_get):
            if id_to_get == mock_text_channel.id:
                return None
            return MagicMock(spec=discord.TextChannel)

        role_reaction_cog.bot.get_channel = MagicMock(side_effect=get_channel_side_effect_forbidden)

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)
            mock_safe_send.assert_called_once_with(
                mock_ctx,
                "У бота нет прав для отправки сообщений в указанный канал.",
                ephemeral=True,
            )


class TestRoleAssignCommand:
    @pytest.mark.asyncio
    async def test_role_assign_message_not_setup(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
        mock_role: discord.Role,
    ):
        mock_data_manager.get_message_info.return_value = None
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test Role"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Сообщение с реакциями не найдено."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )
        mock_data_manager.add_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_assign_success_standard_emoji(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
        mock_role: discord.Role,
        mock_guild: discord.Guild,
    ):
        channel_id, message_id = 123, 456
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog,
            mock_interaction,
            role=mock_role,
            emoji="👍",
            description="Get Test Role",
        )
        mock_data_manager.add_role_reaction.assert_called_once_with(
            mock_guild.id, channel_id, message_id, "👍", mock_role.id, "Get Test Role"
        )
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)
        mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_role_assign_success_custom_emoji(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
        mock_role: discord.Role,
        mock_guild: discord.Guild,
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog,
            mock_interaction,
            role=mock_role,
            emoji="<:custom_emoji:789>",
            description="Custom Emoji Role",
        )
        mock_data_manager.add_role_reaction.assert_called_once_with(
            mock_guild.id, 123, 456, "custom_emoji:789", mock_role.id, "Custom Emoji Role"
        )
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)

    @pytest.mark.asyncio
    async def test_role_assign_add_fails(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
        mock_role: discord.Role,
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.add_role_reaction.return_value = False
        role_reaction_cog.update_reaction_message = AsyncMock()
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Не удалось добавить привязку роли."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )
        role_reaction_cog.update_reaction_message.assert_not_called()


class TestRoleRemoveCommand:
    @pytest.mark.asyncio
    async def test_role_remove_message_not_setup(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
    ):
        mock_data_manager.get_message_info.return_value = None
        await role_reaction_cog.role_remove.callback(
            role_reaction_cog, mock_interaction, emoji="👍"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Сообщение с реакциями не найдено."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )
        mock_data_manager.remove_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_remove_success(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
        mock_guild: discord.Guild,
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.remove_role_reaction.return_value = True
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        await role_reaction_cog.role_remove.callback(
            role_reaction_cog, mock_interaction, emoji="👍"
        )
        mock_data_manager.remove_role_reaction.assert_called_once_with(mock_guild.id, "👍")
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)
        mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_role_remove_not_found(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager,
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.remove_role_reaction.return_value = False
        role_reaction_cog.update_reaction_message = AsyncMock()
        await role_reaction_cog.role_remove.callback(
            role_reaction_cog, mock_interaction, emoji="🤔"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert (
            "Не найдена привязка роли к эмодзи 🤔."
            in mock_interaction.response.send_message.call_args.kwargs["embed"].description
        )
        role_reaction_cog.update_reaction_message.assert_not_called()


class TestUpdateReactionMessage:
    @pytest.mark.asyncio
    async def test_no_cache(self, role_reaction_cog: RoleReactionCog, mock_guild: discord.Guild):
        role_reaction_cog.message_cache = {}
        result = await role_reaction_cog.update_reaction_message(mock_guild.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_success_attaches_buttons(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
        mock_message: discord.Message,
        mock_role: discord.Role,
        mock_data_manager: RoleReactionDataManager,
        mock_bot: commands.Bot,
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = mock_role
        mock_data_manager.get_all_role_reactions.return_value = [
            {"emoji": "👍", "role_id": mock_role.id, "description": "Лайк"},
            {"emoji": "🎉", "role_id": 0, "description": "Системная"},
        ]

        result = await role_reaction_cog.update_reaction_message(mock_guild.id)

        assert result is True
        mock_message.edit.assert_called_once()
        kwargs = mock_message.edit.call_args.kwargs
        assert "Нужна роль? Нажми на кнопку ниже." in kwargs["content"]
        assert f"👍 — {mock_role.mention}: Лайк" in kwargs["content"]
        assert "🎉" not in kwargs["content"]  # системная запись не показывается
        view = kwargs["view"]
        assert [c.custom_id for c in view.children] == [f"rr:role:{mock_role.id}"]

    @pytest.mark.asyncio
    async def test_role_not_found_in_guild_skipped(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
        mock_message: discord.Message,
        mock_data_manager: RoleReactionDataManager,
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = None
        mock_data_manager.get_all_role_reactions.return_value = [
            {"emoji": "👍", "role_id": 101, "description": "Лайк"}
        ]

        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)

            assert result is True
            mock_logger_warning.assert_called_once_with(
                f"Не найдена роль с ID 101 на сервере {mock_guild.id}"
            )
            kwargs = mock_message.edit.call_args.kwargs
            assert "👍" not in kwargs["content"]
            assert len(kwargs["view"].children) == 0

    @pytest.mark.asyncio
    async def test_guild_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (123, 456)
        mock_bot.get_guild.return_value = None
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(f"Не найден сервер с ID {mock_guild.id}")

    @pytest.mark.asyncio
    async def test_channel_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild
    ):
        channel_id, message_id = 123, 456
        role_reaction_cog.message_cache[mock_guild.id] = (channel_id, message_id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = None
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(
                f"Не найден канал с ID {channel_id} на сервере {mock_guild.id}"
            )

    @pytest.mark.asyncio
    async def test_message_not_found(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
    ):
        message_id = 456
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, message_id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.side_effect = discord.NotFound(
            MagicMock(), "Message not found"
        )
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(
                f"Не найдено сообщение с ID {message_id} в канале {mock_text_channel.id}"
            )

    @pytest.mark.asyncio
    async def test_edit_exception(
        self,
        role_reaction_cog: RoleReactionCog,
        mock_bot: commands.Bot,
        mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel,
        mock_message: discord.Message,
        mock_data_manager: RoleReactionDataManager,
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_message.edit.side_effect = discord.HTTPException(MagicMock(), "Edit failed")
        mock_data_manager.get_all_role_reactions.return_value = []

        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_error.assert_called_once()
            assert "Ошибка при обновлении ролевого сообщения" in mock_logger_error.call_args[0][0]


@pytest.mark.asyncio
async def test_setup_function(mock_bot: commands.Bot):
    from cogs.role_reaction import setup as setup_cog

    mock_bot.add_cog = AsyncMock()
    with patch("cogs.role_reaction.logger.info") as mock_logger_info:
        await setup_cog(mock_bot)
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], RoleReactionCog)
        mock_logger_info.assert_called_once_with("Ког RoleReactionCog успешно загружен.")
