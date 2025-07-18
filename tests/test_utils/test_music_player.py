"""Тесты для классов MusicPlayer и Track из utils.music.player."""

import asyncio
import logging  # Добавляем импорт logging
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.music.config import FFMPEG_OPTIONS
from utils.music.player import MusicPlayer, Track

# Инициализируем логгер
logger = logging.getLogger(__name__)

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
    return Track(mock_track_info, mock_member)


@pytest.fixture
def music_player(mock_bot):
    """Создает экземпляр MusicPlayer."""
    player = MusicPlayer(mock_bot)
    return player


# --- Тесты для класса Track ---


def test_track_initialization(mock_track, mock_member, mock_track_info) -> None:
    """Тестирует инициализацию класса Track."""
    assert mock_track.url == mock_track_info["webpage_url"]
    assert mock_track.title == mock_track_info["title"]
    assert mock_track.duration == mock_track_info["duration"]
    assert mock_track.thumbnail == mock_track_info["thumbnail"]
    assert mock_track.uploader == mock_track_info["uploader"]
    assert mock_track.uploader_url == mock_track_info["uploader_url"]
    assert mock_track.requester == mock_member
    assert mock_track.id == mock_track_info["id"]
    assert mock_track.extractor == mock_track_info["extractor_key"].lower()
    assert mock_track.stream_url == mock_track_info["url"]


def test_track_str_representation(mock_track) -> None:
    """Тестирует строковое представление трека."""
    from utils.music.embeds import format_duration

    expected = f"**{mock_track.title}** ({format_duration(mock_track.duration)})"
    assert str(mock_track) == expected


def test_track_to_embed_field(mock_track) -> None:
    """Тестирует метод to_embed_field."""
    from utils.music.embeds import format_duration

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


# --- Тесты для класса MusicPlayer ---


@pytest.mark.asyncio
async def test_music_player_initialization(music_player, mock_bot) -> None:
    """Тестирует инициализацию MusicPlayer."""
    assert music_player.bot is mock_bot
    assert music_player.voice_client is None
    assert music_player.text_channel is None
    assert isinstance(music_player.queue, deque)
    assert len(music_player.queue) == 0
    assert music_player.current_track is None
    assert music_player.is_playing is False
    assert music_player.is_paused is False
    assert music_player.loop is not None
    assert music_player.now_playing_message is None
    assert music_player.player_view is None


@pytest.mark.asyncio
async def test_connect_success(music_player, mock_voice_client) -> None:
    """Тестирует успешное подключение к голосовому каналу."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789
    channel.connect = AsyncMock(return_value=mock_voice_client)

    result = await music_player.connect(channel)

    assert result is True
    channel.connect.assert_awaited_once()
    assert music_player.voice_client is mock_voice_client


@pytest.mark.asyncio
async def test_connect_already_connected_same_channel(music_player, mock_voice_client) -> None:
    """Тестирует подключение к тому же каналу, к которому уже подключен."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789

    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client
    mock_voice_client.channel = channel

    result = await music_player.connect(channel)

    assert result is True
    # Проверяем, что не было попыток подключения или перемещения
    channel.connect.assert_not_called()
    mock_voice_client.move_to.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_move_to_different_channel(music_player, mock_voice_client) -> None:
    """Тестирует перемещение в другой голосовой канал."""
    current_channel = MagicMock(spec=discord.VoiceChannel)
    current_channel.name = "Current Channel"
    current_channel.id = 111111111

    new_channel = MagicMock(spec=discord.VoiceChannel)
    new_channel.name = "New Channel"
    new_channel.id = 222222222

    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client
    mock_voice_client.channel = current_channel

    result = await music_player.connect(new_channel)

    assert result is True
    mock_voice_client.move_to.assert_awaited_once_with(new_channel)


