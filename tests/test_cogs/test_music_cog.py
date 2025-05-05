import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import discord
from discord.ext import commands
import os
from pathlib import Path
from collections import deque

# Импортируем тестируемые модули
from cogs.music import MusicCog
from utils.music.player import MusicPlayer, Track
from utils.music.embeds import create_embed, format_duration
from utils.music.ui import PlayerControlView, SearchView

# --- Фикстуры для асинхронного тестирования ---

@pytest.fixture
def event_loop():
    """Создает и настраивает event loop для тестов."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

# --- Фикстуры ---

@pytest.fixture
def mock_bot():
    """Создает мок для бота Discord."""
    bot = MagicMock(spec=commands.Bot)
    bot.config = {
        "PROXY_URL": None,
    }
    bot.guilds = []
    bot.wait_until_ready = AsyncMock()
    bot.add_cog = AsyncMock()
    bot.get_channel = MagicMock(return_value=None)
    # Мокаем loop для create_task
    bot.loop = asyncio.get_event_loop()
    return bot

@pytest.fixture
def mock_voice_client():
    """Создает мок для голосового клиента Discord."""
    voice_client = MagicMock(spec=discord.VoiceClient)
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = False
    voice_client.channel = MagicMock(spec=discord.VoiceChannel)
    voice_client.channel.name = "Test Voice Channel"
    voice_client.channel.id = 123456789
    voice_client.channel.members = []
    voice_client.play = MagicMock()
    voice_client.stop = MagicMock()
    voice_client.pause = MagicMock()
    voice_client.resume = MagicMock()
    voice_client.disconnect = AsyncMock()
    voice_client.move_to = AsyncMock()
    return voice_client

@pytest.fixture
def mock_text_channel():
    """Создает мок для текстового канала Discord."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 987654321
    channel.name = "test-music"
    channel.send = AsyncMock()
    channel.guild = MagicMock(spec=discord.Guild)
    return channel

@pytest.fixture
def mock_member():
    """Создает мок для участника сервера."""
    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "TestUser"
    member.mention = "<@1>"
    member.bot = False
    member.voice = MagicMock()
    member.voice.channel = MagicMock(spec=discord.VoiceChannel)
    member.voice.channel.name = "Test Voice Channel"
    member.voice.channel.id = 123456789
    member.voice.channel.members = []
    member.guild = MagicMock(spec=discord.Guild)
    return member

