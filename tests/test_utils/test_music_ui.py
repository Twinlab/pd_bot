import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.music.player import MusicPlayer, Track
from utils.music.ui import PlayerControlView, SearchResultSelect, SearchView

# --- Фикстуры ---


@pytest.fixture
def mock_bot():
    """Создает мок для бота Discord."""
    bot = MagicMock()
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
    return voice_client


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
def mock_interaction(mock_member):
    """Создает мок для взаимодействия Discord."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = mock_member
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.message = MagicMock(spec=discord.Message)
    interaction.message.edit = AsyncMock()
    interaction.message.delete = AsyncMock()
    return interaction


@pytest.fixture
def mock_track_info():
    """Создает мок информации о треке."""
    return {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": "https://www.youtube.com/watch?v=test_id",
        "duration": 180,  # 3 минуты
        "thumbnail": "https://example.com/thumbnail.jpg",
        "uploader": "Test Uploader",
        "uploader_url": "https://www.youtube.com/channel/test_channel",
        "extractor_key": "Youtube",
        "url": "https://example.com/stream.mp3",
    }


@pytest.fixture
def mock_track(mock_track_info, mock_member):
    """Создает экземпляр Track."""
    track = MagicMock(spec=Track)
    track.url = mock_track_info["webpage_url"]
    track.title = mock_track_info["title"]
    track.duration = mock_track_info["duration"]
    track.thumbnail = mock_track_info["thumbnail"]
    track.uploader = mock_track_info["uploader"]
    track.uploader_url = mock_track_info["uploader_url"]
    track.requester = mock_member
    track.id = mock_track_info["id"]
    track.extractor = mock_track_info["extractor_key"].lower()
    track.stream_url = mock_track_info["url"]
    return track


@pytest.fixture
def mock_music_player(mock_bot, mock_voice_client, mock_track):
    """Создает мок для MusicPlayer."""
    player = MagicMock(spec=MusicPlayer)
    player.bot = mock_bot
    player.voice_client = mock_voice_client
    player.current_track = mock_track
    player.is_playing = True
    player.is_paused = False
    player.pause = AsyncMock()
    player.resume = AsyncMock()
    player.skip = AsyncMock()
    player.stop = AsyncMock()
    player.show_queue = AsyncMock()
    player.connect = AsyncMock(return_value=True)
    player.queue_track = AsyncMock()
    return player


@pytest.fixture
async def player_control_view(mock_music_player):
    """Создает экземпляр PlayerControlView."""
    # Гарантируем, что View создается внутри event loop
    return PlayerControlView(mock_music_player)


@pytest.fixture
def search_entries():
    """Создает список результатов поиска."""
    return [
        {
            "id": "test_id_1",
            "title": "Test Track 1",
            "webpage_url": "https://www.youtube.com/watch?v=test_id_1",
            "duration": 180,
            "uploader": "Test Uploader 1",
        },
        {
            "id": "test_id_2",
            "title": "Test Track 2",
            "webpage_url": "https://www.youtube.com/watch?v=test_id_2",
            "duration": 240,
            "uploader": "Test Uploader 2",
        },
    ]


@pytest.fixture
def search_result_select(mock_music_player, mock_interaction, search_entries):
    """Создает экземпляр SearchResultSelect."""
    return SearchResultSelect(mock_music_player, mock_interaction, search_entries)


@pytest.fixture
async def search_view(mock_music_player, mock_interaction, search_entries):
    """Создает экземпляр SearchView."""
    # Гарантируем, что View создается внутри event loop
    return SearchView(mock_music_player, mock_interaction, search_entries)


# --- Тесты для PlayerControlView ---


def test_player_control_view_initialization(player_control_view, mock_music_player):
    """Тестирует инициализацию PlayerControlView."""
    assert player_control_view.player is mock_music_player
    assert len(player_control_view.children) == 4  # 4 кнопки

    # Проверяем наличие всех кнопок
    button_ids = [child.custom_id for child in player_control_view.children]
    assert "music:pause_resume" in button_ids
    assert "music:skip" in button_ids
    assert "music:stop" in button_ids
    assert "music:queue" in button_ids


def test_update_buttons_playing(player_control_view, mock_music_player):
    """Тестирует обновление кнопок при воспроизведении."""
    # Устанавливаем состояние воспроизведения
    mock_music_player.is_playing = True
    mock_music_player.is_paused = False
    mock_music_player.current_track = MagicMock()

    # Вызываем _update_buttons
    player_control_view._update_buttons()

    # Проверяем состояние кнопок
    pause_resume_button = discord.utils.get(
        player_control_view.children, custom_id="music:pause_resume"
    )
    assert pause_resume_button is not None
    assert pause_resume_button.disabled is False
    assert pause_resume_button.label == "⏸️ Пауза"
    assert pause_resume_button.style == discord.ButtonStyle.secondary

    skip_button = discord.utils.get(player_control_view.children, custom_id="music:skip")
    assert skip_button is not None
    assert skip_button.disabled is False

    stop_button = discord.utils.get(player_control_view.children, custom_id="music:stop")
    assert stop_button is not None
    assert stop_button.disabled is False


def test_update_buttons_paused(player_control_view, mock_music_player):
    """Тестирует обновление кнопок при паузе."""
    # Устанавливаем состояние паузы
    mock_music_player.is_playing = True
    mock_music_player.is_paused = True
    mock_music_player.current_track = MagicMock()

    # Вызываем _update_buttons
    player_control_view._update_buttons()

    # Проверяем состояние кнопок
    pause_resume_button = discord.utils.get(
        player_control_view.children, custom_id="music:pause_resume"
    )
    assert pause_resume_button is not None
    assert pause_resume_button.disabled is False
    assert pause_resume_button.label == "▶️ Продолжить"
    assert pause_resume_button.style == discord.ButtonStyle.green


def test_update_buttons_no_track(player_control_view, mock_music_player):
    """Тестирует обновление кнопок без текущего трека."""
    # Устанавливаем состояние без трека
    mock_music_player.is_playing = False
    mock_music_player.is_paused = False
    mock_music_player.current_track = None

    # Вызываем _update_buttons
    player_control_view._update_buttons()

    # Проверяем состояние кнопок
    pause_resume_button = discord.utils.get(
        player_control_view.children, custom_id="music:pause_resume"
    )
    assert pause_resume_button is not None
    assert pause_resume_button.disabled is True

    skip_button = discord.utils.get(player_control_view.children, custom_id="music:skip")
    assert skip_button is not None
    assert skip_button.disabled is True


@pytest.mark.asyncio
async def test_check_voice_channel_success(
    player_control_view, mock_interaction, mock_music_player
):
    """Тестирует успешную проверку голосового канала."""
    # Устанавливаем voice_client
    mock_music_player.voice_client.channel = mock_interaction.user.voice.channel

    # Вызываем _check_voice_channel
    result = await player_control_view._check_voice_channel(mock_interaction)

    # Проверяем результат
    assert result is True
    mock_interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_voice_channel_not_in_voice(player_control_view, mock_interaction):
    """Тестирует проверку голосового канала, когда пользователь не в голосовом канале."""
    # Устанавливаем отсутствие голосового канала
    mock_interaction.user.voice = None

    # Вызываем _check_voice_channel
    result = await player_control_view._check_voice_channel(mock_interaction)

    # Проверяем результат
    assert result is False
    mock_interaction.response.send_message.assert_awaited_once()
    assert (
        "Вы должны быть в голосовом канале"
        in mock_interaction.response.send_message.call_args.args[0]
    )


@pytest.mark.asyncio
async def test_check_voice_channel_different_channel(
    player_control_view, mock_interaction, mock_music_player
):
    """Тестирует проверку голосового канала, когда пользователь в другом канале."""
    # Устанавливаем разные каналы
    different_channel = MagicMock(spec=discord.VoiceChannel)
    different_channel.id = 999999
    mock_music_player.voice_client.channel = different_channel

    # Вызываем _check_voice_channel
    result = await player_control_view._check_voice_channel(mock_interaction)

    # Проверяем результат
    assert result is False
    mock_interaction.response.send_message.assert_awaited_once()
    assert (
        "Вы должны быть в том же голосовом канале"
        in mock_interaction.response.send_message.call_args.args[0]
    )


@pytest.mark.asyncio
async def test_pause_resume_button_pause(player_control_view, mock_interaction, mock_music_player):
    """Тестирует кнопку паузы."""
    # Устанавливаем состояние воспроизведения
    mock_music_player.is_paused = False

    # Мокаем _check_voice_channel
    player_control_view._check_voice_channel = AsyncMock(return_value=True)

    # Вызываем callback кнопки
    button = discord.utils.get(player_control_view.children, custom_id="music:pause_resume")
    await button.callback(mock_interaction)

    # Проверяем вызовы
    player_control_view._check_voice_channel.assert_awaited_once_with(mock_interaction)
    mock_music_player.pause.assert_awaited_once_with(mock_interaction)
    mock_music_player.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_pause_resume_button_resume(player_control_view, mock_interaction, mock_music_player):
    """Тестирует кнопку возобновления."""
    # Устанавливаем состояние паузы
    mock_music_player.is_paused = True

    # Мокаем _check_voice_channel
    player_control_view._check_voice_channel = AsyncMock(return_value=True)

    # Вызываем callback кнопки
    button = discord.utils.get(player_control_view.children, custom_id="music:pause_resume")
    await button.callback(mock_interaction)

    # Проверяем вызовы
    player_control_view._check_voice_channel.assert_awaited_once_with(mock_interaction)
    mock_music_player.resume.assert_awaited_once_with(mock_interaction)
    mock_music_player.pause.assert_not_awaited()


@pytest.mark.asyncio
async def test_skip_button(player_control_view, mock_interaction, mock_music_player):
    """Тестирует кнопку пропуска."""
    # Мокаем _check_voice_channel
    player_control_view._check_voice_channel = AsyncMock(return_value=True)

    # Вызываем callback кнопки
    button = discord.utils.get(player_control_view.children, custom_id="music:skip")
    await button.callback(mock_interaction)

    # Проверяем вызовы
    player_control_view._check_voice_channel.assert_awaited_once_with(mock_interaction)
    mock_music_player.skip.assert_awaited_once_with(mock_interaction)


@pytest.mark.asyncio
async def test_stop_button(player_control_view, mock_interaction, mock_music_player):
    """Тестирует кнопку остановки."""
    # Мокаем _check_voice_channel
    player_control_view._check_voice_channel = AsyncMock(return_value=True)

    # Вызываем callback кнопки
    button = discord.utils.get(player_control_view.children, custom_id="music:stop")
    await button.callback(mock_interaction)

    # Проверяем вызовы
    player_control_view._check_voice_channel.assert_awaited_once_with(mock_interaction)
    mock_music_player.stop.assert_awaited_once_with(mock_interaction)


@pytest.mark.asyncio
async def test_queue_button(player_control_view, mock_interaction, mock_music_player):
    """Тестирует кнопку очереди."""
    # Вызываем callback кнопки
    button = discord.utils.get(player_control_view.children, custom_id="music:queue")
    await button.callback(mock_interaction)

    # Проверяем вызовы
    mock_music_player.show_queue.assert_awaited_once_with(mock_interaction)


@pytest.mark.asyncio
async def test_on_timeout(player_control_view, mock_music_player):
    """Тестирует обработку таймаута."""
    # Устанавливаем now_playing_message
    mock_message = MagicMock(spec=discord.Message)
    mock_message.edit = AsyncMock()
    mock_music_player.now_playing_message = mock_message
    player_control_view.player = mock_music_player

    # Вызываем on_timeout
    await player_control_view.on_timeout()

    # Проверяем вызовы
    mock_message.edit.assert_awaited_once_with(view=None)


# --- Тесты для SearchResultSelect ---


def test_search_result_select_initialization(
    search_result_select, mock_music_player, mock_interaction, search_entries
):
    """Тестирует инициализацию SearchResultSelect."""
    assert search_result_select.player is mock_music_player
    assert search_result_select.original_interaction is mock_interaction
    assert search_result_select.entries is search_entries
    assert len(search_result_select.options) == len(search_entries)

    # Проверяем опции
    for i, option in enumerate(search_result_select.options):
        assert option.value == str(i)
        assert search_entries[i]["title"] in option.label
        assert search_entries[i]["uploader"] in option.description


def test_search_result_select_long_title(mock_music_player, mock_interaction):
    """Тестирует обработку длинных названий треков."""
    # Создаем запись с длинным названием
    long_title = "A" * 150
    entries = [
        {
            "id": "test_id",
            "title": long_title,
            "webpage_url": "https://www.youtube.com/watch?v=test_id",
            "duration": 180,
            "uploader": "Test Uploader",
        }
    ]

    # Создаем SearchResultSelect
    select = SearchResultSelect(mock_music_player, mock_interaction, entries)

    # Проверяем, что название было обрезано
    assert len(select.options[0].label) <= 100
    assert select.options[0].label.endswith("...")


@pytest.mark.asyncio
async def test_search_result_select_callback(
    search_result_select, mock_interaction, mock_music_player, search_entries
):
    """Тестирует callback выбора результата поиска."""
    from unittest.mock import PropertyMock

    with patch.object(type(search_result_select), "values", PropertyMock(return_value=["0"])):
        await search_result_select.callback(mock_interaction)
        mock_interaction.message.delete.assert_awaited_once()
        mock_music_player.connect.assert_awaited_once_with(mock_interaction.user.voice.channel)
        mock_interaction.response.send_message.assert_awaited_once()
        assert "Добавляем" in mock_interaction.response.send_message.call_args.args[0]
        mock_music_player.queue_track.assert_awaited_once_with(
            search_entries[0]["webpage_url"], mock_interaction.user, mock_interaction
        )
    # Не вызываем callback второй раз — иначе .values будет пустым

    # Проверяем вызовы
    mock_interaction.message.delete.assert_awaited_once()
    mock_music_player.connect.assert_awaited_once_with(mock_interaction.user.voice.channel)
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Добавляем" in mock_interaction.response.send_message.call_args.args[0]
    mock_music_player.queue_track.assert_awaited_once_with(
        search_entries[0]["webpage_url"], mock_interaction.user, mock_interaction
    )


@pytest.mark.asyncio
async def test_search_result_select_callback_invalid_index(search_result_select, mock_interaction):
    """Тестирует callback с неверным индексом."""
    from unittest.mock import PropertyMock

    with patch.object(type(search_result_select), "values", PropertyMock(return_value=["99"])):
        await search_result_select.callback(mock_interaction)
        mock_interaction.message.delete.assert_awaited_once()
        mock_interaction.response.send_message.assert_awaited_once()
        assert "Неверный выбор" in mock_interaction.response.send_message.call_args.args[0]
    # Не вызываем callback второй раз

    # Проверяем вызовы
    mock_interaction.message.delete.assert_awaited_once()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Неверный выбор" in mock_interaction.response.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_search_result_select_callback_cancel(search_result_select, mock_interaction):
    """Тестирует отмену выбора результата поиска."""
    from unittest.mock import PropertyMock

    with patch.object(type(search_result_select), "values", PropertyMock(return_value=["-1"])):
        await search_result_select.callback(mock_interaction)
        mock_interaction.message.delete.assert_awaited_once()
        mock_interaction.response.send_message.assert_awaited_once()
        assert "Поиск отменен" in mock_interaction.response.send_message.call_args.args[0]
    # Не вызываем callback второй раз

    # Проверяем вызовы
    mock_interaction.message.delete.assert_awaited_once()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Поиск отменен" in mock_interaction.response.send_message.call_args.args[0]


# --- Тесты для SearchView ---


def test_search_view_initialization(
    search_view, mock_music_player, mock_interaction, search_entries
):
    """Тестирует инициализацию SearchView."""
    assert search_view.player is mock_music_player
    assert search_view.original_interaction is mock_interaction
    assert len(search_view.children) == 1  # Один элемент Select
    assert isinstance(search_view.children[0], SearchResultSelect)


@pytest.mark.asyncio
async def test_search_view_on_timeout(search_view, mock_interaction):
    """Тестирует обработку таймаута SearchView."""
    # Вызываем on_timeout
    await search_view.on_timeout()

    # Проверяем вызовы
    mock_interaction.edit_original_response.assert_awaited_once()
    # Проверяем, что был вызов с content="Время выбора трека истекло"
    call_args = mock_interaction.edit_original_response.call_args
    content = ""
    if call_args.args:
        content = call_args.args[0]
    elif "content" in call_args.kwargs:
        content = call_args.kwargs["content"]
    assert "Время выбора трека истекло" in content
    assert mock_interaction.edit_original_response.call_args.kwargs["view"] is None


@pytest.mark.asyncio
async def test_search_view_interaction_check_same_user(search_view, mock_interaction):
    """Тестирует проверку взаимодействия с тем же пользователем."""
    # Устанавливаем того же пользователя
    mock_interaction.user.id = search_view.original_interaction.user.id

    # Вызываем interaction_check
    result = await search_view.interaction_check(mock_interaction)

    # Проверяем результат
    assert result is True
    mock_interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_view_interaction_check_different_user(search_entries, mock_music_player):
    """Тестирует проверку взаимодействия с другим пользователем."""
    from unittest.mock import MagicMock

    # Создаем original_interaction с одним пользователем
    original_interaction = MagicMock(spec=discord.Interaction)
    original_user = MagicMock(spec=discord.Member)
    original_user.id = 1
    original_interaction.user = original_user

    # Создаем search_view с этим original_interaction
    view = SearchView(mock_music_player, original_interaction, search_entries)

    # Создаем новый interaction с другим пользователем
    test_interaction = MagicMock(spec=discord.Interaction)
    other_user = MagicMock(spec=discord.Member)
    other_user.id = 999
    test_interaction.user = other_user
    test_interaction.response = MagicMock()
    test_interaction.response.send_message = AsyncMock()

    # Вызываем interaction_check
    result = await view.interaction_check(test_interaction)

    # Проверяем результат
    assert result is False
    test_interaction.response.send_message.assert_awaited_once()
    assert (
        "Только пользователь, запустивший поиск"
        in test_interaction.response.send_message.call_args.args[0]
    )
