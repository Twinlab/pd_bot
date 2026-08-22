"""Ког для отправки логов бота в указанный Discord канал в реальном времени.

Этот модуль отвечает за:
- Отправку всего содержимого файла логов при запуске бота в специальный канал Discord.
- Последующее отслеживание новых записей в файле логов (аналогично `tail -f`).
- Отправку новых записей логов в тот же канал Discord по мере их появления.

Это позволяет администраторам бота отслеживать его состояние и ошибки в реальном времени
непосредственно в Discord.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

import discord
from discord.ext import commands, tasks

from utils.logging_utils import redact_secrets

logger = logging.getLogger("bot.cogs.logging_cog")  # Иерархическое имя логгера

_CODE_BLOCK_PREFIX = "```\n"
_CODE_BLOCK_SUFFIX = "\n```"
_LEVEL_PREFIX = {
    "WARNING": "⚠️ ",
    "ERROR": "❌ ",
    "CRITICAL": "🚨 ",
}


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

        # Получаем ID канала из настроек
        self.log_channel_id = bot.settings.channels.logging

        self.log_channel = None
        self.log_file_path = str(getattr(bot, "log_file_path", "bot.log"))
        self.last_read_position = 0
        self._tail_task_started = False
        self._log_init_done = False
        self.tail_log_file.change_interval(seconds=self.bot.settings.timeouts.log_check_interval)

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
            await self._send_session_header()
            lines, position = await asyncio.to_thread(self._read_full_log)
            buffer = ""
            for line in lines:
                if (
                    len(buffer) + len(line) + self.bot.settings.limits.logging_buffer_overhead
                    > self.bot.settings.limits.max_message_length
                ):
                    if buffer:
                        await self.send_log_message(buffer)
                    buffer = line
                else:
                    buffer += line
            if buffer:
                await self.send_log_message(buffer)
            self.last_read_position = position
            logger.info(
                f"[LogCog] Весь лог '{self.log_file_path}' отправлен в канал "
                f"{self.log_channel.name}."
            )
            # Запускаем задачу tail только при успехе
            if not self._tail_task_started:
                self.tail_log_file.start()
                self._tail_task_started = True
                logger.info("[LogCog] Задача tail_log_file успешно запущена.")
        except Exception as e:
            logger.error(f"[LogCog] Ошибка при отправке лога: {e}", exc_info=True)
            # Не запускаем tail, если была ошибка с основным логом

    async def _send_session_header(self) -> None:
        """Отделяет лог текущего запуска временем и названием окружения."""
        if self.log_channel is None:
            return
        environment_setting = getattr(self.bot.settings, "environment", "unknown")
        environment = getattr(environment_setting, "value", environment_setting)
        environment_text = discord.utils.escape_markdown(str(environment))
        started_at = int(datetime.now().timestamp())
        await self.log_channel.send(
            "## 🟢 Новый запуск PD Bot\n"
            f"Время: <t:{started_at}:F> · окружение: `{environment_text}`"
        )

    @tasks.loop(seconds=5)  # Default value, will be changed in __init__
    async def tail_log_file(self) -> None:
        """Периодически проверяет файл логов на новые записи и отправляет их в Discord."""
        if self.log_channel is None:
            return
        if not os.path.exists(self.log_file_path):
            return
        try:
            new_lines, new_position = await asyncio.to_thread(
                self._read_log_from_position, self.last_read_position
            )
            if new_lines:
                buffer = ""
                for line in new_lines:
                    if (
                        len(buffer) + len(line) + self.bot.settings.limits.logging_buffer_overhead
                        > self.bot.settings.limits.max_message_length
                    ):
                        if buffer:  # Отправляем, только если буфер не пуст
                            await self.send_log_message(buffer)
                        buffer = line
                    else:
                        buffer += line
                if buffer:  # Отправляем остаток, если он есть
                    await self.send_log_message(buffer)
            self.last_read_position = new_position
        except Exception as e:
            logger.error(f"[LogCog] Ошибка в tail_log_file: {e}", exc_info=True)

    @tail_log_file.before_loop
    async def before_tail_log_file(self) -> None:
        """Ожидает готовности бота перед первым запуском tail_log_file."""
        await self.bot.wait_until_ready()
        logger.info("[LogCog] Задача tail_log_file готова к запуску (после on_ready).")

    def _read_full_log(self) -> tuple[list[str], int]:
        """Читает весь лог-файл (вызывается в потоке)."""
        with open(self.log_file_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            position = f.tell()
        return lines, position

    def _read_log_from_position(self, position: int) -> tuple[list[str], int]:
        """Читает лог-файл с указанной позиции (вызывается в потоке)."""
        with open(self.log_file_path, encoding="utf-8", errors="ignore") as f:
            f.seek(position)
            lines = f.readlines()
            new_position = f.tell()
        return lines, new_position

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
                timestamp_val = log_data.get("timestamp")
                timestamp_str = ""
                if timestamp_val:
                    try:
                        dt = datetime.fromisoformat(str(timestamp_val))
                        timestamp_str = f"[{dt.strftime('%H:%M:%S')}] "
                    except (ValueError, TypeError):
                        # Если не удалось распарсить, но значение есть, отображаем как есть
                        timestamp_str = f"[{timestamp_val}] "

                # Получаем основные поля
                level = log_data.get("level", "")
                logger_name = log_data.get("logger", "").split(".")[
                    -1
                ]  # Берем только последнюю часть имени логгера
                message = log_data.get("message", "")
                module = log_data.get("module", "")
                function = log_data.get("function", "")

                # Форматируем сообщение
                prefix = _LEVEL_PREFIX.get(level, "")
                formatted = f"{prefix}{timestamp_str}{level:<7} {logger_name:<12} - {message}"

                # Добавляем информацию о модуле и функции только если они не дублируют logger_name
                if module and function and module != logger_name.lower():
                    formatted += f" ({module})"

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

    @staticmethod
    def _is_routine_self_log(log_line: str) -> bool:
        """Убирает из Discord только служебные INFO/DEBUG самого log-tail."""
        try:
            log_data = json.loads(log_line)
        except (json.JSONDecodeError, TypeError):
            return False
        return log_data.get("logger") == "bot.cogs.logging_cog" and log_data.get("level") in {
            "DEBUG",
            "INFO",
        }

    @staticmethod
    def _split_log_text(text: str, limit: int) -> list[str]:
        """Делит текст на части, предпочитая границы строк."""
        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, limit + 1)
            if split_at <= 0:
                split_at = limit
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]
            else:
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at + 1 :]
        return chunks

    async def send_log_message(self, message: str) -> None:
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            return

        try:
            lines = message.strip().split("\n")
            formatted_lines = [
                self.format_json_log(redact_secrets(line))
                for line in lines
                if line.strip() and not self._is_routine_self_log(line)
            ]

            formatted_message = redact_secrets("\n".join(formatted_lines))

            if formatted_message:
                wrapper_length = len(_CODE_BLOCK_PREFIX) + len(_CODE_BLOCK_SUFFIX)
                content_limit = max(
                    1,
                    self.bot.settings.limits.max_message_length - wrapper_length,
                )
                for chunk in self._split_log_text(formatted_message, content_limit):
                    await self.log_channel.send(f"{_CODE_BLOCK_PREFIX}{chunk}{_CODE_BLOCK_SUFFIX}")
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
