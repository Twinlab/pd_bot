import discord
from discord.ext import commands, tasks
import asyncio
import logging
import os

logger = logging.getLogger("bot")
LOG_FILE_PATH = "bot.log"
CHECK_INTERVAL_SECONDS = 5
MAX_MESSAGE_LENGTH = 1990 # Оставляем запас для ```\n ... \n```

class LoggingCog(commands.Cog):
    """
    Ког для пересылки новых строк из файла логов в указанный Discord канал.
    Отслеживает файл bot.log и отправляет новые записи в заданный канал.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # ID канала для логирования жестко задан. В будущем лучше вынести в конфиг.
        self.log_channel_id = 1365045098785542224
        self.log_channel = None
        self.last_read_position = 0
        self.log_file_path = LOG_FILE_PATH

        if not self.log_channel_id:
            logger.warning("ID канала логирования не установлен. Логирование в Discord отключено.")
            return

        self.tail_log_file.start()

    async def cog_load(self):
        """Инициализация канала и начальной позиции чтения при загрузке кога."""
        if not self.log_channel_id:
            return

        # Ожидаем готовности бота, чтобы получить объект канала
        await self.bot.wait_until_ready()
        self.log_channel = self.bot.get_channel(self.log_channel_id)

        if not self.log_channel:
            logger.error(f"Не удалось найти канал для логирования с ID: {self.log_channel_id}. Логирование в Discord отключено.")
            self.tail_log_file.cancel()
            return

        # Определяем начальную позицию для чтения файла логов (с конца)
        try:
            if os.path.exists(self.log_file_path):
                self.last_read_position = os.path.getsize(self.log_file_path)
                logger.info(f"Логирование в Discord канал '{self.log_channel.name}' ({self.log_channel_id}) настроено. Чтение с конца файла '{self.log_file_path}'.")
            else:
                logger.warning(f"Файл логов '{self.log_file_path}' не найден при запуске. Чтение начнется с начала после создания файла.")
                self.last_read_position = 0
        except Exception as e:
            logger.error(f"Ошибка при получении начального размера файла логов '{self.log_file_path}': {e}")
            self.tail_log_file.cancel()

    def cog_unload(self):
        """Останавливает задачу при выгрузке кога."""
        self.tail_log_file.cancel()
        logger.info("Задача логирования в Discord остановлена.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def tail_log_file(self):
        """Периодически проверяет файл логов на новые записи и отправляет их."""
        if not self.log_channel:
            # Попытка повторно получить канал, если он не был найден сразу
            if self.log_channel_id and not self.tail_log_file.is_being_cancelled():
                 self.log_channel = self.bot.get_channel(self.log_channel_id)
                 if not self.log_channel:
                     logger.warning(f"Канал логирования {self.log_channel_id} все еще не найден. Проверка через {CHECK_INTERVAL_SECONDS} сек.")
                     return
                 else:
                     logger.info(f"Канал логирования {self.log_channel.name} ({self.log_channel_id}) найден.")
            else:
                return # Прекращаем, если нет ID или задача отменена

        try:
            if not os.path.exists(self.log_file_path):
                return # Файл еще не создан

            current_size = os.path.getsize(self.log_file_path)

            # Обработка усечения файла (например, при ротации логов)
            if current_size < self.last_read_position:
                logger.info(f"Файл логов '{self.log_file_path}' был усечен. Чтение с начала.")
                self.last_read_position = 0

            # Читаем новые строки, если файл увеличился
            if current_size > self.last_read_position:
                with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(self.last_read_position)
                    new_lines = f.readlines()
                    self.last_read_position = f.tell()

                if new_lines:
                    buffer = ""
                    for line in new_lines:
                        # Отправляем буфер, если добавление следующей строки превысит лимит Discord
                        if len(buffer) + len(line) + 10 > MAX_MESSAGE_LENGTH:
                            if buffer:
                                await self.send_log_message(buffer)
                            buffer = line
                        else:
                            buffer += line
                    # Отправляем остаток буфера
                    if buffer:
                        await self.send_log_message(buffer)

        except FileNotFoundError:
             # Редкий случай, если файл удален между проверкой и открытием
             logger.warning(f"Файл логов '{self.log_file_path}' не найден во время чтения.")
             self.last_read_position = 0
        except Exception as e:
            logger.error(f"Ошибка при чтении файла логов '{self.log_file_path}': {e}", exc_info=True)

    async def send_log_message(self, message: str):
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            logger.warning("Попытка отправить лог, но канал не установлен.")
            return

        try:
            # Используем code blocks для лучшей читаемости
            await self.log_channel.send(f"```\n{message.strip()}\n```")
        except discord.HTTPException as e:
            logger.error(f"Ошибка Discord API при отправке лога: {e}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отправке лога: {e}")

    @tail_log_file.before_loop
    async def before_tail_log_file(self):
        """Ожидание готовности бота перед первым запуском цикла."""
        await self.bot.wait_until_ready()
        logger.info("Задача логирования в Discord готова к запуску.")


async def setup(bot: commands.Bot):
    """Добавляет LoggingCog к боту."""
    # Проверка наличия конфига у бота убрана, т.к. ID канала захардкожен
    # if not hasattr(bot, 'config'):
    #      logger.error("Конфигурация не найдена в объекте бота. Невозможно загрузить LoggingCog.")
    #      return
    await bot.add_cog(LoggingCog(bot))