@pytest.fixture
def mock_interaction(mock_member, mock_text_channel):
    """Создает мок для взаимодействия Discord."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = mock_member
    interaction.channel = mock_text_channel
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction

@pytest.fixture
def mock_track_info():
    """Создает мок информации о треке."""
    return {
        'id': 'test_id',
        'title': 'Test Track',
        'webpage_url': 'https://www.youtube.com/watch?v=test_id',
        'duration': 180,  # 3 минуты
        'thumbnail': 'https://example.com/thumbnail.jpg',
        'uploader': 'Test Uploader',
        'uploader_url': 'https://www.youtube.com/channel/test_channel',
        'extractor_key': 'Youtube',
        'filepath': 'downloads/Youtube-test_id-Test_Track.mp3'
    }

@pytest.fixture
def mock_track(mock_track_info, mock_member):
    """Создает реальный объект Track для тестов."""
    return Track(mock_track_info, mock_member)

@pytest.fixture
def mock_music_player(mock_bot, mock_voice_client, mock_track, mock_text_channel):
    """Создает мок для MusicPlayer."""
    player = MagicMock(spec=MusicPlayer)
    player.bot = mock_bot
    player.voice_client = mock_voice_client
    player.current_track = mock_track
    player.is_playing = True
    player.is_paused = False
    player.queue = deque()
    player.connect = AsyncMock(return_value=True)
    player.disconnect = AsyncMock()
    player.queue_track = AsyncMock()
    # Добавляем side_effect для команд, чтобы они считались вызванными
    player.skip = AsyncMock(side_effect=lambda *a, **kw: None)
    player.stop = AsyncMock(side_effect=lambda *a, **kw: None)
    player.pause = AsyncMock(side_effect=lambda *a, **kw: None)
    player.resume = AsyncMock(side_effect=lambda *a, **kw: None)
    player.show_queue = AsyncMock()
    player._cleanup_task = MagicMock()
    player._cleanup_task.cancel = MagicMock()
    player.text_channel = mock_text_channel  # Добавляем text_channel
    return player

@pytest.fixture
async def music_cog(mock_bot, mock_music_player):
    """Создает экземпляр MusicCog с моком MusicPlayer."""
    # Патчим MusicPlayer внутри кога
    with patch('cogs.music.MusicPlayer', return_value=mock_music_player):
        cog = MusicCog(mock_bot)
        cog.player = mock_music_player  # Явно устанавливаем мок
        yield cog

# --- Тесты для вспомогательных функций ---

def test_format_duration():
    """Тестирует функцию format_duration."""
    # Тест для None
    assert format_duration(None) == "∞"
    
    # Тест для отрицательного значения
    assert format_duration(-10) == "00:00"
    
    # Тест для нуля
    assert format_duration(0) == "00:00"
    
    # Тест для секунд
    assert format_duration(45) == "00:45"
    
    # Тест для минут и секунд
    assert format_duration(125) == "02:05"
    
    # Тест для часов, минут и секунд
    assert format_duration(3661) == "01:01:01"
    
    # Тест для некорректного значения
    assert format_duration("invalid") == "?:??"

def test_create_embed():
    """Тестирует функцию create_embed."""
    # Базовый тест
    embed = create_embed("Test Title", "Test Description")
    assert embed.title == "Test Title"
    assert embed.description == "Test Description"
    
    # Тест с thumbnail
    embed = create_embed("Test Title", thumbnail="https://example.com/image.jpg")
    assert embed.thumbnail.url == "https://example.com/image.jpg"
    
    # Тест с footer
    embed = create_embed("Test Title", footer="Test Footer")
    assert embed.footer.text == "Test Footer"
    
    # Тест с полями
    embed = create_embed("Test Title", fields=[
        ("Field 1", "Value 1", True),
        ("Field 2", "Value 2", False)
    ])
    assert len(embed.fields) == 2
    assert embed.fields[0].name == "Field 1"
    assert embed.fields[0].value == "Value 1"
    assert embed.fields[0].inline is True
    assert embed.fields[1].name == "Field 2"
    assert embed.fields[1].value == "Value 2"
    assert embed.fields[1].inline is False

# --- Тесты для класса Track ---

def test_track_initialization(mock_track, mock_member, mock_track_info):
    """Тестирует инициализацию класса Track."""
    assert mock_track.url == mock_track_info['webpage_url']
    assert mock_track.title == mock_track_info['title']
    assert mock_track.duration == mock_track_info['duration']
    assert mock_track.thumbnail == mock_track_info['thumbnail']
    assert mock_track.uploader == mock_track_info['uploader']
    assert mock_track.uploader_url == mock_track_info['uploader_url']
    assert mock_track.requester == mock_member
    assert mock_track.id == mock_track_info['id']
    assert mock_track.extractor == mock_track_info['extractor_key'].lower()
    # filepath не всегда устанавливается в конструкторе Track, поэтому не проверяем

def test_track_str_representation(mock_track):
    """Тестирует строковое представление трека."""
    expected = f"**{mock_track.title}** ({format_duration(mock_track.duration)})"
    assert str(mock_track) == expected

def test_track_to_embed_field(mock_track):
    """Тестирует метод to_embed_field."""
    # Без индекса
    name, value, inline = mock_track.to_embed_field()
    assert name == mock_track.title
    assert f"{format_duration(mock_track.duration)}" in value
    assert mock_track.requester.mention in value
    assert mock_track.uploader in value
    assert inline is False
    
    # С индексом
    name, value, inline = mock_track.to_embed_field(index=1)
    assert name.startswith("`1.` ")
    assert name.endswith(mock_track.title)

# --- Тесты для MusicCog ---

@pytest.mark.asyncio
async def test_cog_initialization(music_cog, mock_bot):
    """Тестирует инициализацию кога."""
    assert music_cog.bot is mock_bot
    assert music_cog.player is not None

@pytest.mark.asyncio
async def test_cog_unload(music_cog):
    """Тестирует выгрузку кога."""
    # Мокаем player._cleanup_task
    music_cog.player._cleanup_task = MagicMock()
    music_cog.player._cleanup_task.cancel = MagicMock()
    
    # Вызываем cog_unload
    music_cog.cog_unload()
    
    # Проверяем, что задача очистки отменена
    music_cog.player._cleanup_task.cancel.assert_called_once()
    # Проверяем, что asyncio.create_task был вызван для disconnect
    with patch("asyncio.create_task") as mock_create_task:
        music_cog.cog_unload()
        mock_create_task.assert_called()

@pytest.mark.asyncio
async def test_on_voice_state_update_bot_user(music_cog, mock_member):
    """Тестирует обработку изменения голосового состояния для бота."""
    # Устанавливаем mock_member как бота
    mock_member.bot = True
    before = MagicMock(spec=discord.VoiceState)
    after = MagicMock(spec=discord.VoiceState)
    
    await music_cog.on_voice_state_update(mock_member, before, after)
    
    # Проверяем, что ничего не происходит для ботов
    music_cog.player.disconnect.assert_not_awaited()

@pytest.mark.asyncio
async def test_on_voice_state_update_no_voice_client(music_cog, mock_member):
    """Тестирует обработку изменения голосового состояния без голосового клиента."""
    # Устанавливаем voice_client как None
    music_cog.player.voice_client = None
    before = MagicMock(spec=discord.VoiceState)
    after = MagicMock(spec=discord.VoiceState)
    
    await music_cog.on_voice_state_update(mock_member, before, after)
    
    # Проверяем, что ничего не происходит без голосового клиента
    music_cog.player.disconnect.assert_not_awaited()

@pytest.mark.asyncio
async def test_on_voice_state_update_user_leaves_empty_channel(music_cog, mock_member, mock_voice_client):
    """Тестирует отключение бота, когда пользователь покидает канал и бот остается один."""
    # Устанавливаем voice_client
    music_cog.player.voice_client = mock_voice_client
    
    # Настраиваем before и after
    before = MagicMock(spec=discord.VoiceState)
    before.channel = mock_voice_client.channel
    after = MagicMock(spec=discord.VoiceState)
    after.channel = None  # Пользователь покинул канал
    
    # Устанавливаем пустой список участников в канале (только боты)
    bot_member = MagicMock(spec=discord.Member)
    bot_member.bot = True
    mock_voice_client.channel.members = [bot_member]
    
    # Патчим asyncio.sleep, чтобы не ждать
    with patch('asyncio.sleep', new_callable=AsyncMock):
        await music_cog.on_voice_state_update(mock_member, before, after)
    
    # Проверяем, что disconnect был вызван
    music_cog.player.disconnect.assert_awaited_once()

@pytest.mark.asyncio
async def test_ensure_voice_success(music_cog, mock_interaction):
    """Тестирует успешную проверку голосового канала."""
    result = await music_cog._ensure_voice(mock_interaction)
    assert result is True
    mock_interaction.response.send_message.assert_not_awaited()

@pytest.mark.asyncio
async def test_ensure_voice_failure(music_cog, mock_interaction):
    """Тестирует неудачную проверку голосового канала."""
    # Устанавливаем отсутствие голосового канала
    mock_interaction.user.voice = None
    
    result = await music_cog._ensure_voice(mock_interaction)
    assert result is False
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Вы должны быть в голосовом канале" in mock_interaction.response.send_message.call_args.args[0]

@pytest.mark.asyncio
async def test_connect_or_move_success(music_cog, mock_interaction, mock_text_channel):
    """Тестирует успешное подключение к голосовому каналу."""
    # Устанавливаем успешное подключение
    music_cog.player.connect.return_value = True
    
    result = await music_cog._connect_or_move(mock_interaction)
    assert result is True
    music_cog.player.connect.assert_awaited_once_with(mock_interaction.user.voice.channel)
    
    # Проверяем установку текстового канала
    assert music_cog.player.text_channel == mock_text_channel

@pytest.mark.asyncio
async def test_connect_or_move_failure(music_cog, mock_interaction):
    """Тестирует неудачное подключение к голосовому каналу."""
    # Устанавливаем неудачное подключение
    music_cog.player.connect.return_value = False
    
    result = await music_cog._connect_or_move(mock_interaction)
    assert result is False
    music_cog.player.connect.assert_awaited_once_with(mock_interaction.user.voice.channel)
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Не удалось подключиться" in mock_interaction.response.send_message.call_args.args[0]

# --- Тесты для команд MusicCog ---

@pytest.mark.asyncio
async def test_play_command_with_url(music_cog, mock_interaction):
    """Тестирует команду /play с URL."""
    # Мокаем _ensure_voice и _connect_or_move
    music_cog._ensure_voice = AsyncMock(return_value=True)
    music_cog._connect_or_move = AsyncMock(return_value=True)
    
    # URL для теста
    test_url = "https://www.youtube.com/watch?v=test_id"
    
    # Вызываем команду через .callback
    await music_cog.play.callback(music_cog, mock_interaction, query=test_url)
    
    # Проверяем вызовы
    mock_interaction.response.defer.assert_awaited_once()
    music_cog._ensure_voice.assert_awaited_once_with(mock_interaction)
    music_cog._connect_or_move.assert_awaited_once_with(mock_interaction)
    mock_interaction.edit_original_response.assert_awaited_once()
    # Проверяем, что edit_original_response был вызван с нужным embed или content
    call_args = mock_interaction.edit_original_response.call_args
    content = ""
    if call_args.args:
        content = call_args.args[0]
    elif 'content' in call_args.kwargs:
        content = call_args.kwargs['content']
    assert "Добавляем трек по ссылке" in content or "Добавляем" in content
    music_cog.player.queue_track.assert_awaited_once_with(test_url, mock_interaction.user, mock_interaction)

@pytest.mark.asyncio
async def test_play_command_with_search(music_cog, mock_interaction):
    """Тестирует команду /play с поисковым запросом."""
    # Мокаем _ensure_voice и _connect_or_move
    music_cog._ensure_voice = AsyncMock(return_value=True)
    music_cog._connect_or_move = AsyncMock(return_value=True)
    
    # Мокаем search_youtube
    search_results = [{"title": "Test Result", "uploader": "Test Uploader", "duration": 180}]
    with patch('cogs.music.search_youtube', new_callable=AsyncMock) as mock_search:
        mock_search.return_value = search_results
        
        # Мокаем SearchView
        with patch('cogs.music.SearchView') as MockSearchView:
            mock_view = MagicMock()
            MockSearchView.return_value = mock_view
            
            # Поисковый запрос для теста
            test_query = "test search query"
            
            # Вызываем команду через .callback
            await music_cog.play.callback(music_cog, mock_interaction, query=test_query)
            
            # Проверяем вызовы
            mock_interaction.response.defer.assert_awaited_once()
            music_cog._ensure_voice.assert_awaited_once_with(mock_interaction)
            music_cog._connect_or_move.assert_awaited_once_with(mock_interaction)
            # Проверяем, что edit_original_response был вызван дважды: сначала с "Ищем", потом с embed/view
            assert mock_interaction.edit_original_response.await_count >= 2
            last_call = mock_interaction.edit_original_response.call_args
            content = ""
            if last_call.args:
                content = last_call.args[0]
            elif 'content' in last_call.kwargs:
                content = last_call.kwargs['content']
            # Проверяем, что хотя бы один вызов был с embed/view
            found_embed = any(
                'embed' in call.kwargs or 'view' in call.kwargs
                for call in mock_interaction.edit_original_response.call_args_list
            )
            assert found_embed
            mock_search.assert_awaited_once_with(test_query)
            MockSearchView.assert_called_once_with(music_cog.player, mock_interaction, search_results)

@pytest.mark.asyncio
async def test_play_command_search_no_results(music_cog, mock_interaction):
    """Тестирует команду /play с поисковым запросом без результатов."""
    # Мокаем _ensure_voice и _connect_or_move
    music_cog._ensure_voice = AsyncMock(return_value=True)
    music_cog._connect_or_move = AsyncMock(return_value=True)
    
    # Мокаем search_youtube без результатов
    with patch('cogs.music.search_youtube', new_callable=AsyncMock) as mock_search:
        mock_search.return_value = None
        
        # Мокаем create_embed
        with patch('cogs.music.create_embed') as mock_create_embed:
            mock_embed = MagicMock()
            mock_create_embed.return_value = mock_embed
            
            # Поисковый запрос для теста
            test_query = "test search query"
            
            # Вызываем команду через .callback
            await music_cog.play.callback(music_cog, mock_interaction, query=test_query)
            
            # Проверяем вызовы
            # Проверяем, что edit_original_response был вызван дважды: сначала с "Ищем", потом с embed
            assert mock_interaction.edit_original_response.await_count >= 2
            mock_create_embed.assert_called_once()
            found_embed = any(
                'embed' in call.kwargs and call.kwargs['embed'] == mock_embed
                for call in mock_interaction.edit_original_response.call_args_list
            )
            assert found_embed

@pytest.mark.asyncio
async def test_skip_command(music_cog, mock_interaction, mock_voice_client, mock_music_player):
    """Тестирует команду /skip."""
    # Устанавливаем voice_client
    music_cog.player.voice_client = mock_voice_client

    # Гарантируем, что interaction.user.voice.channel == player.voice_client.channel
    mock_interaction.user.voice.channel = mock_voice_client.channel

    print(f"[DEBUG] id(mock_music_player)={id(mock_music_player)}")

    # Вызываем команду через .callback
    await music_cog.skip.callback(music_cog, mock_interaction)

    # Проверяем вызов skip
    assert music_cog.player.skip.called

@pytest.mark.asyncio
async def test_stop_command(music_cog, mock_interaction, mock_voice_client):
    """Тестирует команду /stop."""
    # Устанавливаем voice_client
    music_cog.player.voice_client = mock_voice_client
    mock_interaction.user.voice.channel = mock_voice_client.channel

    # Вызываем команду через .callback
    await music_cog.stop.callback(music_cog, mock_interaction)

    # Проверяем вызов stop
    assert music_cog.player.stop.called

@pytest.mark.asyncio
async def test_pause_command(music_cog, mock_interaction, mock_voice_client):
    """Тестирует команду /pause."""
    # Устанавливаем voice_client
    music_cog.player.voice_client = mock_voice_client
    mock_interaction.user.voice.channel = mock_voice_client.channel

    # Вызываем команду через .callback
    await music_cog.pause.callback(music_cog, mock_interaction)

    # Проверяем вызов pause
    assert music_cog.player.pause.called

@pytest.mark.asyncio
async def test_resume_command(music_cog, mock_interaction, mock_voice_client):
    """Тестирует команду /resume."""
    # Устанавливаем voice_client
    music_cog.player.voice_client = mock_voice_client
    mock_interaction.user.voice.channel = mock_voice_client.channel

    # Вызываем команду через .callback
    await music_cog.resume.callback(music_cog, mock_interaction)

    # Проверяем вызов resume
    assert music_cog.player.resume.called

@pytest.mark.asyncio
async def test_queue_command(music_cog, mock_interaction):
    """Тестирует команду /queue."""
    # Вызываем команду через .callback
    await music_cog.queue.callback(music_cog, mock_interaction)
    
    # Проверяем вызов show_queue
    music_cog.player.show_queue.assert_awaited_once_with(mock_interaction)

# --- Тесты для обработки ошибок ---

@pytest.mark.asyncio
async def test_cog_app_command_error_check_failure(music_cog, mock_interaction):
    """Тестирует обработку ошибки CheckFailure."""
    error = discord.app_commands.CheckFailure()
    mock_interaction.command = MagicMock()
    mock_interaction.command.name = "test_command"
    
    await music_cog.cog_app_command_error(mock_interaction, error)
    
    mock_interaction.response.send_message.assert_awaited_once()
    assert "У вас нет прав" in mock_interaction.response.send_message.call_args.args[0]

@pytest.mark.asyncio
async def test_cog_app_command_error_timeout(music_cog, mock_interaction):
    """Тестирует обработку ошибки TimeoutError."""
    original_error = asyncio.TimeoutError()
    # Исправленный вызов: первый аргумент - команда, второй - ошибка
    error = discord.app_commands.CommandInvokeError(MagicMock(), original_error)
    mock_interaction.command = MagicMock()
    mock_interaction.command.name = "test_command"

    await music_cog.cog_app_command_error(mock_interaction, error)

    mock_interaction.response.send_message.assert_awaited_once()
    assert "Превышено время ожидания" in mock_interaction.response.send_message.call_args.args[0]

@pytest.mark.asyncio
async def test_cog_app_command_error_after_response(music_cog, mock_interaction):
    """Тестирует обработку ошибки после отправки ответа."""
    error = Exception("Test error")
    mock_interaction.command = MagicMock()
    mock_interaction.command.name = "test_command"
    mock_interaction.response.is_done.return_value = True
    
    await music_cog.cog_app_command_error(mock_interaction, error)
    
    mock_interaction.followup.send.assert_awaited_once()
    assert "Произошла ошибка" in mock_interaction.followup.send.call_args.args[0]
