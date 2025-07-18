"""Тесты для кога RoleReactionCog."""

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
    message.add_reaction = AsyncMock()
    message.reactions = []
    return message

@pytest.fixture
def mock_interaction(mock_guild: discord.Guild, mock_member: discord.Member, mock_text_channel: discord.TextChannel):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_guild
    interaction.guild_id = mock_guild.id
    interaction.user = mock_member
    interaction.channel = mock_text_channel
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.response.send_message = AsyncMock()
    return interaction

@pytest.fixture
def mock_raw_reaction_payload(mock_guild: discord.Guild, mock_member: discord.Member, mock_text_channel: discord.TextChannel, mock_message: discord.Message):
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.message_id = mock_message.id
    payload.user_id = mock_member.id
    payload.channel_id = mock_text_channel.id
    payload.guild_id = mock_guild.id
    payload.member = mock_member 
    payload.emoji = MagicMock(spec=discord.PartialEmoji)
    payload.emoji.name = "👍"
    payload.emoji.id = None
    return payload

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
def mock_ctx(mock_guild: discord.Guild, mock_member: discord.Member, mock_text_channel: discord.TextChannel, mock_bot: commands.Bot):
    """Фикстура для мока контекста команды."""
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.channel = mock_text_channel
    ctx.bot = mock_bot
    ctx.author = mock_member
    ctx.send = AsyncMock()
    ctx.command = MagicMock(name="test_command") # Для cog_command_error
    return ctx


class TestRoleReactionCogInitAndLoad:
    def test_init(self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_data_manager: RoleReactionDataManager):
        assert role_reaction_cog.bot == mock_bot
        assert role_reaction_cog.data_manager == mock_data_manager
        assert isinstance(role_reaction_cog.message_cache, dict)
        assert not role_reaction_cog.message_cache

    @pytest.mark.asyncio
    async def test_cog_load_calls_load_message_cache(self, role_reaction_cog: RoleReactionCog):
        role_reaction_cog.load_message_cache = AsyncMock()
        await role_reaction_cog.cog_load()
        role_reaction_cog.load_message_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_message_cache_empty(self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_data_manager: RoleReactionDataManager):
        mock_bot.guilds = []
        await role_reaction_cog.load_message_cache()
        mock_data_manager.get_message_info.assert_not_called()
        assert not role_reaction_cog.message_cache

    @pytest.mark.asyncio
    async def test_load_message_cache_with_data(self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild, mock_data_manager: RoleReactionDataManager):
        mock_bot.guilds = [mock_guild]
        mock_data_manager.get_message_info.return_value = (123, 456)
        await role_reaction_cog.load_message_cache()
        mock_data_manager.get_message_info.assert_called_once_with(mock_guild.id)
        assert role_reaction_cog.message_cache[mock_guild.id] == (123, 456)


