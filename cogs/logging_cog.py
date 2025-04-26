import discord
from discord.ext import commands, tasks
import asyncio
import logging
import os

logger = logging.getLogger("bot")
LOG_FILE_PATH = "bot.log"
CHECK_INTERVAL_SECONDS = 5
MAX_MESSAGE_LENGTH = 1990 # Макс. длина сообщения Discord (с запасом для ```)

class LoggingCog(commands.Cog):
    """
    Ког для пересылки новых строк из файла логов в указанный Discord канал.
    Отслеживает файл bot.log и отправляет новые записи в заданный канал.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # TODO: Перенести LOG_CHANNEL_ID в config.py или переменные окружения
        self.log_channel_id = 1365045098785542224 # Жестко заданный ID канала для логов
        self.log_channel = None # Объект канала Discord (получается в cog_load)
        self.last_read_position = 0
        self.log_file_path = LOG_FILE_PATH
        self._task_started = False # Флаг для отслеживания запуска задачи

        if not self.log_channel_id:
            logger.warning("ID канала логирования не установлен. Логирование в Discord отключено.")
            return

        # Определяем начальную позицию для чтения файла логов (сразу при инициализации)
        try:
            if os.path.exists(self.log_file_path):
                # Если файл существует, устанавливаем позицию в конец файла
                self.last_read_position = os.path.getsize(self.log_file_path)
                logger.info(f"Начальная позиция чтения лога установлена в конец файла '{self.log_file_path}' ({self.last_read_position} байт).")
            else:
                # Если файл не найден, начнем читать с начала, когда он появится
                logger.warning(f"Файл логов '{self.log_file_path}' не найден при инициализации. Чтение начнется с начала после создания файла.")
                self.last_read_position = 0

            # Запускаем фоновую задачу чтения логов ТОЛЬКО если удалось определить позицию
            self.tail_log_file.start()
            self._task_started = True
            logger.info("Задача чтения логов запущена.")

        except Exception as e:
            logger.error(f"Критическая ошибка при получении начального размера файла логов '{self.log_file_path}' в __init__: {e}. Задача чтения логов не будет запущена.")
            # Не запускаем задачу, если не удалось определить позицию

    async def cog_load(self):
        """Получение объекта канала после готовности бота."""
        if not self._task_started:
             # Не ищем канал, если задача не была успешно запущена в __init__
            logger.warning("Задача чтения логов не была запущена из-за ошибки в __init__. Канал не будет получен.")
            return

        await self.bot.wait_until_ready()
        self.log_channel = self.bot.get_channel(self.log_channel_id)

        if not self.log_channel:
            logger.error(f"Не удалось найти канал для логирования с ID: {self.log_channel_id}. Логирование в Discord отключено.")
            self.tail_log_file.cancel() # Останавливаем задачу, если канал не найден
        else:
             logger.info(f"Канал для логирования '{self.log_channel.name}' ({self.log_channel_id}) найден.")

    def cog_unload(self):
        """Останавливает задачу при выгрузке кога."""
        if self._task_started:
            self.tail_log_file.cancel()
            logger.info("Задача логирования в Discord остановлена.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def tail_log_file(self):
        """Периодически проверяет файл логов на новые записи и отправляет их в Discord."""
        if not self.log_channel:
            # Канал мог быть не найден в cog_load, или бот потерял к нему доступ
            # Попытка получить его снова здесь может быть излишней, если ошибка постоянная
            # Просто пропускаем итерацию, если канала нет
            if not self.tail_log_file.is_being_cancelled(): # Логируем только если задача не отменяется
                 logger.warning(f"Канал логирования (ID: {self.log_channel_id}) недоступен. Пропуск итерации.")
            return

        try:
            # Проверяем существование файла перед чтением
            if not os.path.exists(self.log_file_path):
                # Можно добавить логгер, если файл часто пропадает, но пока пропустим
                return

            current_size = os.path.getsize(self.log_file_path)

            # Обработка усечения файла (например, при ротации логов)
            if current_size < self.last_read_position:
                logger.info(f"Файл логов '{self.log_file_path}' был усечен. Чтение продолжится с начала.")
                self.last_read_position = 0 # Сбрасываем позицию на начало усеченного файла

            # Читаем новые строки, если размер файла увеличился
            if current_size > self.last_read_position:
                with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(self.last_read_position) # Переходим к последней прочитанной позиции
                    new_lines = f.readlines()      # Читаем все новые строки
                    self.last_read_position = f.tell() # Обновляем позицию

                if new_lines:
                    buffer = ""
                    for line in new_lines:
                        # Собираем строки в буфер, пока не достигнем лимита Discord
                        # Отправляем буфер, если добавление следующей строки его превысит
                        if len(buffer) + len(line) + 10 > MAX_MESSAGE_LENGTH: # +10 для ```\n и \n```
                            if buffer:
                                await self.send_log_message(buffer)
                            buffer = line # Начинаем новый буфер с текущей строки
                        else:
                            buffer += line # Добавляем строку в буфер
                    # Отправляем остаток буфера после цикла
                    if buffer:
                        await self.send_log_message(buffer)

        except FileNotFoundError:
             # Может случиться, если файл удален между os.path.exists и open
             logger.warning(f"Файл логов '{self.log_file_path}' не найден во время чтения.")
             self.last_read_position = 0 # Сбрасываем позицию
        except Exception as e:
            logger.error(f"Ошибка при чтении файла логов '{self.log_file_path}': {e}", exc_info=True)

    async def send_log_message(self, message: str):
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            # Это сообщение может спамить, если канал не найден, убираем или ставим DEBUG
            # logger.warning("Попытка отправить лог, но канал не установлен.")
            return

        try:
            await self.log_channel.send(f"```\n{message.strip()}\n```")
        except discord.HTTPException as e:
            logger.error(f"Ошибка Discord API при отправке лога: {e}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отправке лога: {e}")

    @tail_log_file.before_loop
    async def before_tail_log_file(self):
        """Ожидание готовности бота перед первым запуском цикла."""
        await self.bot.wait_until_ready()
        # Лог о готовности задачи теперь выводится в __init__ после успешного запуска
        # logger.info("Задача логирования в Discord готова к запуску.")


async def setup(bot: commands.Bot):
    """Добавляет LoggingCog к боту."""
    await bot.add_cog(LoggingCog(bot))