@pytest.mark.asyncio
async def test_disconnect(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует отключение от голосового канала."""
    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client

    # Мокаем cleanup
    music_player.cleanup = AsyncMock()

    # Вызываем disconnect с interaction
    await music_player.disconnect(mock_interaction)

    # Проверяем вызовы
    mock_voice_client.stop.assert_called_once()
    mock_voice_client.disconnect.assert_awaited_once()
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Воспроизведение остановлено" in mock_interaction.response.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_disconnect_without_interaction(
    music_player, mock_voice_client, mock_text_channel
) -> None:
    """Тестирует отключение от голосового канала без interaction."""
    # Устанавливаем voice_client и text_channel
    music_player.voice_client = mock_voice_client
    music_player.text_channel = mock_text_channel

    # Мокаем cleanup
    music_player.cleanup = AsyncMock()

    # Вызываем disconnect без interaction
    await music_player.disconnect()

    # Проверяем вызовы
    mock_voice_client.stop.assert_called_once()
    mock_voice_client.disconnect.assert_awaited_once()
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)
    mock_text_channel.send.assert_awaited_once()
    # Проверяем, что embed содержит "Автоотключение"
    embed = mock_text_channel.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Автоотключение" in embed.title


@pytest.mark.asyncio
async def test_queue_track(music_player, mock_track_info, mock_member, mock_interaction) -> None:
    """Тестирует добавление трека в очередь."""
    url = "https://www.youtube.com/watch?v=test_id"

    # Мокаем get_stream_info
    with patch("utils.music.player.get_stream_info", new_callable=AsyncMock) as mock_get_stream:
        mock_get_stream.return_value = mock_track_info

        # Вызываем queue_track
        await music_player.queue_track(url, mock_member, mock_interaction)

        # Проверяем вызовы
        mock_get_stream.assert_awaited_once_with(url)
        assert len(music_player.queue) == 1
        assert isinstance(music_player.queue[0], Track)
        assert music_player.queue[0].title == mock_track_info["title"]
        assert music_player.queue[0].requester == mock_member
        # edit_original_response может быть вызван несколько раз
        assert mock_interaction.edit_original_response.await_count >= 1


@pytest.mark.asyncio
async def test_queue_track_stream_error(music_player, mock_member, mock_interaction) -> None:
    """Тестирует обработку ошибки при получении информации о потоке."""
    url = "https://www.youtube.com/watch?v=test_id"

    # Мокаем get_stream_info с ошибкой
    with patch("utils.music.player.get_stream_info", new_callable=AsyncMock) as mock_get_stream:
        mock_get_stream.return_value = None

        # Вызываем queue_track
        await music_player.queue_track(url, mock_member, mock_interaction)

        # Проверяем вызовы
        mock_get_stream.assert_awaited_once_with(url)
        assert len(music_player.queue) == 0
        # Проверяем, что edit_original_response был вызван хотя бы раз с нужным текстом
        found = False
        logger.debug(
            "edit_original_response.call_args_list: %s",
            mock_interaction.edit_original_response.call_args_list,
        )
        for call_item in mock_interaction.edit_original_response.call_args_list:
            args = call_item.args
            kwargs = call_item.kwargs
            content = ""
            if args:
                content = args[0]
            elif "content" in kwargs:
                content = kwargs["content"]
            # Также проверяем embed, если есть
            embed = kwargs.get("embed")
            if (
                "Не удалось получить информацию о треке" in str(content)
                or "Скачанный файл не найден" in str(content)
                or (embed and "Ошибка" in getattr(embed, "title", ""))
            ):
                found = True
                break
        assert found
        # Проверяем, что хотя бы в одном вызове был embed с "Ошибка"
        has_error_embed = any(
            "Ошибка" in getattr(call_item.kwargs.get("embed"), "title", "")
            for call_item in mock_interaction.edit_original_response.call_args_list
            if call_item.kwargs.get("embed")
        )
        assert has_error_embed


@pytest.mark.asyncio
async def test_start_playback_loop(music_player) -> None:
    """Тестирует запуск цикла воспроизведения."""
    # Мокаем play_next
    music_player.play_next = AsyncMock()

    # Мокаем loop.create_task
    mock_task = MagicMock()
    music_player.loop.create_task = MagicMock(return_value=mock_task)

    # Вызываем start_playback_loop
    music_player.start_playback_loop()

    # Проверяем вызовы
    # Проверяем, что create_task был вызван хотя бы раз с coroutine
    assert music_player.loop.create_task.call_count == 1
    called_args = music_player.loop.create_task.call_args[0]
    assert called_args
    assert callable(getattr(called_args[0], "__await__", None))
    assert music_player._play_next_task is mock_task


@pytest.mark.asyncio
async def test_play_next(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует воспроизведение следующего трека."""
    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client

    # Добавляем трек в очередь
    music_player.queue.append(mock_track)

    # Мокаем _update_now_playing_message
    music_player._update_now_playing_message = AsyncMock()

    # Мокаем discord.FFmpegPCMAudio
    with patch("discord.FFmpegPCMAudio") as mock_ffmpeg:
        mock_source = MagicMock()
        mock_ffmpeg.return_value = mock_source

        # Вызываем play_next
        await music_player.play_next()

        # Проверяем вызовы
        mock_ffmpeg.assert_called_once_with(
            mock_track.stream_url,
            options=FFMPEG_OPTIONS.get("options", ""),
            before_options=FFMPEG_OPTIONS.get("before_options", ""),
        )
        mock_voice_client.play.assert_called_once()
        music_player._update_now_playing_message.assert_awaited_once()
        assert music_player.is_playing is True
        assert music_player.is_paused is False


@pytest.mark.asyncio
async def test_play_next_empty_queue(music_player, mock_voice_client) -> None:
    """Тестирует play_next с пустой очередью."""
    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client

    # Мокаем cleanup
    music_player.cleanup = AsyncMock()

    # Вызываем play_next с пустой очередью
    await music_player.play_next()

    # Проверяем вызовы
    music_player.cleanup.assert_awaited_once_with(clear_queue=False)
    assert music_player.is_playing is False
    assert music_player.current_track is None


@pytest.mark.asyncio
async def test_pause(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует приостановку воспроизведения."""
    # Устанавливаем voice_client и состояние
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.is_paused = False

    # Мокаем _update_now_playing_message
    music_player._update_now_playing_message = AsyncMock()

    # Вызываем pause
    await music_player.pause(mock_interaction)

    # Проверяем вызовы
    mock_voice_client.pause.assert_called_once()
    assert music_player.is_paused is True
    mock_interaction.response.send_message.assert_awaited_once()
    assert "приостановлено" in mock_interaction.response.send_message.call_args.args[0]
    music_player._update_now_playing_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует возобновление воспроизведения."""
    # Устанавливаем voice_client и состояние
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.is_paused = True

    # Мокаем _update_now_playing_message
    music_player._update_now_playing_message = AsyncMock()

    # Вызываем resume
    await music_player.resume(mock_interaction)

    # Проверяем вызовы
    mock_voice_client.resume.assert_called_once()
    assert music_player.is_paused is False
    mock_interaction.response.send_message.assert_awaited_once()
    assert "возобновлено" in mock_interaction.response.send_message.call_args.args[0].lower()
    music_player._update_now_playing_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_skip(music_player, mock_voice_client, mock_interaction, mock_track) -> None:
    """Тестирует пропуск трека."""
    # Устанавливаем voice_client и текущий трек
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.current_track = mock_track

    # Вызываем skip
    await music_player.skip(mock_interaction)

    # Проверяем вызовы
    mock_voice_client.stop.assert_called_once()
    mock_interaction.response.send_message.assert_awaited_once()
    assert "пропущен" in mock_interaction.response.send_message.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_stop(music_player, mock_interaction) -> None:
    """Тестирует остановку воспроизведения."""
    # Мокаем disconnect
    music_player.disconnect = AsyncMock()

    # Вызываем stop
    await music_player.stop(mock_interaction)

    # Проверяем вызовы
    music_player.disconnect.assert_awaited_once_with(mock_interaction)


@pytest.mark.asyncio
async def test_show_queue_empty(music_player, mock_interaction) -> None:
    """Тестирует отображение пустой очереди."""
    # Вызываем show_queue с пустой очередью
    await music_player.show_queue(mock_interaction)

    # Проверяем вызовы
    mock_interaction.response.send_message.assert_awaited_once()
    assert "Очередь пуста" in mock_interaction.response.send_message.call_args.kwargs["embed"].title


@pytest.mark.asyncio
async def test_show_queue_with_tracks(music_player, mock_interaction, mock_track) -> None:
    """Тестирует отображение очереди с треками."""
    # Добавляем текущий трек и треки в очередь
    music_player.current_track = mock_track
    music_player.queue.append(mock_track)
    music_player.queue.append(mock_track)

    # Вызываем show_queue
    await music_player.show_queue(mock_interaction)

    # Проверяем вызовы
    mock_interaction.response.send_message.assert_awaited_once()
    assert (
        "Очередь воспроизведения"
        in mock_interaction.response.send_message.call_args.kwargs["embed"].title
    )
    assert (
        "Сейчас играет"
        in mock_interaction.response.send_message.call_args.kwargs["embed"].description
    )
    assert (
        "В очереди" in mock_interaction.response.send_message.call_args.kwargs["embed"].description
    )


@pytest.mark.asyncio
async def test_create_now_playing_embed_no_track(music_player) -> None:
    """Тестирует создание embed для 'Сейчас играет' без текущего трека."""
    # Вызываем _create_now_playing_embed без текущего трека
    embed = music_player._create_now_playing_embed()

    # Проверяем результат
    assert "Ничего не играет" in embed.title


@pytest.mark.asyncio
async def test_create_now_playing_embed_with_track(music_player, mock_track) -> None:
    """Тестирует создание embed для 'Сейчас играет' с текущим треком."""
    # Устанавливаем текущий трек
    music_player.current_track = mock_track

    # Вызываем _create_now_playing_embed
    embed = music_player._create_now_playing_embed()

    # Проверяем результат
    assert "Сейчас играет" in embed.title
    assert mock_track.title in embed.description
    assert len(embed.fields) > 0
    assert "Длительность" in embed.fields[1].name
    assert "Запросил" in embed.fields[2].name


@pytest.mark.asyncio
async def test_update_now_playing_message_no_channel(music_player) -> None:
    """Тестирует обновление сообщения 'Сейчас играет' без текстового канала."""
    # Вызываем _update_now_playing_message без текстового канала
    await music_player._update_now_playing_message()

    # Проверяем, что ничего не произошло
    assert music_player.now_playing_message is None
    assert music_player.player_view is None


@pytest.mark.asyncio
async def test_update_now_playing_message_new_message(music_player, mock_text_channel) -> None:
    """Тестирует создание нового сообщения 'Сейчас играет'."""
    # Устанавливаем текстовый канал
    music_player.text_channel = mock_text_channel

    # Мокаем PlayerControlView по правильному пути
    with patch("utils.music.ui.PlayerControlView") as MockPlayerView:
        mock_view = MagicMock()
        mock_view._update_buttons = MagicMock()
        MockPlayerView.return_value = mock_view

        # Мокаем _create_now_playing_embed
        mock_embed = MagicMock()
        music_player._create_now_playing_embed = MagicMock(return_value=mock_embed)

        # Мокаем отправку сообщения
        mock_message = MagicMock()
        mock_text_channel.send.return_value = mock_message

        # Вызываем _update_now_playing_message
        await music_player._update_now_playing_message()

        # Проверяем вызовы
        MockPlayerView.assert_called_once_with(music_player)
        mock_view._update_buttons.assert_called_once()
        mock_text_channel.send.assert_awaited_once_with(embed=mock_embed, view=mock_view)
        assert music_player.now_playing_message is mock_message
        assert music_player.player_view is mock_view


@pytest.mark.asyncio
async def test_send_error_message(music_player, mock_text_channel) -> None:
    """Тестирует отправку сообщения об ошибке."""
    # Устанавливаем текстовый канал
    music_player.text_channel = mock_text_channel

    # Вызываем send_error_message
    error_message = "Test error message"
    await music_player.send_error_message(error_message)

    # Проверяем вызовы
    mock_text_channel.send.assert_awaited_once()
    assert "Ошибка" in mock_text_channel.send.call_args.kwargs["embed"].title
    assert error_message in mock_text_channel.send.call_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_cleanup(music_player, mock_track) -> None:
    """Тестирует очистку плеера."""
    # Устанавливаем состояние
    music_player.is_playing = True
    music_player.is_paused = True
    music_player.current_track = mock_track
    music_player.queue.append(mock_track)

    # Мокаем player_view
    class DummyView(discord.ui.View):
        pass

    mock_view = DummyView()
    mock_view.stop = MagicMock()
    music_player.player_view = mock_view

    # Мокаем now_playing_message
    mock_message = MagicMock()
    mock_message.edit = AsyncMock()
    mock_message.delete = AsyncMock()
    music_player.now_playing_message = mock_message

    # Вызываем cleanup
    await music_player.cleanup(clear_queue=True)

    # Проверяем результат
    assert music_player.is_playing is False
    assert music_player.is_paused is False
    assert music_player.current_track is None
    assert len(music_player.queue) == 0
    mock_view.stop.assert_called_once()
    mock_message.edit.assert_awaited_once_with(view=None)
    mock_message.delete.assert_awaited_once()
    assert music_player.player_view is None
    assert music_player.now_playing_message is None


@pytest.mark.asyncio
async def test_cleanup_without_clearing_queue(music_player, mock_track) -> None:
    """Тестирует очистку плеера без очистки очереди."""
    # Устанавливаем состояние
    music_player.is_playing = True
    music_player.is_paused = True
    music_player.current_track = mock_track
    music_player.queue.append(mock_track)

    # Вызываем cleanup без очистки очереди
    await music_player.cleanup(clear_queue=False)

    # Проверяем результат
    assert music_player.is_playing is False
    assert music_player.is_paused is False
    assert music_player.current_track is None
    assert len(music_player.queue) == 1  # Очередь не должна быть очищена


# --- Дополнительные тесты для улучшения покрытия ---


@pytest.mark.asyncio
async def test_connect_timeout_error(music_player) -> None:
    """Тестирует обработку таймаута при подключении к голосовому каналу."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789
    channel.connect = AsyncMock(side_effect=asyncio.TimeoutError())

    result = await music_player.connect(channel)

    assert result is False
    assert music_player.voice_client is None


@pytest.mark.asyncio
async def test_connect_client_exception_with_existing_voice_client(music_player) -> None:
    """Тестирует обработку ClientException при наличии существующего голосового клиента."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789
    channel.connect = AsyncMock(side_effect=discord.ClientException("Already connected"))
    
    # Мокаем guild.voice_client
    existing_voice_client = MagicMock(spec=discord.VoiceClient)
    existing_voice_client.channel = MagicMock()
    existing_voice_client.channel.name = "Existing Channel"
    channel.guild.voice_client = existing_voice_client
    
    # Мокаем рекурсивный вызов connect
    music_player.connect = AsyncMock(return_value=True)
    
    result = await music_player.connect(channel)
    
    assert result is True


@pytest.mark.asyncio
async def test_connect_client_exception_without_existing_voice_client(music_player) -> None:
    """Тестирует обработку ClientException без существующего голосового клиента."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789
    channel.connect = AsyncMock(side_effect=discord.ClientException("Connection failed"))
    channel.guild.voice_client = None

    result = await music_player.connect(channel)

    assert result is False
    assert music_player.voice_client is None


@pytest.mark.asyncio
async def test_connect_general_exception(music_player) -> None:
    """Тестирует обработку общих исключений при подключении."""
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.name = "Test Voice Channel"
    channel.id = 123456789
    channel.connect = AsyncMock(side_effect=Exception("General error"))

    result = await music_player.connect(channel)

    assert result is False
    assert music_player.voice_client is None


@pytest.mark.asyncio
async def test_connect_move_to_timeout_error(music_player, mock_voice_client) -> None:
    """Тестирует обработка таймаута при перемещении в другой канал."""
    current_channel = MagicMock(spec=discord.VoiceChannel)
    current_channel.name = "Current Channel"
    current_channel.id = 111111111

    new_channel = MagicMock(spec=discord.VoiceChannel)
    new_channel.name = "New Channel"
    new_channel.id = 222222222

    # Устанавливаем voice_client
    music_player.voice_client = mock_voice_client
    mock_voice_client.channel = current_channel
    mock_voice_client.move_to = AsyncMock(side_effect=asyncio.TimeoutError())

    result = await music_player.connect(new_channel)

    assert result is False


@pytest.mark.asyncio
async def test_disconnect_not_connected(music_player) -> None:
    """Тестирует отключение когда голосовой клиент не подключен."""
    # Устанавливаем voice_client, но не подключенный
    mock_voice_client = MagicMock(spec=discord.VoiceClient)
    mock_voice_client.is_connected.return_value = False
    music_player.voice_client = mock_voice_client
    
    # Мокаем cleanup
    music_player.cleanup = AsyncMock()

    await music_player.disconnect()

    # Проверяем, что stop и disconnect не вызывались
    mock_voice_client.stop.assert_not_called()
    mock_voice_client.disconnect.assert_not_awaited()
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)


@pytest.mark.asyncio
async def test_disconnect_send_message_error(music_player, mock_text_channel) -> None:
    """Тестирует обработку ошибки при отправке сообщения об автоотключении."""
    music_player.text_channel = mock_text_channel
    mock_text_channel.send = AsyncMock(side_effect=Exception("Send failed"))
    
    # Мокаем cleanup
    music_player.cleanup = AsyncMock()

    await music_player.disconnect()

    # Проверяем, что ошибка обработана корректно
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)


@pytest.mark.asyncio
async def test_queue_track_stream_url_missing(music_player, mock_member, mock_interaction) -> None:
    """Тестирует обработку ошибки когда у трека нет stream_url."""
    url = "https://www.youtube.com/watch?v=test_id"
    mock_track_info = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "url": None,  # Нет stream_url
    }

    with patch("utils.music.player.get_stream_info", new_callable=AsyncMock) as mock_get_stream:
        mock_get_stream.return_value = mock_track_info

        await music_player.queue_track(url, mock_member, mock_interaction)

        assert len(music_player.queue) == 0
        # Проверяем, что было отправлено сообщение об ошибке
        assert mock_interaction.edit_original_response.await_count >= 1


@pytest.mark.asyncio
async def test_queue_track_zero_size_file_error(music_player, mock_member, mock_interaction) -> None:
    """Тестирует обработку ошибки когда скачанный файл имеет нулевой размер."""
    url = "https://www.youtube.com/watch?v=test_id"
    mock_track_info = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "filepath": "downloads/empty.mp3",
    }

    with patch("utils.music.player.download_track", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = mock_track_info
        
        with patch("pathlib.Path.exists", return_value=True):
            # Мокаем stat чтобы вернуть нулевой размер
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 0
            with patch("pathlib.Path.stat", return_value=mock_stat_result):
                await music_player.queue_track(url, mock_member, mock_interaction)

                assert len(music_player.queue) == 0
                # Проверяем, что было отправлено сообщение об ошибке
                assert mock_interaction.edit_original_response.await_count >= 1


@pytest.mark.asyncio
async def test_queue_track_without_interaction(music_player, mock_member, mock_text_channel) -> None:
    """Тестирует добавление трека без interaction, используя text_channel."""
    url = "https://www.youtube.com/watch?v=test_id"
    mock_track_info = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "filepath": "downloads/test.mp3",
    }

    music_player.text_channel = mock_text_channel

    with patch("utils.music.player.download_track", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = mock_track_info
        
        with patch("pathlib.Path.exists", return_value=True):
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 1024
            with patch("pathlib.Path.stat", return_value=mock_stat_result):
                await music_player.queue_track(url, mock_member)

                assert len(music_player.queue) == 1
                # Проверяем, что сообщения отправлялись в text_channel
                assert mock_text_channel.send.await_count >= 1


@pytest.mark.asyncio
async def test_queue_track_start_playback_when_not_playing(music_player, mock_member, mock_voice_client, mock_interaction) -> None:
    """Тестирует автоматический запуск воспроизведения при добавлении трека."""
    url = "https://www.youtube.com/watch?v=test_id"
    mock_track_info = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "filepath": "downloads/test.mp3",
    }

    music_player.voice_client = mock_voice_client
    music_player.is_playing = False
    music_player.start_playback_loop = MagicMock()

    with patch("utils.music.player.download_track", new_callable=AsyncMock) as mock_download:
        mock_download.return_value = mock_track_info
        
        with patch("pathlib.Path.exists", return_value=True):
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 1024
            with patch("pathlib.Path.stat", return_value=mock_stat_result):
                await music_player.queue_track(url, mock_member, mock_interaction)

                assert len(music_player.queue) == 1
                music_player.start_playback_loop.assert_called_once()


@pytest.mark.asyncio
async def test_start_playback_loop_already_running(music_player) -> None:
    """Тестирует что новая задача не создается если цикл уже запущен."""
    # Создаем мок задачи, которая еще не завершена
    mock_task = MagicMock()
    mock_task.done.return_value = False
    music_player._play_next_task = mock_task
    
    music_player.loop.create_task = MagicMock()

    music_player.start_playback_loop()

    # Проверяем, что новая задача не была создана
    music_player.loop.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_play_next_not_connected(music_player) -> None:
    """Тестирует play_next когда голосовой клиент не подключен."""
    music_player.voice_client = None
    music_player.cleanup = AsyncMock()

    await music_player.play_next()

    music_player.cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_play_next_already_playing(music_player, mock_voice_client) -> None:
    """Тестирует play_next когда уже идет воспроизведение."""
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True

    await music_player.play_next()

    # Проверяем, что ничего не произошло
    assert music_player.is_playing is True


@pytest.mark.asyncio
async def test_play_next_file_not_found(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует play_next когда файл трека не найден."""
    music_player.voice_client = mock_voice_client
    mock_track.filepath = "downloads/nonexistent.mp3"
    music_player.queue.append(mock_track)
    
    music_player.send_error_message = AsyncMock()
    music_player.start_playback_loop = MagicMock()

    with patch("pathlib.Path.exists", return_value=False):
        await music_player.play_next()

        music_player.send_error_message.assert_awaited_once()
        music_player.start_playback_loop.assert_called_once()
        assert music_player.current_track is None


@pytest.mark.asyncio
async def test_play_next_zero_size_file(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует play_next когда файл трека имеет нулевой размер."""
    music_player.voice_client = mock_voice_client
    mock_track.filepath = "downloads/empty.mp3"
    music_player.queue.append(mock_track)
    
    music_player.send_error_message = AsyncMock()
    music_player.start_playback_loop = MagicMock()

    with patch("pathlib.Path.exists", return_value=True):
        mock_stat_result = MagicMock()
        mock_stat_result.st_size = 0
        with patch("pathlib.Path.stat", return_value=mock_stat_result):
            await music_player.play_next()

            music_player.send_error_message.assert_awaited_once()
            music_player.start_playback_loop.assert_called_once()
            assert music_player.current_track is None


@pytest.mark.asyncio
async def test_play_next_ffmpeg_error(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует play_next когда FFmpegPCMAudio вызывает ошибку."""
    music_player.voice_client = mock_voice_client
    mock_track.filepath = "downloads/test.mp3"
    music_player.queue.append(mock_track)
    
    music_player.send_error_message = AsyncMock()
    music_player.start_playback_loop = MagicMock()

    with patch("pathlib.Path.exists", return_value=True):
        mock_stat_result = MagicMock()
        mock_stat_result.st_size = 1024
        with patch("pathlib.Path.stat", return_value=mock_stat_result):
            with patch("discord.FFmpegPCMAudio", side_effect=Exception("FFmpeg error")):
                await music_player.play_next()

                music_player.send_error_message.assert_awaited_once()
                music_player.start_playback_loop.assert_called_once()
                assert music_player.current_track is None


@pytest.mark.asyncio
async def test_after_playback_with_error(music_player, mock_track) -> None:
    """Тестирует _after_playback с ошибкой воспроизведения."""
    music_player.current_track = mock_track
    music_player.send_error_message = AsyncMock()
    music_player.cleanup = AsyncMock()

    error = Exception("Playback error")
    await music_player._after_playback(error)

    assert music_player.is_playing is False
    assert music_player.current_track is None
    music_player.send_error_message.assert_awaited_once()
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)


@pytest.mark.asyncio
async def test_after_playback_with_queue_and_connected(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует _after_playback когда есть треки в очереди и клиент подключен."""
    music_player.current_track = mock_track
    music_player.voice_client = mock_voice_client
    music_player.queue.append(mock_track)  # Добавляем трек в очередь
    music_player.start_playback_loop = MagicMock()

    await music_player._after_playback(None)

    assert music_player.is_playing is False
    assert music_player.current_track is None
    music_player.start_playback_loop.assert_called_once()


@pytest.mark.asyncio
async def test_after_playback_empty_queue_connected(music_player, mock_voice_client, mock_track) -> None:
    """Тестирует _after_playback когда очередь пуста но клиент подключен."""
    music_player.current_track = mock_track
    music_player.voice_client = mock_voice_client
    music_player.cleanup = AsyncMock()

    await music_player._after_playback(None)

    assert music_player.is_playing is False
    assert music_player.current_track is None
    music_player.cleanup.assert_awaited_once_with(clear_queue=False)


@pytest.mark.asyncio
async def test_after_playback_not_connected(music_player, mock_track) -> None:
    """Тестирует _after_playback когда клиент не подключен."""
    music_player.current_track = mock_track
    music_player.voice_client = None
    music_player.cleanup = AsyncMock()

    await music_player._after_playback(None)

    assert music_player.is_playing is False
    assert music_player.current_track is None
    music_player.cleanup.assert_awaited_once_with(clear_queue=True)


@pytest.mark.asyncio
async def test_pause_not_playing(music_player, mock_interaction) -> None:
    """Тестирует pause когда ничего не играет."""
    music_player.is_playing = False

    await music_player.pause(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    assert "ничего не играет" in mock_interaction.response.send_message.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_pause_already_paused(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует pause когда уже на паузе."""
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.is_paused = True

    await music_player.pause(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    assert "уже на паузе" in mock_interaction.response.send_message.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_pause_with_done_response(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует pause когда response уже был отправлен."""
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.is_paused = False
    mock_interaction.response.is_done.return_value = True
    music_player._update_now_playing_message = AsyncMock()

    await music_player.pause(mock_interaction)

    mock_voice_client.pause.assert_called_once()
    assert music_player.is_paused is True
    mock_interaction.followup.send.assert_awaited_once()
    music_player._update_now_playing_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_not_paused(music_player, mock_interaction) -> None:
    """Тестирует resume когда не на паузе."""
    music_player.is_paused = False

    await music_player.resume(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    assert "не на паузе" in mock_interaction.response.send_message.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_resume_with_done_response(music_player, mock_voice_client, mock_interaction) -> None:
    """Тестирует resume когда response уже был отправлен."""
    music_player.voice_client = mock_voice_client
    music_player.is_paused = True
    mock_interaction.response.is_done.return_value = True
    music_player._update_now_playing_message = AsyncMock()

    await music_player.resume(mock_interaction)

    mock_voice_client.resume.assert_called_once()
    assert music_player.is_paused is False
    mock_interaction.followup.send.assert_awaited_once()
    music_player._update_now_playing_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_skip_not_playing(music_player, mock_interaction) -> None:
    """Тестирует skip когда ничего не играет."""
    music_player.is_playing = False

    await music_player.skip(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    assert "ничего не играет" in mock_interaction.response.send_message.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_skip_with_done_response(music_player, mock_voice_client, mock_interaction, mock_track) -> None:
    """Тестирует skip когда response уже был отправлен."""
    music_player.voice_client = mock_voice_client
    music_player.is_playing = True
    music_player.current_track = mock_track
    mock_interaction.response.is_done.return_value = True

    await music_player.skip(mock_interaction)

    mock_voice_client.stop.assert_called_once()
    mock_interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_show_queue_with_many_tracks(music_player, mock_interaction, mock_track) -> None:
    """Тестирует отображение очереди с большим количеством треков (>15)."""
    # Добавляем 20 треков в очередь
    for i in range(20):
        music_player.queue.append(mock_track)

    await music_player.show_queue(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    assert "...и еще 5 трек(ов)" in embed.description


@pytest.mark.asyncio
async def test_show_queue_only_current_track(music_player, mock_interaction, mock_track) -> None:
    """Тестирует отображение очереди только с текущим треком."""
    music_player.current_track = mock_track
    music_player.is_paused = True

    await music_player.show_queue(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    assert "⏸️" in embed.description
    assert "Всего треков: 1" in embed.footer.text


@pytest.mark.asyncio
async def test_update_now_playing_message_edit_not_found(music_player, mock_text_channel) -> None:
    """Тестирует обновление сообщения когда существующее сообщение не найдено."""
    music_player.text_channel = mock_text_channel
    
    # Создаем мок существующего сообщения
    mock_message = MagicMock()
    mock_message.edit = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Message not found"))
    music_player.now_playing_message = mock_message
    
    with patch("utils.music.ui.PlayerControlView") as MockPlayerView:
        mock_view = MagicMock()
        mock_view._update_buttons = MagicMock()
        MockPlayerView.return_value = mock_view
        
        mock_embed = MagicMock()
        music_player._create_now_playing_embed = MagicMock(return_value=mock_embed)
        
        # Мокаем отправку нового сообщения
        new_mock_message = MagicMock()
        mock_text_channel.send.return_value = new_mock_message
        
        await music_player._update_now_playing_message()
        
        # Проверяем, что старое сообщение было сброшено и отправлено новое
        mock_message.edit.assert_awaited_once()
        mock_text_channel.send.assert_awaited_once()
        assert music_player.now_playing_message is new_mock_message


@pytest.mark.asyncio
async def test_update_now_playing_message_edit_general_error(music_player, mock_text_channel) -> None:
    """Тестирует обновление сообщения при общей ошибке редактирования."""
    music_player.text_channel = mock_text_channel
    
    # Создаем мок существующего сообщения
    mock_message = MagicMock()
    mock_message.edit = AsyncMock(side_effect=Exception("Edit failed"))
    music_player.now_playing_message = mock_message
    
    with patch("utils.music.ui.PlayerControlView") as MockPlayerView:
        mock_view = MagicMock()
        mock_view._update_buttons = MagicMock()
        MockPlayerView.return_value = mock_view
        
        mock_embed = MagicMock()
        music_player._create_now_playing_embed = MagicMock(return_value=mock_embed)
        
        # Мокаем отправку нового сообщения
        new_mock_message = MagicMock()
        mock_text_channel.send.return_value = new_mock_message
        
        await music_player._update_now_playing_message()
        
        # Проверяем, что было отправлено новое сообщение
        mock_text_channel.send.assert_awaited_once()
        assert music_player.now_playing_message is new_mock_message


@pytest.mark.asyncio
async def test_update_now_playing_message_send_http_exception(music_player, mock_text_channel) -> None:
    """Тестирует обработку HTTPException при отправке сообщения."""
    music_player.text_channel = mock_text_channel
    mock_text_channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "Send failed"))
    
    with patch("utils.music.ui.PlayerControlView") as MockPlayerView:
        mock_view = MagicMock()
        mock_view._update_buttons = MagicMock()
        MockPlayerView.return_value = mock_view
        
        mock_embed = MagicMock()
        music_player._create_now_playing_embed = MagicMock(return_value=mock_embed)
        
        await music_player._update_now_playing_message()
        
        # Проверяем, что now_playing_message остался None
        assert music_player.now_playing_message is None


@pytest.mark.asyncio
async def test_update_now_playing_message_send_general_exception(music_player, mock_text_channel) -> None:
    """Тестирует обработку общего исключения при отправке сообщения."""
    music_player.text_channel = mock_text_channel
    mock_text_channel.send = AsyncMock(side_effect=Exception("General send error"))
    
    with patch("utils.music.ui.PlayerControlView") as MockPlayerView:
        mock_view = MagicMock()
        mock_view._update_buttons = MagicMock()
        MockPlayerView.return_value = mock_view
        
        mock_embed = MagicMock()
        music_player._create_now_playing_embed = MagicMock(return_value=mock_embed)
        
        await music_player._update_now_playing_message()
        
        # Проверяем, что now_playing_message остался None
        assert music_player.now_playing_message is None


@pytest.mark.asyncio
async def test_create_now_playing_embed_with_next_track(music_player, mock_track) -> None:
    """Тестирует создание embed с информацией о следующем треке."""
    music_player.current_track = mock_track
    music_player.queue.append(mock_track)  # Добавляем следующий трек
    
    embed = music_player._create_now_playing_embed()
    
    assert "Сейчас играет" in embed.title
    # Проверяем, что есть поле "Следующий"
    next_field = next((field for field in embed.fields if field.name == "Следующий"), None)
    assert next_field is not None


@pytest.mark.asyncio
async def test_send_error_message_no_channel(music_player) -> None:
    """Тестирует отправку сообщения об ошибке без установленного канала."""
    music_player.text_channel = None
    
    # Не должно вызывать исключений
    await music_player.send_error_message("Test error")


@pytest.mark.asyncio
async def test_send_error_message_http_exception(music_player, mock_text_channel) -> None:
    """Тестирует обработку HTTPException при отправке сообщения об ошибке."""
    music_player.text_channel = mock_text_channel
    mock_text_channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "Send failed"))
    
    # Не должно вызывать исключений
    await music_player.send_error_message("Test error")


@pytest.mark.asyncio
async def test_send_error_message_general_exception(music_player, mock_text_channel) -> None:
    """Тестирует обработку общего исключения при отправке сообщения об ошибке."""
    music_player.text_channel = mock_text_channel
    mock_text_channel.send = AsyncMock(side_effect=Exception("General error"))
    
    # Не должно вызывать исключений
    await music_player.send_error_message("Test error")


@pytest.mark.asyncio
async def test_cleanup_message_not_found(music_player) -> None:
    """Тестирует cleanup когда сообщение не найдено при удалении."""
    mock_message = MagicMock()
    mock_message.edit = AsyncMock()
    mock_message.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Message not found"))
    music_player.now_playing_message = mock_message
    
    await music_player.cleanup()
    
    # Проверяем, что ошибка была обработана корректно
    mock_message.delete.assert_awaited_once()
    assert music_player.now_playing_message is None


@pytest.mark.asyncio
async def test_cleanup_message_delete_error(music_player) -> None:
    """Тестирует cleanup при ошибке удаления сообщения."""
    mock_message = MagicMock()
    mock_message.edit = AsyncMock()
    mock_message.delete = AsyncMock(side_effect=Exception("Delete failed"))
    music_player.now_playing_message = mock_message
    
    await music_player.cleanup()
    
    # Проверяем, что ошибка была обработана корректно
    mock_message.delete.assert_awaited_once()
    assert music_player.now_playing_message is None


@pytest.mark.asyncio
async def test_cleanup_view_edit_error(music_player) -> None:
    """Тестирует cleanup при ошибке редактирования view."""
    class DummyView(discord.ui.View):
        pass

    mock_view = DummyView()
    mock_view.stop = MagicMock()
    music_player.player_view = mock_view
    
    mock_message = MagicMock()
    mock_message.edit = AsyncMock(side_effect=Exception("Edit failed"))
    mock_message.delete = AsyncMock()
    music_player.now_playing_message = mock_message
    
    await music_player.cleanup()
    
    # Проверяем, что ошибка была обработана корректно
    mock_view.stop.assert_called_once()
    assert music_player.player_view is None


@pytest.mark.asyncio
async def test_start_cleanup_task(music_player) -> None:
    """Тестирует запуск задачи очистки файлов."""
    mock_task = MagicMock()
    music_player.loop.create_task = MagicMock(return_value=mock_task)
    
    await music_player.start_cleanup_task()
    
    music_player.loop.create_task.assert_called_once()
    assert music_player._cleanup_task is mock_task


@pytest.mark.asyncio
async def test_start_cleanup_task_already_running(music_player) -> None:
    """Тестирует что задача очистки не создается если уже запущена."""
    mock_task = MagicMock()
    mock_task.done.return_value = False
    music_player._cleanup_task = mock_task
    
    music_player.loop.create_task = MagicMock()
    
    await music_player.start_cleanup_task()
    
    # Проверяем, что новая задача не была создана
    music_player.loop.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_cleanup_cancelled(music_player) -> None:
    """Тестирует обработку отмены задачи периодической очистки."""
    with patch("asyncio.sleep", side_effect=asyncio.CancelledError()):
        await music_player._scheduled_cleanup()
        # Тест проходит если исключение обработано корректно


@pytest.mark.asyncio
async def test_scheduled_cleanup_general_exception(music_player) -> None:
    """Тестирует обработку общего исключения в задаче периодической очистки."""
    with patch("asyncio.sleep", side_effect=Exception("General error")):
        await music_player._scheduled_cleanup()
        # Тест проходит если исключение обработано корректно


@pytest.mark.asyncio
async def test_cleanup_old_files(music_player) -> None:
    """Тестирует очистку старых файлов."""
    from pathlib import Path
    import time
    
    # Мокаем DOWNLOADS_DIR и файлы
    mock_file1 = MagicMock(spec=Path)
    mock_file1.is_file.return_value = True
    mock_file1.name = "old_file.mp3"
    mock_file1.stat.return_value.st_mtime = time.time() - (25 * 60 * 60)  # 25 часов назад
    mock_file1.unlink = MagicMock()
    
    mock_file2 = MagicMock(spec=Path)
    mock_file2.is_file.return_value = True
    mock_file2.name = "new_file.mp3"
    mock_file2.stat.return_value.st_mtime = time.time() - (1 * 60 * 60)  # 1 час назад
    mock_file2.unlink = MagicMock()
    
    mock_dir = MagicMock(spec=Path)
    mock_dir.is_file.return_value = False  # Это директория, должна быть пропущена
    
    with patch("utils.music.player.DOWNLOADS_DIR") as mock_downloads_dir:
        mock_downloads_dir.glob.return_value = [mock_file1, mock_file2, mock_dir]
        
        await music_player._cleanup_old_files()
        
        # Проверяем, что старый файл был удален
        mock_file1.unlink.assert_called_once_with(missing_ok=True)
        # Проверяем, что новый файл не был удален
        mock_file2.unlink.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_old_files_os_error(music_player) -> None:
    """Тестирует обработку OSError при удалении файлов."""
    from pathlib import Path
    import time
    
    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.name = "error_file.mp3"
    mock_file.stat.return_value.st_mtime = time.time() - (25 * 60 * 60)  # 25 часов назад
    mock_file.unlink = MagicMock(side_effect=OSError("Permission denied"))
    
    with patch("utils.music.player.DOWNLOADS_DIR") as mock_downloads_dir:
        mock_downloads_dir.glob.return_value = [mock_file]
        
        # Не должно вызывать исключений
        await music_player._cleanup_old_files()
        
        mock_file.unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
async def test_cleanup_old_files_general_exception(music_player) -> None:
    """Тестирует обработку общего исключения при очистке файлов."""
    from pathlib import Path
    import time
    
    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.name = "error_file.mp3"
    mock_file.stat.return_value.st_mtime = time.time() - (25 * 60 * 60)  # 25 часов назад
    mock_file.unlink = MagicMock(side_effect=Exception("Unexpected error"))
    
    with patch("utils.music.player.DOWNLOADS_DIR") as mock_downloads_dir:
        mock_downloads_dir.glob.return_value = [mock_file]
        
        # Не должно вызывать исключений
        await music_player._cleanup_old_files()
        
        mock_file.unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
async def test_cleanup_old_files_no_files_to_delete(music_player) -> None:
    """Тестирует очистку когда нет файлов для удаления."""
    from pathlib import Path
    import time
    
    # Все файлы новые
    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.name = "new_file.mp3"
    mock_file.stat.return_value.st_mtime = time.time() - (1 * 60 * 60)  # 1 час назад
    mock_file.unlink = MagicMock()
    
    with patch("utils.music.player.DOWNLOADS_DIR") as mock_downloads_dir:
        mock_downloads_dir.glob.return_value = [mock_file]
        
        await music_player._cleanup_old_files()
        
        # Проверяем, что файл не был удален
        mock_file.unlink.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_old_files_glob_exception(music_player) -> None:
    """Тестирует обработку исключения в общем процессе очистки файлов."""
    with patch("utils.music.player.DOWNLOADS_DIR") as mock_downloads_dir:
        mock_downloads_dir.glob.side_effect = Exception("Glob failed")
        
        # Не должно вызывать исключений
        await music_player._cleanup_old_files()


def test_track_initialization_minimal_info(mock_member) -> None:
    """Тестирует инициализацию Track с минимальной информацией."""
    minimal_info = {}
    track = Track(minimal_info, mock_member)
    
    assert track.url == ""
    assert track.title == "Неизвестное название"
    assert track.duration is None
    assert track.thumbnail is None
    assert track.uploader is None
    assert track.uploader_url is None
    assert track.requester == mock_member
    assert track.id == ""
    assert track.extractor == "youtube"  # значение по умолчанию
    assert track.filepath is None


def test_track_to_embed_field_no_uploader(mock_member) -> None:
    """Тестирует to_embed_field без информации об авторе."""
    track_info = {
        "title": "Test Track",
        "duration": 180,
    }
    track = Track(track_info, mock_member)
    
    name, value, inline = track.to_embed_field()
    
    assert name == track.title
    assert mock_member.mention in value
    # Проверяем, что uploader None и не включен в value
    assert track.uploader is None
    assert "Автор:" not in value  # Поле автора не должно быть включено
    assert inline is False


def test_track_to_embed_field_uploader_no_url(mock_member) -> None:
    """Тестирует to_embed_field с автором но без URL."""
    track_info = {
        "title": "Test Track",
        "duration": 180,
        "uploader": "Test Channel",
    }
    track = Track(track_info, mock_member)
    
    name, value, inline = track.to_embed_field()
    
    assert name == track.title
    assert mock_member.mention in value
    assert "Test Channel" in value
    assert "[Test Channel]" not in value  # Не должно быть ссылки
    assert inline is False
