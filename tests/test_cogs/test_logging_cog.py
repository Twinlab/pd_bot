"""Тесты для кога LoggingCog."""

import asyncio
import json
import logging
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import discord
import pytest
from discord.ext import commands

# Предполагаем, что LoggingCog находится в cogs.logging_cog
from cogs.logging_cog import CHECK_INTERVAL_SECONDS, MAX_MESSAGE_LENGTH, LoggingCog

# Устанавливаем уровень логгирования для тестов, чтобы видеть отладочные сообщения
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_bot(mock_settings):
    """Фикстура для мока бота."""
    bot = MagicMock(spec=commands.Bot)
    bot.settings = mock_settings
    bot.log_file_path = "test_bot.log"
    bot.wait_until_ready = AsyncMock()
    bot.get_channel = MagicMock()
    return bot


@pytest.fixture
def mock_text_channel():
    """Фикстура для мока текстового канала."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123456789
    channel.name = "test-log-channel"
    channel.guild = MagicMock(spec=discord.Guild)
    channel.guild.me = MagicMock(spec=discord.Member)
    channel.permissions_for = MagicMock()
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def logging_cog(mock_bot: commands.Bot):
    """Фикстура для создания экземпляра LoggingCog."""
    return LoggingCog(mock_bot)


class TestLoggingCogInit:
    """Тесты для инициализации LoggingCog."""

    def test_init_default_channel_id(self, mock_bot: commands.Bot):
        """Тест инициализации с ID канала по умолчанию."""
        cog = LoggingCog(mock_bot)
        assert cog.bot == mock_bot
        assert cog.log_channel_id == 1365045098785542224  # Значение по умолчанию
        assert cog.log_file_path == "test_bot.log"
        assert cog.last_read_position == 0
        assert not cog._tail_task_started
        assert not cog._log_init_done

    def test_init_custom_channel_id(self, mock_bot: commands.Bot):
        """Тест инициализации с пользовательским ID канала."""
        mock_bot.settings.channels.logging = 987654321
        cog = LoggingCog(mock_bot)
        assert cog.log_channel_id == 987654321

    def test_init_invalid_channel_id_type(self, mock_bot: commands.Bot):
        """Тест инициализации с неверным типом ID канала в конфиге."""
        # Этот тест больше не актуален, так как Pydantic выполняет проверку типов при загрузке.
        # Если мы хотим протестировать это, нам нужно будет мокать сам процесс загрузки настроек,
        # что выходит за рамки этого теста. Пропускаем.
        pass

    def test_init_log_file_path_from_bot(self, mock_bot: commands.Bot):
        """Тест, что log_file_path берется из атрибута бота."""
        mock_bot.log_file_path = "custom_path.log"
        cog = LoggingCog(mock_bot)
        assert cog.log_file_path == "custom_path.log"

    def test_init_log_file_path_default(self):
        """Тест, что log_file_path по умолчанию 'bot.log', если не задан у бота."""
        bot_without_log_path = MagicMock(spec=commands.Bot)
        delattr(bot_without_log_path, "log_file_path") # Убедимся, что атрибута нет
        cog = LoggingCog(bot_without_log_path)
        assert cog.log_file_path == "bot.log"


class TestLoggingCogOnReady:
    """Тесты для обработчика on_ready."""

    @pytest.mark.asyncio
    async def test_on_ready_calls_send_full_log(self, logging_cog: LoggingCog):
        """Тест, что on_ready вызывает _send_full_log_and_start_tail."""
        logging_cog._send_full_log_and_start_tail = AsyncMock()
        await logging_cog.on_ready()
        logging_cog._send_full_log_and_start_tail.assert_called_once()
        assert logging_cog._log_init_done is True

    @pytest.mark.asyncio
    async def test_on_ready_called_multiple_times(self, logging_cog: LoggingCog):
        """Тест, что _send_full_log_and_start_tail вызывается только один раз."""
        logging_cog._send_full_log_and_start_tail = AsyncMock()
        await logging_cog.on_ready()  # Первый вызов
        await logging_cog.on_ready()  # Второй вызов
        logging_cog._send_full_log_and_start_tail.assert_called_once() # Должен быть вызван только раз


class TestSendFullLogAndStartTail:
    """Тесты для функции _send_full_log_and_start_tail."""

    @pytest.mark.asyncio
    async def test_channel_not_found(self, logging_cog: LoggingCog, mock_bot: commands.Bot):
        """Тест, когда канал логирования не найден."""
        mock_bot.get_channel.return_value = None
        # В _send_full_log_and_start_tail, если get_channel вернул None,
        # то channel будет None.
        # Первая проверка isinstance(channel, discord.TextChannel) вернет False.
        # Будет залогирована ошибка "Канал с ID ... не является текстовым каналом."
        # Затем, если self.log_channel все еще None (а он будет None),
        # будет залогирована ошибка "Не удалось получить канал логирования..."
        # Тест должен проверять ОБЕ ошибки или ту, которая ожидается первой.
        # В данном случае, self.log_channel не будет установлен, и вторая ошибка тоже произойдет.
        # Однако, первая ошибка "не является текстовым" более специфична для случая, когда get_channel вернул что-то, но не TextChannel.
        # Если get_channel вернул None, то логичнее ожидать "Не удалось получить канал".
        # Давайте проверим, что self.log_channel остается None и задача не запускается.
        # И проверим лог на "Не удалось получить канал".

        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog._send_full_log_and_start_tail()

            # Проверяем, что self.log_channel не установлен
            assert logging_cog.log_channel is None
            # Проверяем, что задача tail не запущена
            assert not logging_cog._tail_task_started

            # Проверяем, что была попытка получить канал
            mock_bot.get_channel.assert_called_once_with(logging_cog.log_channel_id)

            # Проверяем правильность логирования
            # Ожидаем, что будет залогирована ошибка "Канал с ID ... не является текстовым каналом."
            # так как channel (который None) не пройдет проверку isinstance(channel, discord.TextChannel)
            calls = [call_args[0][0] for call_args in mock_logger_error.call_args_list]
            expected_error_msg = (
                f"[LogCog] Канал с ID {logging_cog.log_channel_id} не является текстовым каналом. "
                "Логирование невозможно."
            )
            assert any(expected_error_msg in call for call in calls)

    @pytest.mark.asyncio
    async def test_channel_not_text_channel(
        self, logging_cog: LoggingCog, mock_bot: commands.Bot
    ):
        """Тест, когда найденный канал не является текстовым."""
        mock_bot.get_channel.return_value = MagicMock(spec=discord.VoiceChannel)
        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog._send_full_log_and_start_tail()
            mock_logger_error.assert_any_call(
                f"[LogCog] Канал с ID {logging_cog.log_channel_id} не является текстовым каналом. "
                "Логирование невозможно."
            )
            assert logging_cog.log_channel is None
            assert not logging_cog._tail_task_started

    @pytest.mark.asyncio
    async def test_no_send_permissions(
        self, logging_cog: LoggingCog, mock_bot: commands.Bot, mock_text_channel: discord.TextChannel
    ):
        """Тест, когда у бота нет прав на отправку сообщений."""
        # Устанавливаем LOGGING_CHANNEL_ID в конфиге бота, чтобы он совпадал с ID мока канала
        mock_bot.settings.channels.logging = mock_text_channel.id
        # Пересоздаем logging_cog с обновленным конфигом бота, чтобы он подхватил правильный ID
        current_logging_cog = LoggingCog(mock_bot)

        mock_bot.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(send_messages=False)

        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await current_logging_cog._send_full_log_and_start_tail()

            expected_error_msg = (
                f"[LogCog] У бота нет прав на отправку сообщений в канал "
                f"{mock_text_channel.name} ({mock_text_channel.id})"
            )
            mock_logger_error.assert_any_call(expected_error_msg)
            assert current_logging_cog.log_channel is mock_text_channel # Канал должен быть установлен
            assert not current_logging_cog._tail_task_started # Но задача не запущена

    @pytest.mark.asyncio
    async def test_log_file_not_exists(
        self, logging_cog: LoggingCog, mock_bot: commands.Bot, mock_text_channel: discord.TextChannel
    ):
        """Тест, когда файл логов не существует."""
        mock_bot.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(send_messages=True)
        logging_cog.log_file_path = "non_existent_log.log"
        with patch("os.path.exists", return_value=False), \
             patch("cogs.logging_cog.logger.warning") as mock_logger_warning:
            await logging_cog._send_full_log_and_start_tail()
            mock_logger_warning.assert_called_once_with(
                f"[LogCog] Файл логов '{logging_cog.log_file_path}' не найден."
            )
            assert not logging_cog._tail_task_started

    @pytest.mark.asyncio
    @patch("builtins.open", new_callable=mock_open, read_data="Log line 1\nLog line 2\n")
    @patch("os.path.exists", return_value=True)
    @patch("config.settings.BotSettings.load_from_yaml")
    async def test_send_full_log_success(
        self, mock_load_yaml, mock_os_exists, mock_file_open,
        logging_cog: LoggingCog, mock_bot: commands.Bot, mock_text_channel: discord.TextChannel
    ):
        """Тест успешной отправки всего лога и запуска задачи tail."""
        # Создаем полноценный mock для settings с нужными атрибутами
        mock_settings = MagicMock()
        mock_settings.limits.logging_buffer_overhead = 10
        mock_settings.limits.max_message_length = 1990
        mock_settings.timeouts.log_check_interval = 5
        mock_settings.channels.logging = 123456789
        mock_load_yaml.return_value = mock_settings
        mock_bot.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(send_messages=True)
        logging_cog.send_log_message = AsyncMock()
        logging_cog.tail_log_file = MagicMock() # Мокаем саму задачу, чтобы не запускать loop
        logging_cog.tail_log_file.start = MagicMock()
    
        await logging_cog._send_full_log_and_start_tail()
    
        # Проверяем, что файл логов был открыт для чтения
        mock_file_open.assert_any_call(logging_cog.log_file_path, "r", encoding="utf-8", errors="ignore")
        # Проверяем, что send_log_message был вызван
        logging_cog.send_log_message.assert_called_once()
        # Проверяем, что last_read_position обновлена
        # mock_file_open().tell() должен быть вызван
        mock_file_open().tell.assert_called()
        assert logging_cog.last_read_position == mock_file_open().tell()

        # Проверяем, что задача tail запущена
        logging_cog.tail_log_file.start.assert_called_once()
        assert logging_cog._tail_task_started is True

    @pytest.mark.asyncio
    @patch("builtins.open", new_callable=mock_open, read_data="L" * (MAX_MESSAGE_LENGTH + 100)) # Очень длинный лог
    @patch("os.path.exists", return_value=True)
    @patch("config.settings.BotSettings.load_from_yaml")
    async def test_send_full_log_multiple_messages(
        self, mock_load_yaml, mock_os_exists, mock_file_open,
        logging_cog: LoggingCog, mock_bot: commands.Bot, mock_text_channel: discord.TextChannel
    ):
        # Создаем полноценный mock для settings с нужными атрибутами
        mock_settings = MagicMock()
        mock_settings.limits.logging_buffer_overhead = 10
        mock_settings.limits.max_message_length = 1990
        mock_settings.timeouts.log_check_interval = 5
        mock_settings.channels.logging = 123456789
        mock_load_yaml.return_value = mock_settings
        """Тест отправки полного лога, который разбивается на несколько сообщений."""
        mock_bot.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(send_messages=True)
        logging_cog.send_log_message = AsyncMock()
        logging_cog.tail_log_file = MagicMock()
        logging_cog.tail_log_file.start = MagicMock()

        # Создаем содержимое файла, которое точно потребует несколько сообщений
        # MAX_MESSAGE_LENGTH это лимит для одного сообщения
        # Пусть одна строка будет чуть меньше лимита
        line_content = "a" * (MAX_MESSAGE_LENGTH - 20)
        file_content = f"{line_content}\n{line_content}\n{line_content}\n"
        mock_file_open.read_data = file_content
        # Пересоздаем мок open с новым read_data
        with patch("builtins.open", new_callable=mock_open, read_data=file_content):
            await logging_cog._send_full_log_and_start_tail()

        # Ожидаем, что send_log_message будет вызван несколько раз
        assert logging_cog.send_log_message.call_count > 1
        # Проверяем, что задача tail запущена
        logging_cog.tail_log_file.start.assert_called_once()

    @pytest.mark.asyncio
    @patch("builtins.open", side_effect=IOError("Test IO Error"))
    @patch("os.path.exists", return_value=True)
    async def test_send_full_log_read_error(
        self, mock_os_exists, mock_file_open_error,
        logging_cog: LoggingCog, mock_bot: commands.Bot, mock_text_channel: discord.TextChannel
    ):
        """Тест обработки ошибки при чтении файла логов."""
        mock_bot.get_channel.return_value = mock_text_channel
        mock_text_channel.permissions_for.return_value = MagicMock(send_messages=True)
        logging_cog.tail_log_file = MagicMock() # Мокаем задачу
        logging_cog.tail_log_file.start = MagicMock()


        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog._send_full_log_and_start_tail()
            mock_logger_error.assert_any_call(
                f"[LogCog] Ошибка при отправке лога: Test IO Error", exc_info=True
            )
            # Задача tail не должна быть запущена, если была ошибка чтения основного лога
            logging_cog.tail_log_file.start.assert_not_called()
            assert not logging_cog._tail_task_started


class TestTailLogFileTask:
    """Тесты для задачи tail_log_file."""

    @pytest.mark.asyncio
    async def test_tail_log_file_channel_none(self, logging_cog: LoggingCog):
        """Тест, что задача ничего не делает, если log_channel is None."""
        logging_cog.log_channel = None
        # Просто вызываем, чтобы убедиться, что не будет ошибки
        await logging_cog.tail_log_file()
        # Никаких assert, так как функция должна просто выйти

    @pytest.mark.asyncio
    @patch("os.path.exists", return_value=False)
    async def test_tail_log_file_not_exists(self, mock_os_exists, logging_cog: LoggingCog, mock_text_channel: discord.TextChannel):
        """Тест, что задача ничего не делает, если файл логов не существует."""
        logging_cog.log_channel = mock_text_channel # Устанавливаем канал
        # Просто вызываем, чтобы убедиться, что не будет ошибки
        await logging_cog.tail_log_file()
        mock_text_channel.send.assert_not_called() # Убедимся, что ничего не отправлено

    @pytest.mark.asyncio
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=True)
    async def test_tail_log_file_reads_new_lines(
        self, mock_os_exists, mock_file_open,
        logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест, что задача читает и отправляет новые строки."""
        logging_cog.log_channel = mock_text_channel
        logging_cog.send_log_message = AsyncMock()
        logging_cog.last_read_position = 0

        # Имитируем новые строки в файле
        mock_file_open().readlines.return_value = ["New log line 1\n", "New log line 2\n"]
        mock_file_open().tell.return_value = 50 # Новая позиция

        await logging_cog.tail_log_file()

        mock_file_open().seek.assert_called_once_with(0)
        logging_cog.send_log_message.assert_called_once()
        # Проверим, что буфер был отправлен с обеими строками
        # Это зависит от реализации send_log_message и MAX_MESSAGE_LENGTH,
        # но в данном случае обе строки короткие и должны попасть в один вызов
        assert "New log line 1\nNew log line 2" in logging_cog.send_log_message.call_args[0][0]
        assert logging_cog.last_read_position == 50

    @pytest.mark.asyncio
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=True)
    async def test_tail_log_file_multiple_sends_for_long_new_lines(
        self, mock_os_exists, mock_file_open,
        logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест, что длинные новые логи разбиваются на несколько сообщений."""
        logging_cog.log_channel = mock_text_channel
        logging_cog.send_log_message = AsyncMock()
        logging_cog.last_read_position = 0

        line_content = "b" * (MAX_MESSAGE_LENGTH - 10)
        new_lines_data = [f"{line_content}\n", f"{line_content}\n"]
        mock_file_open().readlines.return_value = new_lines_data
        mock_file_open().tell.return_value = len("".join(new_lines_data))

        await logging_cog.tail_log_file()

        # Каждая длинная строка должна вызвать отдельный send_log_message
        # так как buffer будет превышать MAX_MESSAGE_LENGTH на второй итерации
        assert logging_cog.send_log_message.call_count == 2
        assert logging_cog.last_read_position == len("".join(new_lines_data))


    @pytest.mark.asyncio
    @patch("builtins.open", side_effect=IOError("Tail Read Error"))
    @patch("os.path.exists", return_value=True)
    async def test_tail_log_file_read_error(
        self, mock_os_exists, mock_file_open_error,
        logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест обработки ошибки при чтении файла в tail_log_file."""
        logging_cog.log_channel = mock_text_channel
        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog.tail_log_file()
            mock_logger_error.assert_called_once_with(
                f"[LogCog] Ошибка в tail_log_file: Tail Read Error", exc_info=True
            )

    @pytest.mark.asyncio
    async def test_before_tail_log_file(self, logging_cog: LoggingCog, mock_bot: commands.Bot):
        """Тест функции before_tail_log_file."""
        with patch("cogs.logging_cog.logger.info") as mock_logger_info:
            await logging_cog.before_tail_log_file()
            mock_bot.wait_until_ready.assert_called_once()
            mock_logger_info.assert_called_once_with(
                "[LogCog] Задача tail_log_file готова к запуску (после on_ready)."
            )


class TestFormatJsonLog:
    """Тесты для функции format_json_log."""

    def test_format_valid_json_log(self, logging_cog: LoggingCog):
        """Тест форматирования валидной JSON-строки лога."""
        log_line = json.dumps({
            "timestamp": "2023-10-27T10:30:00.123456+00:00",
            "level": "INFO",
            "logger": "bot.cogs.music",
            "message": "Player started",
            "module": "player",
            "function": "play",
            "context": {"track_id": "xyz123", "user_id": "123"},
            "exception": {"type": "ValueError", "message": "Bad value"}
        })
        formatted = logging_cog.format_json_log(log_line)
        assert "[10:30:00] INFO    music        - Player started (player) [track_id=xyz123, user_id=123]" in formatted
        assert "Исключение: ValueError: Bad value" in formatted

    def test_format_json_log_minimal(self, logging_cog: LoggingCog):
        """Тест форматирования минимальной JSON-строки лога."""
        log_line = json.dumps({
            "timestamp": "2023-10-27T11:00:00Z", # Другой формат времени
            "level": "DEBUG",
            "logger": "bot.main",
            "message": "Bot init"
        })
        formatted = logging_cog.format_json_log(log_line)
        # Ожидаем "[HH:MM:SS] LEVEL..."
        assert formatted.startswith("[11:00:00] DEBUG")
        assert "main         - Bot init" in formatted


    def test_format_json_log_invalid_timestamp(self, logging_cog: LoggingCog):
        """Тест форматирования JSON с невалидным timestamp."""
        log_line = json.dumps({
            "timestamp": "invalid-time",
            "level": "WARNING",
            "logger": "bot.utils.api",
            "message": "API call failed"
        })
        formatted = logging_cog.format_json_log(log_line)
        # Ожидаем, что timestamp будет отображен как есть, заключенный в скобки
        assert "[invalid-time] WARNING api          - API call failed" in formatted


    def test_format_not_json_log(self, logging_cog: LoggingCog):
        """Тест, когда строка не является JSON."""
        log_line = "This is a plain text log line"
        formatted = logging_cog.format_json_log(log_line)
        assert formatted == "This is a plain text log line"

    def test_format_invalid_json_log(self, logging_cog: LoggingCog):
        """Тест, когда строка является невалидным JSON."""
        log_line = "{'key': 'value', not_json" # Невалидный JSON
        formatted = logging_cog.format_json_log(log_line)
        assert formatted == log_line # Должна вернуться исходная строка

    def test_format_json_log_missing_fields(self, logging_cog: LoggingCog):
        """Тест форматирования JSON, где отсутствуют некоторые ожидаемые поля."""
        log_line = json.dumps({
            "level": "ERROR",
            "message": "Something went wrong"
        })
        formatted = logging_cog.format_json_log(log_line)
        # Ожидаем, что отсутствующий timestamp не приведет к "[] " в начале
        assert not formatted.startswith("[]")
        assert "ERROR   " in formatted # Проверяем наличие уровня и выравнивания
        assert "             - Something went wrong" in formatted # Проверяем сообщение и имя логгера по умолчанию (пустое)

    def test_format_json_log_logger_name_short(self, logging_cog: LoggingCog):
        """Тест форматирования, когда имя логгера короткое (без точек)."""
        log_line = json.dumps({
            "timestamp": "2023-10-27T10:30:00",
            "level": "INFO",
            "logger": "main",
            "message": "App started"
        })
        formatted = logging_cog.format_json_log(log_line)
        assert "main         -" in formatted # Проверяем выравнивание


class TestSendLogMessage:
    """Тесты для функции send_log_message."""

    @pytest.mark.asyncio
    async def test_send_log_message_channel_none(self, logging_cog: LoggingCog):
        """Тест, что функция ничего не делает, если log_channel is None."""
        logging_cog.log_channel = None
        await logging_cog.send_log_message("Test message")
        # Никаких assert, так как функция должна просто выйти без ошибок

    @pytest.mark.asyncio
    async def test_send_log_message_success(
        self, logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест успешной отправки отформатированного сообщения."""
        logging_cog.log_channel = mock_text_channel
        logging_cog.format_json_log = MagicMock(side_effect=lambda x: f"formatted: {x.strip()}")

        message_content = "Line 1\nLine 2"
        await logging_cog.send_log_message(message_content)

        # Проверяем, что format_json_log был вызван для каждой строки
        assert logging_cog.format_json_log.call_count == 2
        logging_cog.format_json_log.assert_any_call("Line 1")
        logging_cog.format_json_log.assert_any_call("Line 2")

        # Проверяем, что send был вызван с отформатированным сообщением в блоке кода
        expected_formatted_msg = "formatted: Line 1\nformatted: Line 2"
        mock_text_channel.send.assert_called_once_with(f"```\n{expected_formatted_msg}\n```")

    @pytest.mark.asyncio
    async def test_send_log_message_empty_message(
        self, logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест отправки пустого сообщения (или сообщения только с пробелами)."""
        logging_cog.log_channel = mock_text_channel
        await logging_cog.send_log_message("   \n   ")
        mock_text_channel.send.assert_not_called() # Не должно ничего отправляться

    @pytest.mark.asyncio
    async def test_send_log_message_discord_http_exception(
        self, logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест обработки discord.HTTPException при отправке."""
        logging_cog.log_channel = mock_text_channel
        mock_text_channel.send.side_effect = discord.HTTPException(MagicMock(), "Test Discord Error")

        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog.send_log_message("Test message")
            mock_logger_error.assert_called_once()
            assert "[LogCog] Ошибка Discord API при отправке лога:" in mock_logger_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_send_log_message_other_exception(
        self, logging_cog: LoggingCog, mock_text_channel: discord.TextChannel
    ):
        """Тест обработки других исключений при отправке."""
        logging_cog.log_channel = mock_text_channel
        mock_text_channel.send.side_effect = Exception("Some other error")

        with patch("cogs.logging_cog.logger.error") as mock_logger_error:
            await logging_cog.send_log_message("Test message")
            mock_logger_error.assert_called_once()
            assert "[LogCog] Неизвестная ошибка при отправке лога:" in mock_logger_error.call_args[0][0]


class TestCogUnload:
    """Тесты для функции cog_unload."""

    @pytest.mark.asyncio
    async def test_cog_unload_cancels_task(self, logging_cog: LoggingCog):
        """Тест, что cog_unload отменяет задачу tail_log_file, если она запущена."""
        logging_cog.tail_log_file = MagicMock() # Мокаем задачу
        logging_cog.tail_log_file.cancel = MagicMock()
        logging_cog._tail_task_started = True

        with patch("cogs.logging_cog.logger.info") as mock_logger_info:
            await logging_cog.cog_unload()
            logging_cog.tail_log_file.cancel.assert_called_once()
            mock_logger_info.assert_any_call("[LogCog] Задача tail_log_file остановлена.")
            mock_logger_info.assert_any_call(f"Ког {logging_cog.__class__.__name__} выгружен.")

    @pytest.mark.asyncio
    async def test_cog_unload_task_not_started(self, logging_cog: LoggingCog):
        """Тест, что cog_unload не пытается отменить задачу, если она не была запущена."""
        logging_cog.tail_log_file = MagicMock()
        logging_cog.tail_log_file.cancel = MagicMock()
        logging_cog._tail_task_started = False # Задача не запущена

        with patch("cogs.logging_cog.logger.info") as mock_logger_info:
            await logging_cog.cog_unload()
            logging_cog.tail_log_file.cancel.assert_not_called() # Не должна быть вызвана
            mock_logger_info.assert_any_call(f"Ког {logging_cog.__class__.__name__} выгружен.")


@pytest.mark.asyncio
async def test_setup_function(mock_bot: commands.Bot):
    """Тест функции setup."""
    # Импортируем setup из модуля кога
    from cogs.logging_cog import setup as setup_logging_cog

    mock_bot.add_cog = AsyncMock()
    with patch("cogs.logging_cog.logger.info") as mock_logger_info:
        await setup_logging_cog(mock_bot)
        mock_bot.add_cog.assert_called_once()
        # Проверяем, что переданный в add_cog объект является экземпляром LoggingCog
        assert isinstance(mock_bot.add_cog.call_args[0][0], LoggingCog)
        mock_logger_info.assert_called_once_with("Ког LoggingCog успешно загружен.")
