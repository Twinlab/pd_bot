"""Ког для отправки логов бота в указанный Discord канал в реальном времени.

Этот модуль отвечает за:
- Отправку всего содержимого файла логов при запуске бота в специальный канал Discord.
- Последующее отслеживание новых записей в файле логов (аналогично `tail -f`).
- Отправку новых записей логов в тот же канал Discord по мере их появления.

Это позволяет администраторам бота отслеживать его состояние и ошибки в реальном времени
непосредственно в Discord.
"""

import json
import logging
import os
from datetime import datetime

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("bot.cogs.logging_cog")  # Иерархическое имя логгера
CHECK_INTERVAL_SECONDS = 5
MAX_MESSAGE_LENGTH = 1990  # Discord limit with margin for code block


class LoggingCog(commands.Cog):
    """Ког для отправки логов в Discord канал.

    Отправляет весь текущий файл логов при запуске,
    а затем новые строки по мере их появления (tail -f).
    """

    bot: commands.Bot
    log_channel_id: int
    log_channel: discord.TextChannel | None
    log_file_path: str
    last_read_position: int
    _tail_task_started: bool
    _log_init_done: bool

    def __init__(self, bot: commands.Bot) -> None:
        """Инициализирует ког LoggingCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        # Получаем ID канала из конфига, используем 1365045098785542224 как значение по умолчанию
        # Предполагаем, что bot.config это dict или имеет метод get
        config_channel_id = getattr(self.bot, "config", {}).get(
            "LOGGING_CHANNEL_ID", 1365045098785542224
        )
        if not isinstance(config_channel_id, int):
            logger.warning(
                f"[LogCog] LOGGING_CHANNEL_ID в конфиге не является int: {config_channel_id}. "
                "Используется значение по умолчанию."
            )
            self.log_channel_id = 1365045098785542224
        else:
            self.log_channel_id = config_channel_id

        self.log_channel = None
        self.log_file_path = str(getattr(bot, "log_file_path", "bot.log"))
        self.last_read_position = 0
        self._tail_task_started = False
        self._log_init_done = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Запускает процесс логирования при готовности бота.

        Использует флаг _log_init_done для предотвращения повторного запуска.
        """
        if self._log_init_done:
            return
        self._log_init_done = True
        logger.info("[LogCog] on_ready: запуск логирования")
        await self._send_full_log_and_start_tail()

    async def _send_full_log_and_start_tail(self) -> None:
        """Отправляет весь текущий лог в Discord и запускает отслеживание.

        Проверяет доступность канала и права бота на отправку сообщений.
        """
        # Получаем канал
        channel = self.bot.get_channel(self.log_channel_id)
        # Проверяем, что канал является текстовым
        if isinstance(channel, discord.TextChannel):
            self.log_channel = channel
        else:
            logger.error(
                f"[LogCog] Канал с ID {self.log_channel_id} не является текстовым каналом. "
                "Логирование невозможно."
            )
            return
        if not self.log_channel:
            logger.error(
                f"[LogCog] Не удалось получить канал логирования (ID: {self.log_channel_id}). "
                "Проверьте ID и права бота."
            )
            return
        permissions = self.log_channel.permissions_for(self.log_channel.guild.me)
        if not permissions.send_messages:
            logger.error(
                f"[LogCog] У бота нет прав на отправку сообщений в канал "
                f"{self.log_channel.name} ({self.log_channel_id})"
            )
            return

        # Читаем и отправляем весь лог
        if not os.path.exists(self.log_file_path):
            logger.warning(f"[LogCog] Файл логов '{self.log_file_path}' не найден.")
            return

        try:
            with open(self.log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                buffer = ""
                for line in f:
                    if len(buffer) + len(line) + 10 > MAX_MESSAGE_LENGTH:
                        await self.send_log_message(buffer)
                        buffer = line
                    else:
                        buffer += line
                if buffer:
                    await self.send_log_message(buffer)
                self.last_read_position = f.tell()
            logger.info(
                f"[LogCog] Весь лог '{self.log_file_path}' отправлен в канал "
                f"{self.log_channel.name}."
            )
        except Exception as e:
            logger.error(f"[LogCog] Ошибка при отправке лога: {e}", exc_info=True)

        # Запускаем задачу tail
        if not self._tail_task_started:
            self.tail_log_file.start()
            self._tail_task_started = True
            logger.info("[LogCog] Задача tail_log_file успешно запущена.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def tail_log_file(self) -> None:
        """Периодически проверяет файл логов на новые записи и отправляет их в Discord."""
        if self.log_channel is None:
            return
        if not os.path.exists(self.log_file_path):
            return
        try:
            with open(self.log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(self.last_read_position)
                new_lines = f.readlines()
                new_position = f.tell()
            if new_lines:
                buffer = ""
                for line in new_lines:
                    if len(buffer) + len(line) + 10 > MAX_MESSAGE_LENGTH:
                        await self.send_log_message(buffer)
                        buffer = line
                    else:
                        buffer += line
                if buffer:
                    await self.send_log_message(buffer)
            self.last_read_position = new_position
        except Exception as e:
            logger.error(f"[LogCog] Ошибка в tail_log_file: {e}", exc_info=True)

    @tail_log_file.before_loop
    async def before_tail_log_file(self) -> None:
        """Ожидает готовности бота перед первым запуском tail_log_file."""
        await self.bot.wait_until_ready()
        logger.info("[LogCog] Задача tail_log_file готова к запуску (после on_ready).")

    def format_json_log(self, log_line: str) -> str:
        """Преобразует JSON-лог в удобочитаемый формат.

        Args:
            log_line: Строка лога в формате JSON

        Returns:
            Отформатированная строка лога
        """
        try:
            # Проверяем, является ли строка JSON
            if log_line.strip().startswith("{") and "}" in log_line:
                log_data = json.loads(log_line)

                # Форматируем время
                timestamp = log_data.get("timestamp", "")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        timestamp = dt.strftime("%H:%M:%S")
                    except (ValueError, TypeError):
                        pass

                # Получаем основные поля
                level = log_data.get("level", "")
                logger_name = log_data.get("logger", "").split(".")[
                    -1
                ]  # Берем только последнюю часть имени логгера
                message = log_data.get("message", "")
                module = log_data.get("module", "")
                function = log_data.get("function", "")

                # Форматируем сообщение
                formatted = f"[{timestamp}] {level:<8} {logger_name:<15} - {message}"

                # Добавляем информацию о модуле и функции
                if module and function:
                    formatted += f" ({module}.{function})"

                # Добавляем контекст, если он есть
                if "context" in log_data:
                    context = log_data["context"]
                    context_str = ", ".join(f"{k}={v}" for k, v in context.items())
                    formatted += f" [{context_str}]"

                # Добавляем информацию об исключении, если оно есть
                if "exception" in log_data:
                    exc = log_data["exception"]
                    exc_type = exc.get("type", "")
                    exc_msg = exc.get("message", "")
                    formatted += f"\nИсключение: {exc_type}: {exc_msg}"

                return formatted
            else:
                # Если это не JSON, возвращаем строку как есть
                return log_line
        except json.JSONDecodeError:
            # Если не удалось распарсить JSON, возвращаем строку как есть
            return log_line
        except Exception as e:
            # В случае любой другой ошибки, логируем её и возвращаем исходную строку
            logger.error(f"Ошибка при форматировании лога: {e}", exc_info=True)
            return log_line

    async def send_log_message(self, message: str) -> None:
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            return

        try:
            # Разбиваем сообщение на строки и форматируем каждую
            lines = message.strip().split("\n")
            formatted_lines = [self.format_json_log(line) for line in lines if line.strip()]

            # Собираем отформатированные строки обратно
            formatted_message = "\n".join(formatted_lines)

            # Отправляем сообщение
            if formatted_message:
                await self.log_channel.send(f"```\n{formatted_message}\n```")
        except discord.HTTPException as e:
            logger.error(f"[LogCog] Ошибка Discord API при отправке лога: {e}")
        except Exception as e:
            logger.error(f"[LogCog] Неизвестная ошибка при отправке лога: {e}")

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога, останавливает задачу отслеживания логов."""
        if self._tail_task_started:
            self.tail_log_file.cancel()
            logger.info("[LogCog] Задача tail_log_file остановлена.")
        logger.info(f"Ког {self.__class__.__name__} выгружен.")


async def setup(bot: commands.Bot) -> None:
    """Добавляет LoggingCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(LoggingCog(bot))
    logger.info("Ког LoggingCog успешно загружен.")
