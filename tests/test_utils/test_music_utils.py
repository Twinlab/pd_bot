from pathlib import Path
from unittest.mock import MagicMock, patch

import discord
import pytest
import yt_dlp

from utils.music.embeds import create_embed, format_duration
from utils.music.yt_integration import get_stream_info, search_youtube

# --- Тесты для функций из embeds.py ---


def test_format_duration_none() -> None:
    """Тестирует форматирование длительности None."""
    assert format_duration(None) == "∞"


def test_format_duration_zero() -> None:
    """Тестирует форматирование нулевой длительности."""
    assert format_duration(0) == "00:00"


def test_format_duration_negative() -> None:
    """Тестирует форматирование отрицательной длительности."""
    assert format_duration(-10) == "00:00"


def test_format_duration_seconds() -> None:
    """Тестирует форматирование длительности в секундах."""
    assert format_duration(45) == "00:45"


def test_format_duration_minutes_seconds() -> None:
    """Тестирует форматирование длительности в минутах и секундах."""
    assert format_duration(125) == "02:05"


def test_format_duration_hours_minutes_seconds() -> None:
    """Тестирует форматирование длительности в часах, минутах и секундах."""
    assert format_duration(3661) == "01:01:01"


def test_format_duration_invalid() -> None:
    """Тестирует форматирование некорректной длительности."""
    # mypy ругается на некорректные типы, но мы именно это и тестируем.
    # Для прохождения mypy, мы должны передавать ожидаемые типы.
    # Однако, логика функции format_duration обрабатывает и такие случаи, возвращая "?:??".
    # Чтобы тест соответствовал ожиданиям mypy и логике функции,
    # мы можем либо изменить тест, чтобы он передавал int/None,
    # либо добавить # type: ignore к строкам с некорректными типами.
    # В данном случае, поскольку мы тестируем поведение с "некорректными" типами,
    # но функция их обрабатывает, оставим как есть и добавим type: ignore.
    assert format_duration("invalid") == "?:??"  # type: ignore[arg-type]
    assert format_duration(None) == "∞"
    assert format_duration({}) == "?:??"  # type: ignore[arg-type]


def test_create_embed_basic() -> None:
    """Тестирует создание базового embed."""
    title = "Test Title"
    description = "Test Description"
    color = discord.Color.blue()

    embed = create_embed(title, description, color)

    assert embed.title == title
    assert embed.description == description
    assert embed.color == color


def test_create_embed_with_thumbnail() -> None:
    """Тестирует создание embed с миниатюрой."""
    title = "Test Title"
    thumbnail_url = "https://example.com/thumbnail.jpg"

    embed = create_embed(title, thumbnail=thumbnail_url)

    assert embed.thumbnail.url == thumbnail_url


def test_create_embed_with_footer() -> None:
    """Тестирует создание embed с нижним колонтитулом."""
    title = "Test Title"
    footer_text = "Test Footer"

    embed = create_embed(title, footer=footer_text)

    assert embed.footer.text == footer_text


def test_create_embed_with_image() -> None:
    """Тестирует создание embed с изображением."""
    title = "Test Title"
    image_url = "https://example.com/image.jpg"

    embed = create_embed(title, image=image_url)

    assert embed.image.url == image_url


def test_create_embed_with_author_string() -> None:
    """Тестирует создание embed с автором в виде строки."""
    title = "Test Title"
    author_name = "Test Author"

    embed = create_embed(title, author=author_name)

    assert embed.author.name == author_name
    assert embed.author.icon_url is None
    assert embed.author.url is None


def test_create_embed_with_author_dict() -> None:
    """Тестирует создание embed с автором в виде словаря."""
    title = "Test Title"
    author_data = {
        "name": "Test Author",
        "icon_url": "https://example.com/icon.jpg",
        "url": "https://example.com/author",
    }

    embed = create_embed(title, author=author_data)

    assert embed.author.name == author_data["name"]
    assert embed.author.icon_url == author_data["icon_url"]
    assert embed.author.url == author_data["url"]