class TestSetupRoleMessageCommand:
    @pytest.mark.asyncio
    async def test_setup_role_message_success_current_channel(
        self, role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager, mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_guild: discord.Guild, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        mock_text_channel.send = AsyncMock(return_value=mock_message) 
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = mock_text_channel # Устанавливаем канал для контекста
            
        def get_channel_side_effect_current(id_to_get):
            if id_to_get == mock_text_channel.id: 
                return None 
            return MagicMock(spec=discord.TextChannel) 
        role_reaction_cog.bot.get_channel = MagicMock(side_effect=get_channel_side_effect_current)

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)

            mock_text_channel.send.assert_called_once_with("Нужна роль? Нажми на соответствующую реакцию.")
            mock_data_manager.add_role_reaction.assert_called_once_with(
                mock_guild.id, mock_text_channel.id, mock_message.id, "✅", 0, "Системная запись - не удалять"
            )
            assert role_reaction_cog.message_cache[mock_guild.id] == (mock_text_channel.id, mock_message.id)
            mock_safe_send.assert_called_once()
            assert f"Сообщение для получения ролей создано в канале <#{mock_text_channel.id}>" in mock_safe_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_setup_role_message_success_config_channel(
        self, role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager, mock_bot: commands.Bot,
        mock_guild: discord.Guild, mock_message: discord.Message, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        config_channel_id = 999
        mock_bot.settings.channels.role_reactions_default = config_channel_id
        
        config_channel_mock = MagicMock(spec=discord.TextChannel, id=config_channel_id)
        config_channel_mock.send = AsyncMock(return_value=mock_message) 
        mock_bot.get_channel.return_value = config_channel_mock
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = MagicMock(spec=discord.TextChannel) # ctx.channel не должен быть config_channel_mock изначально

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)

            config_channel_mock.send.assert_called_once_with("Нужна роль? Нажми на соответствующую реакцию.")
            mock_data_manager.add_role_reaction.assert_called_once_with(
                mock_guild.id, config_channel_id, mock_message.id, "✅", 0, "Системная запись - не удалять"
            )
            assert role_reaction_cog.message_cache[mock_guild.id] == (config_channel_id, mock_message.id)
            mock_safe_send.assert_called_once()
            assert f"Сообщение для получения ролей создано в канале <#{config_channel_id}>" in mock_safe_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_setup_role_message_already_exists(
        self, role_reaction_cog: RoleReactionCog, mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        existing_channel_id = 123
        mock_data_manager.get_message_info.return_value = (existing_channel_id, 456)
        
        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)
            mock_safe_send.assert_called_once()
            assert f"Сообщение с реакциями уже существует в канале <#{existing_channel_id}>" in mock_safe_send.call_args[0][1]
            mock_data_manager.add_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_role_message_discord_forbidden(
        self, role_reaction_cog: RoleReactionCog,
        mock_data_manager: RoleReactionDataManager, mock_text_channel: discord.TextChannel, mock_guild: discord.Guild, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        mock_text_channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send messages"))
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
                mock_ctx, "У бота нет прав для отправки сообщений в указанный канал.", ephemeral=True
            )

    @pytest.mark.asyncio
    async def test_setup_role_message_config_channel_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild,
        mock_data_manager: RoleReactionDataManager, mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        config_channel_id = 999
        mock_bot.settings.channels.role_reactions_default = config_channel_id
        mock_bot.get_channel.return_value = None
        
        mock_text_channel.send = AsyncMock(return_value=mock_message) 
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = mock_text_channel 

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send, \
             patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)

            mock_logger_warning.assert_any_call(
                f"Канал с ID {config_channel_id} из конфига не найден. "
                f"Используется текущий канал {mock_text_channel.id}."
            )
            mock_text_channel.send.assert_called_once_with("Нужна роль? Нажми на соответствующую реакцию.")
            mock_data_manager.add_role_reaction.assert_called_once_with(
                mock_guild.id, mock_text_channel.id, mock_message.id, "✅", 0, "Системная запись - не удалять"
            )
            mock_safe_send.assert_called_once()
            assert f"Сообщение для получения ролей создано в канале <#{mock_text_channel.id}>" in mock_safe_send.call_args[0][1]

    @pytest.mark.asyncio
    async def test_setup_role_message_invalid_config_channel_id(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild,
        mock_data_manager: RoleReactionDataManager, mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_member: discord.Member, mock_ctx: commands.Context
    ):
        invalid_config_id = "not_an_int"
        mock_bot.settings.channels.role_reactions_default = invalid_config_id
        
        mock_text_channel.send = AsyncMock(return_value=mock_message)
        mock_data_manager.get_message_info.return_value = None
        mock_ctx.channel = mock_text_channel
        
        role_reaction_cog.bot.get_channel = MagicMock()

        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send, \
             patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            await role_reaction_cog.setup_role_message.callback(role_reaction_cog, mock_ctx)

            mock_logger_warning.assert_any_call(
                f"Некорректный ID канала '{invalid_config_id}' в конфиге. "
                f"Используется текущий канал {mock_text_channel.id}."
            )
            role_reaction_cog.bot.get_channel.assert_not_called() 
            mock_text_channel.send.assert_called_once_with("Нужна роль? Нажми на соответствующую реакцию.")
            mock_data_manager.add_role_reaction.assert_called_once_with(
                mock_guild.id, mock_text_channel.id, mock_message.id, "✅", 0, "Системная запись - не удалять"
            )


