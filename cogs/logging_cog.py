import discord
from discord.ext import commands, tasks
import logging
import os

logger = logging.getLogger("bot")
CHECK_INTERVAL_SECONDS = 5
MAX_MESSAGE_LENGTH = 1990  # Discord limit with margin for code block

class LoggingCog(commands.Cog):
    """
    Ког для отправки всего текущего файла логов в указанный Discord канал при запуске,
    а затем отправки новых строк по мере их появления (tail -f).
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_channel_id = 1365045098785542224  # Жестко заданный ID канала для логов
        self.log_channel = None
        self.log_file_path = getattr(bot, "log_file_path", "bot.log")
        self.last_read_position = 0
        self._tail_task_started = False
        self._log_init_done = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._log_init_done:
            return
        self._log_init_done = True
        logger.info("[LogCog] on_ready: запуск логирования")
        await self._send_full_log_and_start_tail()

    async def _send_full_log_and_start_tail(self):
        # Получаем канал
        self.log_channel = self.bot.get_channel(self.log_channel_id)
        if not self.log_channel:
            logger.error(f"[LogCog] Не удалось получить канал логирования (ID: {self.log_channel_id}). Проверьте ID и права бота.")
            return
        permissions = self.log_channel.permissions_for(self.log_channel.guild.me)
        if not permissions.send_messages:
            logger.error(f"[LogCog] У бота нет прав на отправку сообщений в канал {self.log_channel.name} ({self.log_channel_id})")
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
            logger.info(f"[LogCog] Весь лог '{self.log_file_path}' отправлен в канал {self.log_channel.name}.")
        except Exception as e:
            logger.error(f"[LogCog] Ошибка при отправке лога: {e}", exc_info=True)

        # Запускаем задачу tail
        if not self._tail_task_started:
            self.tail_log_file.start()
            self._tail_task_started = True
            logger.info("[LogCog] Задача tail_log_file успешно запущена.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def tail_log_file(self):
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

    async def send_log_message(self, message: str):
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            return
        try:
            await self.log_channel.send(f"```\n{message.strip()}\n```")
        except discord.HTTPException as e:
            logger.error(f"[LogCog] Ошибка Discord API при отправке лога: {e}")
        except Exception as e:
            logger.error(f"[LogCog] Неизвестная ошибка при отправке лога: {e}")

async def setup(bot: commands.Bot):
    """Добавляет LoggingCog к боту."""
    await bot.add_cog(LoggingCog(bot))