def test_create_embed_with_fields() -> None:
    """Тестирует создание embed с полями."""
    title = "Test Title"
    fields = [
        ("Field 1", "Value 1", True),
        ("Field 2", "Value 2", False),
        ("Field 3", "Value 3"),  # Без указания inline
    ]

    embed = create_embed(title, fields=fields)

    assert len(embed.fields) == 3
    assert embed.fields[0].name == "Field 1"
    assert embed.fields[0].value == "Value 1"
    assert embed.fields[0].inline is True
    assert embed.fields[1].name == "Field 2"
    assert embed.fields[1].value == "Value 2"
    assert embed.fields[1].inline is False
    assert embed.fields[2].name == "Field 3"
    assert embed.fields[2].value == "Value 3"
    assert embed.fields[2].inline is True  # По умолчанию True


def test_create_embed_with_unknown_kwargs() -> None:
    """Тестирует создание embed с неизвестными именованными аргументами."""
    title = "Test Title"

    embed = create_embed(title, field1="Value 1", field2="Value 2")

    assert len(embed.fields) == 2
    assert embed.fields[0].name == "field1"
    assert embed.fields[0].value == "Value 1"
    assert embed.fields[0].inline is True
    assert embed.fields[1].name == "field2"
    assert embed.fields[1].value == "Value 2"
    assert embed.fields[1].inline is True


# --- Тесты для функций из yt_integration.py ---


@pytest.mark.asyncio
async def test_get_stream_info_success():
    """Тестирует успешное получение информации о потоке."""
    url = "https://www.youtube.com/watch?v=test_id"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_info: dict = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "thumbnail": "https://example.com/thumbnail.jpg",
        "uploader": "Test Uploader",
        "uploader_url": "https://www.youtube.com/channel/test_channel",
        "extractor_key": "Youtube",
        "url": "https://example.com/stream.mp3",
    }
    mock_ytdl.extract_info.return_value = mock_info

    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await get_stream_info(url)

        # Проверяем результат
        assert result is not None
        assert result["id"] == mock_info["id"]
        assert result["title"] == mock_info["title"]
        assert result["url"] == "https://example.com/stream.mp3"


@pytest.mark.asyncio
async def test_get_stream_info_with_entries():
    """Тестирует получение информации о потоке из плейлиста."""
    url = "https://www.youtube.com/playlist?list=test_playlist"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_entry: dict = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": "https://www.youtube.com/watch?v=test_id",
        "duration": 180,
        "thumbnail": "https://example.com/thumbnail.jpg",
        "uploader": "Test Uploader",
        "uploader_url": "https://www.youtube.com/channel/test_channel",
        "extractor_key": "Youtube",
        "url": "https://example.com/stream.mp3",
    }
    mock_info: dict = {"entries": [mock_entry]}
    mock_ytdl.extract_info.return_value = mock_info

    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await get_stream_info(url)

        # Проверяем результат
        assert result is not None
        assert result["id"] == mock_entry["id"]
        assert result["title"] == mock_entry["title"]
        assert result["url"] == "https://example.com/stream.mp3"


@pytest.mark.asyncio
async def test_get_stream_info_no_stream_url():
    """Тестирует случай, когда не удалось извлечь URL потока."""
    url = "https://www.youtube.com/watch?v=test_id"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_info: dict = {
        "id": "test_id",
        "title": "Test Track",
        "webpage_url": url,
        "duration": 180,
        "thumbnail": "https://example.com/thumbnail.jpg",
        "uploader": "Test Uploader",
        "uploader_url": "https://www.youtube.com/channel/test_channel",
        "extractor_key": "Youtube",
        "url": None,  # Нет URL потока
    }
    mock_ytdl.extract_info.return_value = mock_info

    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await get_stream_info(url)

        # Проверяем результат
        assert result is None