class TestRoleAssignCommand:
    @pytest.mark.asyncio
    async def test_role_assign_message_not_setup(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role
    ):
        mock_data_manager.get_message_info.return_value = None
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test Role"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert "Сообщение с реакциями не найдено." in mock_interaction.response.send_message.call_args[0][0]
        mock_data_manager.add_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_assign_success_standard_emoji(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role, mock_guild: discord.Guild
    ):
        channel_id, message_id = 123, 456
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        emoji_str = "👍"
        description_str = "Get Test Role"
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji=emoji_str, description=description_str
        )
        mock_data_manager.add_role_reaction.assert_called_once_with(
            mock_guild.id, channel_id, message_id, emoji_str, mock_role.id, description_str
        )
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)
        mock_interaction.response.send_message.assert_called_once()
        assert f"Роль {mock_role.mention} успешно привязана к эмодзи {emoji_str}" in mock_interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_role_assign_success_custom_emoji(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role, mock_guild: discord.Guild
    ):
        channel_id, message_id = 123, 456
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        custom_emoji_input = "<:custom_emoji:789>"
        expected_emoji_format = "custom_emoji:789"
        description_str = "Custom Emoji Role"
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji=custom_emoji_input, description=description_str
        )
        mock_data_manager.add_role_reaction.assert_called_once_with(
            mock_guild.id, channel_id, message_id, expected_emoji_format, mock_role.id, description_str
        )
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)
        mock_interaction.response.send_message.assert_called_once()
        assert f"Роль {mock_role.mention} успешно привязана к эмодзи {custom_emoji_input}" in mock_interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_role_assign_add_fails(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.add_role_reaction.return_value = False
        role_reaction_cog.update_reaction_message = AsyncMock()
        await role_reaction_cog.role_assign.callback(
            role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test"
        )
        mock_interaction.response.send_message.assert_called_once()
        assert "Не удалось добавить привязку роли." in mock_interaction.response.send_message.call_args[0][0]
        role_reaction_cog.update_reaction_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_assign_discord_not_found_non_interaction(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.add_role_reaction.side_effect = discord.NotFound(MagicMock(), "Some other NotFound error")
        
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.role_assign.callback(
                role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test"
            )
            mock_interaction.response.send_message.assert_called_once()
            assert "Произошла ошибка:" in mock_interaction.response.send_message.call_args[0][0]
            assert "Some other NotFound error" in mock_interaction.response.send_message.call_args[0][0]
            mock_logger_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_role_assign_unknown_interaction_error(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.add_role_reaction.side_effect = discord.NotFound(MagicMock(), "Unknown interaction")
        
        with patch("cogs.role_reaction.logger.info") as mock_logger_info:
            await role_reaction_cog.role_assign.callback(
                role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test"
            )
            mock_interaction.response.send_message.assert_not_called()
            mock_logger_info.assert_called_once()
            assert "Взаимодействие не найдено при добавлении роли" in mock_logger_info.call_args[0][0]

    @pytest.mark.asyncio
    async def test_role_assign_generic_exception(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_role: discord.Role
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.add_role_reaction.side_effect = Exception("Generic error")
        
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.role_assign.callback(
                role_reaction_cog, mock_interaction, role=mock_role, emoji="👍", description="Test"
            )
            mock_interaction.response.send_message.assert_called_once()
            assert "Произошла ошибка: Generic error" in mock_interaction.response.send_message.call_args[0][0]
            mock_logger_error.assert_called_once()


class TestRoleRemoveCommand:
    @pytest.mark.asyncio
    async def test_role_remove_message_not_setup(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager
    ):
        mock_data_manager.get_message_info.return_value = None
        await role_reaction_cog.role_remove.callback(role_reaction_cog, mock_interaction, emoji="👍")
        mock_interaction.response.send_message.assert_called_once()
        assert "Сообщение с реакциями не найдено." in mock_interaction.response.send_message.call_args[0][0]
        mock_data_manager.remove_role_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_remove_success(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.remove_role_reaction.return_value = True
        role_reaction_cog.update_reaction_message = AsyncMock(return_value=True)
        emoji_str = "👍"
        await role_reaction_cog.role_remove.callback(role_reaction_cog, mock_interaction, emoji=emoji_str)
        mock_data_manager.remove_role_reaction.assert_called_once_with(mock_guild.id, emoji_str)
        role_reaction_cog.update_reaction_message.assert_called_once_with(mock_guild.id)
        mock_interaction.response.send_message.assert_called_once()
        assert f"Роль, привязанная к эмодзи {emoji_str}, успешно удалена." in mock_interaction.response.send_message.call_args[0][0]

    @pytest.mark.asyncio
    async def test_role_remove_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_interaction: discord.Interaction,
        mock_data_manager: RoleReactionDataManager
    ):
        mock_data_manager.get_message_info.return_value = (123, 456)
        mock_data_manager.remove_role_reaction.return_value = False
        role_reaction_cog.update_reaction_message = AsyncMock()
        emoji_str = "🤔"
        await role_reaction_cog.role_remove.callback(role_reaction_cog, mock_interaction, emoji=emoji_str)
        mock_interaction.response.send_message.assert_called_once()
        assert f"Не найдена привязка роли к эмодзи {emoji_str}." in mock_interaction.response.send_message.call_args[0][0]
        role_reaction_cog.update_reaction_message.assert_not_called()


class TestRawReactionListeners:
    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_success(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_raw_reaction_payload.member = mock_member
        await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
        mock_data_manager.get_role_by_emoji.assert_called_once_with(mock_guild.id, mock_raw_reaction_payload.emoji.name)
        mock_member.add_roles.assert_called_once_with(mock_role, reason="Роль по реакции")

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_bot_user(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_member: discord.Member
    ):
        mock_member.bot = True
        await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
        mock_member.add_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_wrong_message(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_member: discord.Member
    ):
        mock_data_manager.get_message_info.return_value = (123, 999)
        await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
        mock_member.add_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_role_not_found_for_emoji(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = None
        await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
        mock_member.add_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_guild_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_message: discord.Message, mock_member: discord.Member
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = 101 
        role_reaction_cog.bot.get_guild.return_value = None 
        await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
        mock_member.add_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_role_not_found_in_guild(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_message: discord.Message, mock_member: discord.Member
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = 101
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = None 
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
            mock_member.add_roles.assert_not_called()
            mock_logger_warning.assert_called_once_with(f"Не найдена роль с ID 101 на сервере {mock_guild.id}")

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_forbidden(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_member.add_roles.side_effect = discord.Forbidden(MagicMock(), "Cannot add role")
        mock_raw_reaction_payload.member = mock_member
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
            mock_logger_error.assert_called_once()
            assert f"Недостаточно прав для выдачи роли {mock_role.name}" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_raw_reaction_add_generic_exception(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_member.add_roles.side_effect = Exception("Generic add error")
        mock_raw_reaction_payload.member = mock_member
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.on_raw_reaction_add(mock_raw_reaction_payload)
            mock_logger_error.assert_called_once()
            assert f"Ошибка при выдаче роли {mock_role.name}" in mock_logger_error.call_args[0][0]
            # Проверяем, что exc_info=True было передано, и что сообщение содержит текст ошибки
            assert mock_logger_error.call_args[1]['exc_info'] is True
            assert "Generic add error" in mock_logger_error.call_args[0][0] # Текст ошибки будет в основном сообщении


    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_success(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = mock_member
        mock_guild.fetch_member = AsyncMock(return_value=mock_member)
        mock_raw_reaction_payload.member = mock_member
        await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
        mock_data_manager.get_role_by_emoji.assert_called_once_with(mock_guild.id, mock_raw_reaction_payload.emoji.name)
        mock_member.remove_roles.assert_called_once_with(mock_role, reason="Роль по реакции (удалена)")

    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_member_not_in_payload_fetched(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        mock_raw_reaction_payload.member = None 
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = None 
        mock_guild.fetch_member.return_value = mock_member 

        await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
        mock_guild.fetch_member.assert_called_once_with(mock_raw_reaction_payload.user_id)
        mock_member.remove_roles.assert_called_once_with(mock_role, reason="Роль по реакции (удалена)")

    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_member_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_message: discord.Message
    ):
        mock_raw_reaction_payload.member = None
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = None
        mock_guild.fetch_member.side_effect = discord.NotFound(MagicMock(), "Member not found")
        
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
            mock_logger_warning.assert_called_once_with(
                f"Не найден пользователь с ID {mock_raw_reaction_payload.user_id} на сервере {mock_guild.id}"
            )

    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_fetch_member_exception(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_message: discord.Message, mock_member: discord.Member
    ):
        mock_raw_reaction_payload.member = None
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = None
        mock_guild.fetch_member.side_effect = discord.HTTPException(MagicMock(), "Fetch error")
        
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
            mock_logger_error.assert_called_once()
            assert f"Ошибка при получении пользователя {mock_raw_reaction_payload.user_id}" in mock_logger_error.call_args[0][0]
            mock_member.remove_roles.assert_not_called()


    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_forbidden(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = mock_member
        mock_member.remove_roles.side_effect = discord.Forbidden(MagicMock(), "Cannot remove role")
        mock_raw_reaction_payload.member = mock_member

        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
            mock_logger_error.assert_called_once()
            assert f"Недостаточно прав для снятия роли {mock_role.name}" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_on_raw_reaction_remove_generic_exception(
        self, role_reaction_cog: RoleReactionCog, mock_raw_reaction_payload: discord.RawReactionActionEvent,
        mock_data_manager: RoleReactionDataManager, mock_guild: discord.Guild, mock_role: discord.Role,
        mock_member: discord.Member, mock_message: discord.Message
    ):
        channel_id, message_id = mock_message.channel.id, mock_message.id
        mock_data_manager.get_message_info.return_value = (channel_id, message_id)
        mock_data_manager.get_role_by_emoji.return_value = mock_role.id
        role_reaction_cog.bot.get_guild.return_value = mock_guild
        mock_guild.get_role.return_value = mock_role
        mock_guild.get_member.return_value = mock_member
        mock_member.remove_roles.side_effect = Exception("Generic remove error")
        mock_raw_reaction_payload.member = mock_member

        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            await role_reaction_cog.on_raw_reaction_remove(mock_raw_reaction_payload)
            mock_logger_error.assert_called_once()
            assert f"Ошибка при снятии роли {mock_role.name}" in mock_logger_error.call_args[0][0]
            # Проверяем, что exc_info=True было передано, и что сообщение содержит текст ошибки
            assert mock_logger_error.call_args[1]['exc_info'] is True
            assert "Generic remove error" in mock_logger_error.call_args[0][0] # Текст ошибки будет в основном сообщении


class TestUpdateReactionMessage:
    @pytest.mark.asyncio
    async def test_update_reaction_message_no_cache(self, role_reaction_cog: RoleReactionCog, mock_guild: discord.Guild):
        role_reaction_cog.message_cache = {}
        result = await role_reaction_cog.update_reaction_message(mock_guild.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_update_reaction_message_success(
        self, role_reaction_cog: RoleReactionCog, mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel, mock_message: discord.Message,
        mock_role: discord.Role, mock_data_manager: RoleReactionDataManager, mock_bot: commands.Bot
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = mock_role
        db_reaction_data = [
            {"guild_id": mock_guild.id, "channel_id": mock_text_channel.id, "message_id": mock_message.id,
             "emoji": "👍", "role_id": mock_role.id, "description": "Лайк"},
            {"guild_id": mock_guild.id, "channel_id": mock_text_channel.id, "message_id": mock_message.id,
             "emoji": "🎉", "role_id": 0, "description": "Системная"}
        ]
        mock_data_manager.get_all_role_reactions.return_value = db_reaction_data
        mock_message.reactions = []
        result = await role_reaction_cog.update_reaction_message(mock_guild.id)
        assert result is True
        mock_message.edit.assert_called_once()
        edited_content = mock_message.edit.call_args[1]['content']
        assert "Нужна роль? Нажми на соответствующую реакцию." in edited_content
        assert f"👍 - {mock_role.mention}: Лайк" in edited_content
        assert "🎉" not in edited_content
        mock_message.add_reaction.assert_called_once_with("👍")

    @pytest.mark.asyncio
    async def test_update_reaction_message_existing_reaction(
        self, role_reaction_cog: RoleReactionCog, mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel, mock_message: discord.Message,
        mock_role: discord.Role, mock_data_manager: RoleReactionDataManager, mock_bot: commands.Bot
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = mock_role
        db_reaction_data = [{"emoji": "👍", "role_id": mock_role.id, "description": "Лайк"}]
        mock_data_manager.get_all_role_reactions.return_value = db_reaction_data
        existing_reaction_mock = MagicMock(spec=discord.Reaction)
        existing_reaction_mock.emoji = "👍"
        mock_message.reactions = [existing_reaction_mock]
        result = await role_reaction_cog.update_reaction_message(mock_guild.id)
        assert result is True
        mock_message.add_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_reaction_message_guild_not_found(self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild):
        role_reaction_cog.message_cache[mock_guild.id] = (123, 456)
        mock_bot.get_guild.return_value = None 
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(f"Не найден сервер с ID {mock_guild.id}")

    @pytest.mark.asyncio
    async def test_update_reaction_message_channel_not_found(self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild):
        channel_id, message_id = 123, 456
        role_reaction_cog.message_cache[mock_guild.id] = (channel_id, message_id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = None 
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(f"Не найден канал с ID {channel_id} на сервере {mock_guild.id}")

    @pytest.mark.asyncio
    async def test_update_reaction_message_message_not_found(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild, mock_text_channel: discord.TextChannel
    ):
        message_id = 456
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, message_id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.side_effect = discord.NotFound(MagicMock(), "Message not found")
        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_warning.assert_called_once_with(f"Не найдено сообщение с ID {message_id} в канале {mock_text_channel.id}")

    @pytest.mark.asyncio
    async def test_update_reaction_message_fetch_message_exception(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild, mock_text_channel: discord.TextChannel
    ):
        message_id = 456
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, message_id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.side_effect = discord.HTTPException(MagicMock(), "API error")
        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is False
            mock_logger_error.assert_called_once()
            assert f"Ошибка при получении сообщения {message_id}" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_reaction_message_role_not_found_in_guild(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_data_manager: RoleReactionDataManager
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = None 
        db_reaction_data = [{"emoji": "👍", "role_id": 101, "description": "Лайк"}]
        mock_data_manager.get_all_role_reactions.return_value = db_reaction_data

        with patch("cogs.role_reaction.logger.warning") as mock_logger_warning:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is True 
            mock_logger_warning.assert_called_once_with(f"Не найдена роль с ID 101 на сервере {mock_guild.id}")
            mock_message.edit.assert_called_once()
            edited_content = mock_message.edit.call_args[1]['content']
            assert "👍" not in edited_content 
            mock_message.add_reaction.assert_not_called() 

    @pytest.mark.asyncio
    async def test_update_reaction_message_edit_exception(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_data_manager: RoleReactionDataManager
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
            assert "Ошибка при обновлении сообщения с реакциями" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_reaction_message_add_reaction_exception(
        self, role_reaction_cog: RoleReactionCog, mock_bot: commands.Bot, mock_guild: discord.Guild,
        mock_text_channel: discord.TextChannel, mock_message: discord.Message, mock_role: discord.Role,
        mock_data_manager: RoleReactionDataManager
    ):
        role_reaction_cog.message_cache[mock_guild.id] = (mock_text_channel.id, mock_message.id)
        mock_bot.get_guild.return_value = mock_guild
        mock_guild.get_channel.return_value = mock_text_channel
        mock_text_channel.fetch_message.return_value = mock_message
        mock_guild.get_role.return_value = mock_role
        db_reaction_data = [{"emoji": "👍", "role_id": mock_role.id, "description": "Лайк"}]
        mock_data_manager.get_all_role_reactions.return_value = db_reaction_data
        mock_message.reactions = []
        mock_message.add_reaction.side_effect = discord.HTTPException(MagicMock(), "Add reaction failed")

        with patch("cogs.role_reaction.logger.error") as mock_logger_error:
            result = await role_reaction_cog.update_reaction_message(mock_guild.id)
            assert result is True 
            mock_message.edit.assert_called_once()
            mock_logger_error.assert_called_once()
            assert mock_logger_error.call_args[0][0].startswith("Не удалось добавить реакцию 👍:")
            assert "Add reaction failed" in mock_logger_error.call_args[0][0]


class TestCogCommandError:
    @pytest.mark.asyncio
    async def test_cog_command_error_missing_permissions(self, role_reaction_cog: RoleReactionCog, mock_ctx: commands.Context):
        error = commands.MissingPermissions(["manage_roles"])
        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.cog_command_error(mock_ctx, error)
            mock_safe_send.assert_called_once_with(mock_ctx, "У вас нет прав для выполнения этой команды.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_cog_command_error_command_invoke_error(self, role_reaction_cog: RoleReactionCog, mock_ctx: commands.Context):
        original_error = ValueError("Test original error")
        error = commands.CommandInvokeError(original_error)
        mock_ctx.command = MagicMock(name="test_invoke_command") # Убедимся, что у ctx есть command
        with patch("cogs.role_reaction.logger.error") as mock_logger_error, \
             patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.cog_command_error(mock_ctx, error)
            mock_safe_send.assert_called_once_with(mock_ctx, f"Произошла ошибка: {original_error}", ephemeral=True)
            mock_logger_error.assert_called_once_with(
                f"Ошибка при выполнении команды {mock_ctx.command}: {original_error}", exc_info=original_error
            )

    @pytest.mark.asyncio
    async def test_cog_command_error_bad_argument(self, role_reaction_cog: RoleReactionCog, mock_ctx: commands.Context):
        error = commands.BadArgument("Bad argument provided")
        with patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.cog_command_error(mock_ctx, error)
            mock_safe_send.assert_called_once_with(mock_ctx, f"Неверный аргумент: {error}", ephemeral=True)

    @pytest.mark.asyncio
    async def test_cog_command_error_generic_error(self, role_reaction_cog: RoleReactionCog, mock_ctx: commands.Context):
        error = Exception("Some generic error")
        mock_ctx.command = MagicMock(name="test_generic_command")
        with patch("cogs.role_reaction.logger.error") as mock_logger_error, \
             patch("cogs.role_reaction.safe_send", new_callable=AsyncMock) as mock_safe_send:
            await role_reaction_cog.cog_command_error(mock_ctx, error)
            mock_safe_send.assert_called_once_with(mock_ctx, f"Произошла неизвестная ошибка: {error}", ephemeral=True)
            mock_logger_error.assert_called_once_with(
                f"Необработанная ошибка в команде {mock_ctx.command}: {error}", exc_info=error
            )


@pytest.mark.asyncio
async def test_setup_function(mock_bot: commands.Bot):
    from cogs.role_reaction import setup as setup_cog
    mock_bot.add_cog = AsyncMock()
    with patch("cogs.role_reaction.logger.info") as mock_logger_info:
        await setup_cog(mock_bot)
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], RoleReactionCog)
        mock_logger_info.assert_called_once_with("Ког RoleReactionCog успешно загружен.")
