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
            logger.warning("[LogCog] ID канала логирования не установлен. Логирование в Discord отключено.")
            return

        # Определяем начальную позицию для чтения файла логов (сразу при инициализации)
        try:
            logger.info("[LogCog] Попытка определить начальную позицию чтения лога...")
            if os.path.exists(self.log_file_path):
                # Если файл существует, устанавливаем позицию в конец файла
                self.last_read_position = os.path.getsize(self.log_file_path)
                logger.info(f"[LogCog] Начальная позиция чтения лога установлена в конец файла '{self.log_file_path}' ({self.last_read_position} байт).")
            else:
                # Если файл не найден, начнем читать с начала, когда он появится
                logger.warning(f"[LogCog] Файл логов '{self.log_file_path}' не найден при инициализации. Чтение начнется с начала после создания файла.")
                self.last_read_position = 0

            # Запускаем фоновую задачу чтения логов ТОЛЬКО если удалось определить позицию
            logger.info("[LogCog] Попытка запуска задачи tail_log_file...")
            self.tail_log_file.start()
            self._task_started = True
            logger.info("[LogCog] Задача чтения логов tail_log_file успешно запущена.")

        except Exception as e:
            logger.error(f"[LogCog] Критическая ошибка при получении начального размера файла логов '{self.log_file_path}' в __init__: {e}. Задача чтения логов не будет запущена.", exc_info=True)
            # Не запускаем задачу, если не удалось определить позицию

    async def cog_load(self):
        """Получение объекта канала после готовности бота."""
        logger.info("[LogCog] cog_load вызван.")
        if not self._task_started:
            logger.warning("[LogCog] Задача чтения логов не была запущена в __init__. Поиск канала отменен.")
            return

        logger.info("[LogCog] Ожидание готовности бота для получения канала...")
        await self.bot.wait_until_ready()
        logger.info("[LogCog] Бот готов. Попытка получить канал...")
        self.log_channel = self.bot.get_channel(self.log_channel_id)

        if not self.log_channel:
            logger.error(f"[LogCog] Не удалось найти канал для логирования с ID: {self.log_channel_id}. Логирование в Discord отключено.")
            self.tail_log_file.cancel() # Останавливаем задачу, если канал не найден
        else:
             logger.info(f"[LogCog] Канал для логирования '{self.log_channel.name}' ({self.log_channel_id}) успешно найден.")

    def cog_unload(self):
        """Останавливает задачу при выгрузке кога."""
        logger.info("[LogCog] cog_unload вызван.")
        if self._task_started:
            self.tail_log_file.cancel()
            logger.info("[LogCog] Задача логирования в Discord остановлена.")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def tail_log_file(self):
        """Периодически проверяет файл логов на новые записи и отправляет их в Discord."""
        logger.debug("[LogCog] Итерация цикла tail_log_file.")

        if not self.log_channel:
            if not self.tail_log_file.is_being_cancelled():
                 logger.warning(f"[LogCog] Канал логирования (ID: {self.log_channel_id}) недоступен (self.log_channel is None). Пропуск итерации.")
            return

        try:
            logger.debug(f"[LogCog] Проверка файла: {self.log_file_path}")
            file_exists = os.path.exists(self.log_file_path)
            logger.debug(f"[LogCog] Файл существует: {file_exists}")
            if not file_exists:
                return

            current_size = os.path.getsize(self.log_file_path)
            logger.debug(f"[LogCog] Текущий размер: {current_size}, Последняя позиция: {self.last_read_position}")

            # Обработка усечения файла
            if current_size < self.last_read_position:
                logger.info(f"[LogCog] Файл логов '{self.log_file_path}' был усечен (с {self.last_read_position} до {current_size} байт). Чтение продолжится с начала.")
                self.last_read_position = 0 # Сбрасываем на начало файла

            # Читаем новые строки, если файл вырос
            if current_size > self.last_read_position:
                logger.debug(f"[LogCog] Файл вырос. Чтение с позиции {self.last_read_position}")
                with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    logger.debug(f"[LogCog] Seeking to position: {self.last_read_position}")
                    f.seek(self.last_read_position)
                    new_lines = f.readlines()
                    new_position = f.tell() # Запоминаем новую позицию *после* чтения
                    logger.debug(f"[LogCog] Прочитано {len(new_lines)} строк. Новая позиция: {new_position}")


                if new_lines:
                    logger.info(f"[LogCog] Обнаружено {len(new_lines)} новых строк лога для отправки.")
                    buffer = ""
                    for line in new_lines:
                        # Собираем строки в буфер
                        if len(buffer) + len(line) + 10 > MAX_MESSAGE_LENGTH: # +10 для ```\n и \n```
                            if buffer:
                                logger.debug(f"[LogCog] Отправка буфера (переполнение): {buffer[:100]}...")
                                await self.send_log_message(buffer)
                            buffer = line # Начинаем новый буфер
                        else:
                            buffer += line # Добавляем в буфер
                    # Отправляем остаток буфера
                    if buffer:
                        logger.debug(f"[LogCog] Отправка остатка буфера: {buffer[:100]}...")
                        await self.send_log_message(buffer)

                # Обновляем позицию только после успешного чтения и потенциальной отправки
                logger.debug(f"[LogCog] Обновление позиции чтения на {new_position}")
                self.last_read_position = new_position # Исправлено: убрана ошибка с new_position
            else:
                logger.debug("[LogCog] Размер файла не изменился.")

        except FileNotFoundError:
             # Это может произойти, если файл удален между os.path.exists и open
             logger.warning(f"[LogCog] Файл логов '{self.log_file_path}' не найден во время чтения.")
             self.last_read_position = 0 # Сбрасываем позицию
        except Exception as e:
            logger.error(f"[LogCog] Ошибка в цикле чтения/отправки логов: {e}", exc_info=True)

    async def send_log_message(self, message: str):
        """Отправляет отформатированное сообщение лога в Discord канал."""
        if not self.log_channel:
            # logger.warning("[LogCog] Попытка отправить лог, но канал не установлен.") # Слишком много спама может быть
            return

        logger.debug(f"[LogCog] Попытка отправки сообщения в канал {self.log_channel.name}")
        try:
            await self.log_channel.send(f"```\n{message.strip()}\n```")
            logger.debug(f"[LogCog] Сообщение успешно отправлено.")
        except discord.HTTPException as e:
            logger.error(f"[LogCog] Ошибка Discord API при отправке лога: {e}")
        except Exception as e:
            logger.error(f"[LogCog] Неизвестная ошибка при отправке лога: {e}")

    @tail_log_file.before_loop
    async def before_tail_log_file(self):
        """Ожидание готовности бота перед первым запуском цикла."""
        logger.info("[LogCog] before_loop: Ожидание готовности бота...")
        await self.bot.wait_until_ready()
        logger.info("[LogCog] before_loop: Бот готов.")
        # Лог о готовности задачи теперь выводится в __init__ после успешного запуска


async def setup(bot: commands.Bot):
    """Добавляет LoggingCog к боту."""
    logger.info("[LogCog] Вызов setup для LoggingCog.")
    await bot.add_cog(LoggingCog(bot))