@pytest.mark.asyncio
async def test_get_stream_info_download_error():
    """Тестирует обработку ошибки скачивания."""
    url = "https://www.youtube.com/watch?v=test_id"

    # Мокаем YoutubeDL с ошибкой
    mock_ytdl = MagicMock()
    mock_ytdl.extract_info.side_effect = yt_dlp.utils.DownloadError("Test download error")

    # Мокаем yt_dlp.YoutubeDL
    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        with pytest.raises(yt_dlp.utils.DownloadError):
            await get_stream_info(url)


@pytest.mark.asyncio


@pytest.mark.asyncio
async def test_search_youtube_success():
    """Тестирует успешный поиск на YouTube."""
    query = "test search query"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_entries: list[dict] = [
        {
            "id": "test_id_1",
            "title": "Test Track 1",
            "url": "https://www.youtube.com/watch?v=test_id_1",
            "duration": 180,
            "thumbnail": "https://example.com/thumbnail1.jpg",
            "uploader": "Test Uploader 1",
            "uploader_url": "https://www.youtube.com/channel/test_channel_1",
            "ie_key": "Youtube",
        },
        {
            "id": "test_id_2",
            "title": "Test Track 2",
            "url": "https://www.youtube.com/watch?v=test_id_2",
            "duration": 240,
            "thumbnail": "https://example.com/thumbnail2.jpg",
            "uploader": "Test Uploader 2",
            "uploader_url": "https://www.youtube.com/channel/test_channel_2",
            "ie_key": "Youtube",
        },
    ]
    mock_info: dict = {"entries": mock_entries}
    mock_ytdl.extract_info.return_value = mock_info

    # Мокаем yt_dlp.YoutubeDL
    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await search_youtube(query)

        # Проверяем результат
        assert result is not None
        assert len(result) == 2
        assert result[0]["id"] == mock_entries[0]["id"]
        assert result[0]["title"] == mock_entries[0]["title"]
        assert result[1]["id"] == mock_entries[1]["id"]
        assert result[1]["title"] == mock_entries[1]["title"]


@pytest.mark.asyncio
async def test_search_youtube_with_missing_url():
    """Тестирует поиск на YouTube с отсутствующим URL."""
    query = "test search query"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_entries: list[dict] = [
        {
            "id": "test_id_1",
            "title": "Test Track 1",
            # Нет URL
            "duration": 180,
            "thumbnail": "https://example.com/thumbnail1.jpg",
            "uploader": "Test Uploader 1",
            "uploader_url": "https://www.youtube.com/channel/test_channel_1",
            "ie_key": "Youtube",
        }
    ]
    mock_info: dict = {"entries": mock_entries}
    mock_ytdl.extract_info.return_value = mock_info

    # Мокаем yt_dlp.YoutubeDL
    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await search_youtube(query)

        # Проверяем результат
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == mock_entries[0]["id"]
        assert result[0]["title"] == mock_entries[0]["title"]
        assert "url" in result[0]
        assert result[0]["url"] == f"https://www.youtube.com/watch?v={mock_entries[0]['id']}"


@pytest.mark.asyncio
async def test_search_youtube_no_results():
    """Тестирует поиск на YouTube без результатов."""
    query = "test search query"

    # Мокаем YoutubeDL
    mock_ytdl = MagicMock()
    mock_info: dict = {"entries": []}
    mock_ytdl.extract_info.return_value = mock_info

    # Мокаем yt_dlp.YoutubeDL
    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await search_youtube(query)

        # Проверяем результат
        assert result is None


@pytest.mark.asyncio
async def test_search_youtube_download_error():
    """Тестирует обработку ошибки поиска на YouTube."""
    query = "test search query"

    # Мокаем YoutubeDL с ошибкой
    mock_ytdl = MagicMock()
    mock_ytdl.extract_info.side_effect = yt_dlp.utils.DownloadError("Test download error")

    # Мокаем yt_dlp.YoutubeDL
    with patch("yt_dlp.YoutubeDL", return_value=mock_ytdl):
        result = await search_youtube(query)

        # Проверяем результат
        assert result is None
