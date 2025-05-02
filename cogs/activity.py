import discord
from discord.ext import commands, tasks
from discord import app_commands # Импортируем для описаний параметров
import asyncio
import logging
from datetime import datetime, timedelta, time, date
import pytz
from collections import defaultdict
from typing import Dict, Tuple, Optional, List # Убираем Set, DefaultDict, ButtonStyle, Interaction, Any

# Импортируем менеджер данных
from utils.activity_data_manager import ActivityDataManager
# Импортируем компоненты из нового пакета utils.activity
from utils.activity.views import ActivityView, StatsView
from utils.activity.reports import run_automatic_daily_report, run_automatic_monthly_report, send_daily_report, send_monthly_report, MONTH_NAMES_RU
from utils.activity.helpers import format_time_short, is_application

# Логгер для кога
logger = logging.getLogger("bot.activity") # Используем иерархическое имя

class ActivityTracker(commands.Cog):
    """
    Ког для отслеживания игровой активности пользователей,
    генерации отчетов и предоставления статистики.
    """

    def __init__(self, bot: commands.Bot):
        """
        Инициализация кога ActivityTracker.

        Args:
            bot: Экземпляр бота.
        """
        self.bot = bot
        # Инициализируем менеджер данных
        self.data_manager = ActivityDataManager()
        logger.info("Инициализация ActivityDataManager завершена.")

        # Словарь для отслеживания текущих активных игровых сессий в памяти
        # {user_id: (game_name, start_time_utc)}
        self.current_activities: Dict[int, Tuple[str, datetime]] = {}

        # Флаг для предотвращения многократного запуска сканирования при on_ready
        self.scan_scheduled = False

        # Запуск фоновых задач
        try:
            self.periodic_save.start()
            self.daily_report.start()
            self.monthly_report.start()
            logger.info("Фоновые задачи ActivityTracker запущены.")
        except Exception as e:
            logger.error(f"Не удалось запустить фоновые задачи ActivityTracker: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_ready(self):
        """Выполняется при готовности бота, запускает начальное сканирование активности."""
        # Используем флаг, чтобы сканирование выполнялось только один раз,
        # даже если on_ready вызывается несколько раз (например, при переподключениях).
        if not self.scan_scheduled:
            self.scan_scheduled = True
            logger.info("Бот готов. Запуск начального сканирования активности...")
            # Запускаем сканирование асинхронно, чтобы не блокировать on_ready
            asyncio.create_task(self.scan_all_users_activity())

    async def scan_all_users_activity(self):
        """
        Сканирует активность всех пользователей на всех серверах при запуске бота.
        Обнаруживает уже идущие игровые сессии и записывает их начало.
        """
        try:
            # Ожидаем полной готовности кеша пользователей
            await self.bot.wait_until_ready()
            logger.info("Начинаем сканирование активности всех пользователей после запуска.")
            now_utc = datetime.now(pytz.UTC)
            found_activities = 0
            for guild in self.bot.guilds:
                for member in guild.members:
                    # Пропускаем ботов и известные приложения
                    if member.bot or is_application(member):
                        continue

                    # Ищем активную игру (ActivityType.playing)
                    playing_activity = None
                    for activity in member.activities:
                        if activity.type == discord.ActivityType.playing:
                            playing_activity = activity
                            break # Берем первую найденную игру

                    if playing_activity:
                        # Записываем начало сессии в память
                        self.current_activities[member.id] = (playing_activity.name, now_utc)
                        found_activities += 1
                        logger.debug(f"Обнаружена активная игра у {member.name} ({member.id}): {playing_activity.name}")

            logger.info(f"Сканирование завершено. Обнаружено {found_activities} активных игровых сессий.")

            # Важно: Не обновляем БД сразу после сканирования,
            # так как это может привести к записи нулевой длительности.
            # periodic_save обработает эти сессии позже.

        except Exception as e:
            logger.error(f"Ошибка при сканировании активности пользователей: {e}", exc_info=True)

    def cog_unload(self):
        """Выполняется при выгрузке кога, останавливает фоновые задачи."""
        self.daily_report.cancel()
        self.monthly_report.cancel()
        self.periodic_save.cancel()
        logger.info("Фоновые задачи ActivityTracker остановлены.")
        # Попытка сохранить последние данные об активности перед выгрузкой
        # Используем asyncio.run для синхронного выполнения в cog_unload
        # (create_task может не успеть выполниться)
        try:
            logger.info("Попытка финального сохранения активности перед выгрузкой...")
            # Запускаем синхронно, чтобы гарантировать выполнение
            asyncio.run(self.update_current_activities(final_save=True))
            logger.info("Финальное сохранение активности завершено.")
        except RuntimeError as e:
            # Может возникнуть, если цикл событий уже остановлен
             logger.warning(f"Не удалось выполнить финальное сохранение активности (возможно, цикл событий остановлен): {e}")
        except Exception as e:
            logger.error(f"Ошибка при финальном сохранении активности во время выгрузки: {e}", exc_info=True)
        logger.info("Ког ActivityTracker выгружен.")

    # --- Логика обновления активности (остается в коге, т.к. работает с self.current_activities) ---
    async def update_current_activities(self, final_save: bool = False):
        """
        Обновляет статистику для текущих активных сессий, записывая данные в БД.
        Вызывается периодически задачей periodic_save и при завершении сессии в on_presence_update.

        Args:
            final_save: Если True, выполняется финальное сохранение перед выгрузкой кога.
                        В этом режиме время старта в current_activities не обновляется.
        """
        now_utc = datetime.now(pytz.UTC)
        tasks_to_run = []
        users_to_update_start_time = {} # Для обновления времени старта в памяти

        if not self.current_activities:
            logger.debug("update_current_activities: Нет активных сессий для обновления.")
            return # Нечего обновлять

        logger.debug(f"update_current_activities: Обновление {len(self.current_activities)} активных сессий...")

        for user_id, (game_name, start_time) in list(self.current_activities.items()):
            elapsed_seconds = int((now_utc - start_time).total_seconds())

            # Минимальный порог для записи (например, 10 секунд)
            min_record_threshold = 10
            # Максимальный порог (например, 24 часа), чтобы избежать нереальных значений при сбоях
            max_record_threshold = 86400 * 2 # 2 дня

            if elapsed_seconds >= min_record_threshold and elapsed_seconds < max_record_threshold:
                # Добавляем задачу обновления в БД в список
                tasks_to_run.append(self.data_manager.update_activity(user_id, game_name, elapsed_seconds))
                # Если это не финальное сохранение, запоминаем, что нужно обновить время старта
                if not final_save:
                    users_to_update_start_time[user_id] = (game_name, now_utc)
                logger.debug(f"Подготовлено обновление для {user_id} - {game_name}: +{elapsed_seconds} сек.")
            elif elapsed_seconds < 0:
                # Обработка возможной смены системного времени или других аномалий
                logger.warning(f"Обнаружено отрицательное время ({elapsed_seconds}s) для {user_id} в {game_name}. Сбрасываем время начала сессии в памяти.")
                # Обновляем только в памяти, чтобы избежать записи отрицательного времени
                self.current_activities[user_id] = (game_name, now_utc)
            elif elapsed_seconds >= max_record_threshold:
                 logger.warning(f"Обнаружено слишком большое время ({elapsed_seconds}s > {max_record_threshold}s) для {user_id} в {game_name}. Сессия будет проигнорирована и сброшена.")
                 # Удаляем аномальную сессию из памяти, чтобы она не копилась
                 if user_id in self.current_activities and self.current_activities[user_id][0] == game_name:
                     del self.current_activities[user_id]
            # else: # elapsed_seconds < min_record_threshold - игнорируем короткие сессии

        if not tasks_to_run:
            logger.debug("update_current_activities: Нет сессий, удовлетворяющих порогу для записи в БД.")
            return # Если нечего обновлять в БД

        try:
            # Выполняем все задачи записи в БД параллельно
            await asyncio.gather(*tasks_to_run)
            logger.debug(f"update_current_activities: Успешно выполнено {len(tasks_to_run)} обновлений в БД.")

            # Обновляем время старта в памяти ПОСЛЕ успешной записи в БД (если не финальное сохранение)
            if not final_save:
                for user_id, new_start_data in users_to_update_start_time.items():
                    # Проверяем, что сессия все еще активна и игра та же
                    if user_id in self.current_activities and self.current_activities[user_id][0] == new_start_data[0]:
                        self.current_activities[user_id] = new_start_data
                        logger.debug(f"Обновлено время старта в памяти для {user_id} - {new_start_data[0]}.")

        except Exception as e:
            logger.error(f"Ошибка при пакетном обновлении активности в БД: {e}", exc_info=True)
            # Время старта в памяти не обновляется при ошибке, чтобы попытаться записать позже

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """
        Отслеживает изменения статуса и игровой активности пользователей.
        Записывает завершенные сессии и начало новых.
        """
        # Игнорируем ботов и приложения
        if after.bot or is_application(after): # Используем хелпер
            return

        try:
            now_utc = datetime.now(pytz.UTC)
            user_id = after.id

            # Определяем, в какие игры играл пользователь до и после обновления
            before_game = None
            for act in before.activities:
                if act.type == discord.ActivityType.playing:
                    before_game = act.name
                    break

            after_game = None
            for act in after.activities:
                if act.type == discord.ActivityType.playing:
                    after_game = act.name
                    break

            # Если игра не изменилась (или ее не было и нет), ничего не делаем
            if before_game == after_game:
                return

            logger.debug(f"Изменение активности {after.name} ({user_id}): '{before_game}' -> '{after_game}'")

            # --- Обработка завершения игры ---
            if before_game is not None:
                # Проверяем, отслеживали ли мы эту сессию
                if user_id in self.current_activities and self.current_activities[user_id][0] == before_game:
                    start_time = self.current_activities[user_id][1]
                    elapsed_seconds = int((now_utc - start_time).total_seconds())

                    # Удаляем завершенную сессию из памяти ДО записи в БД,
                    # чтобы избежать состояния гонки, если событие придет снова быстро.
                    del self.current_activities[user_id]
                    logger.debug(f"Сессия {user_id} - {before_game} удалена из памяти.")

                    # Записываем в БД, если время сессии достаточное
                    min_record_threshold = 10
                    if elapsed_seconds >= min_record_threshold:
                        logger.debug(f"Завершилась сессия {user_id} - {before_game} ({elapsed_seconds} сек). Запись в БД...")
                        # Запускаем запись асинхронно, чтобы не блокировать обработчик событий
                        asyncio.create_task(self.data_manager.update_activity(user_id, before_game, elapsed_seconds))
                    else:
                        logger.debug(f"Сессия {user_id} - {before_game} была слишком короткой ({elapsed_seconds} сек), пропуск записи.")

            # --- Обработка начала новой игры ---
            if after_game is not None:
                # Если пользователь уже играет во что-то другое (маловероятно, но возможно),
                # или если сессия уже есть (например, после перезапуска бота), обновляем время начала.
                if user_id not in self.current_activities or self.current_activities[user_id][0] != after_game:
                     self.current_activities[user_id] = (after_game, now_utc)
                     logger.debug(f"Началась новая сессия: {user_id} - {after_game}")
                # else: # Сессия этой игры уже отслеживается, ничего не делаем

        except Exception as e:
            logger.error(f"Ошибка при обработке изменения присутствия для {after.name} ({after.id}): {e}", exc_info=True)

    # --- Фоновые задачи ---

    @tasks.loop(minutes=5)
    async def periodic_save(self):
        """Периодически обновляет время текущих активных сессий в БД."""
        logger.debug("periodic_save: Запуск периодического сохранения...")
        try:
            # Вызываем метод обновления, который работает с self.current_activities
            await self.update_current_activities()
            logger.debug("periodic_save: Периодическое сохранение завершено.")
        except Exception as e:
            # Логируем ошибку, но задача должна продолжать работать
            logger.error(f"Ошибка в задаче periodic_save: {e}", exc_info=True)

    @periodic_save.before_loop
    async def before_periodic_save(self):
        """Ожидает готовности бота перед первым запуском periodic_save."""
        try:
            logger.debug("before_periodic_save: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача periodic_save готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug("before_periodic_save: Бот еще не инициализирован, задача будет запущена позже.")
            else:
                logger.error(f"Ошибка в before_periodic_save: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_periodic_save: {e}", exc_info=True)

    @tasks.loop(time=time(hour=12, minute=0, tzinfo=pytz.timezone('Europe/Moscow'))) # 12:00 МСК
    async def monthly_report(self):
        """Выполняет автоматическую логику ежемесячного отчета."""
        logger.info("monthly_report: Запуск автоматической задачи ежемесячного отчета...")
        # Вызываем перенесенную логику
        await run_automatic_monthly_report(self)
        logger.info("monthly_report: Автоматическая задача ежемесячного отчета завершена.")


    @monthly_report.before_loop
    async def before_monthly_report(self):
        """Ожидает готовности бота перед первым запуском ежемесячной задачи."""
        try:
            logger.debug("before_monthly_report: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача monthly_report готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug("before_monthly_report: Бот еще не инициализирован, задача будет запущена позже.")
            else:
                logger.error(f"Ошибка в before_monthly_report: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_monthly_report: {e}", exc_info=True)

    # Устанавливаем правильный часовой пояс для времени запуска
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=pytz.timezone('Europe/Moscow'))) # 00:00 МСК
    async def daily_report(self):
        """Выполняет автоматическую логику ежедневного отчета."""
        logger.info("daily_report: Запуск автоматической задачи ежедневного отчета...")
        # Вызываем перенесенную логику
        await run_automatic_daily_report(self)
        logger.info("daily_report: Автоматическая задача ежедневного отчета завершена.")


    @daily_report.before_loop
    async def before_daily_report(self):
        """Ожидает готовности бота перед первым запуском ежедневной задачи."""
        try:
            logger.debug("before_daily_report: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача daily_report готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug("before_daily_report: Бот еще не инициализирован, задача будет запущена позже.")
            else:
                logger.error(f"Ошибка в before_daily_report: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_daily_report: {e}", exc_info=True)


    # --- Команды ---

    @commands.hybrid_command(
        name="activity",
        description='Показать текущую статистику игровой активности за сегодня.'
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(test_mode="[Только для теста] Использовать тестовые данные, если реальных нет.")
    async def activity_command(self, ctx: commands.Context, test_mode: bool = False):
        """
        Показывает статистику игровой активности за СЕГОДНЯШНИЙ день.
        Доступно администраторам. Позволяет использовать тестовые данные.
        """
        logger.info(f"Команда /activity вызвана пользователем {ctx.author} (ID: {ctx.author.id}), test_mode={test_mode}")
        try:
            # Обновляем текущие сессии перед показом статистики
            await self.update_current_activities()
            today_data = await self.data_manager.get_daily_stats(date.today())

            # Генерация тестовых данных, если запрошено и реальных данных нет
            if not today_data and test_mode:
                logger.info("Генерация тестовых данных для /activity.")
                today_data = { ctx.author.id: {"Test Game 1": 3660, "Test Game 2": 1800} }
                # Пытаемся добавить еще пару пользователей для теста
                if ctx.guild:
                    members = [m for m in ctx.guild.members if not m.bot and m.id != ctx.author.id][:2]
                    if len(members) > 0: today_data[members[0].id] = {"Another Game": 7200}
                    if len(members) > 1: today_data[members[1].id] = {"Test Game 1": 1200, "Third Game": 5000}

            if not today_data:
                await ctx.send("Сегодня пока никто не играл в игры 😢", ephemeral=True)
                return

            # Создаем и отправляем View
            # Передаем bot вместо cog
            view = ActivityView(self.bot, today_data, ctx=ctx, report_type="command")
            prefix = "**[ТЕСТ]** " if test_mode else ""
            message_content = f"{prefix}Статистика активности за сегодня:"
            # Отправляем как обычное сообщение, чтобы кнопки были видны всем
            message = await ctx.send(content=f"{message_content}\n{view.get_current_content()}", view=view)
            view.message = message # Сохраняем для таймаута

        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /activity: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}", ephemeral=True)

    @commands.hybrid_command(
        name="mystats",
        description='Показать статистику игровой активности пользователя за месяц.'
    )
    @app_commands.describe(
        user="Пользователь, чью статистику показать (по умолчанию - вы).",
        month="Месяц (число от 1 до 12, по умолчанию - текущий).",
        year="Год (по умолчанию - текущий)."
    )
    async def mystats_command(self, ctx: commands.Context, user: Optional[discord.Member] = None, month: Optional[int] = None, year: Optional[int] = None):
        """
        Показывает статистику игровой активности пользователя за указанный месяц (или текущий).
        Использует пагинацию через эмбед и кнопки.
        """
        target_user = user if user else ctx.author
        logger.info(f"Команда /mystats вызвана {ctx.author} для {target_user} (Месяц: {month}, Год: {year})")

        try:
            user_id = target_user.id
            today = date.today()

            # Валидация и установка значений по умолчанию для года и месяца
            target_year = year if year is not None else today.year
            if month is not None:
                if not 1 <= month <= 12:
                    await ctx.send("Неверный номер месяца. Укажите число от 1 до 12.", ephemeral=True)
                    return
                target_month = month
            else:
                target_month = today.month

            # Проверка, является ли запрашиваемый период текущим месяцем
            is_current_month = (target_year == today.year and target_month == today.month)

            # Обновляем текущие сессии, если смотрим статистику за текущий месяц
            if is_current_month:
                await self.update_current_activities()

            # Получаем месячные данные из БД
            monthly_data = await self.data_manager.get_monthly_stats(user_id, target_year, target_month)

            # Если текущий месяц, добавляем данные за сегодня из daily_activity
            if is_current_month:
                today_stats = await self.data_manager.get_daily_stats(today)
                if user_id in today_stats:
                    for game, seconds in today_stats[user_id].items():
                        monthly_data[game] = monthly_data.get(game, 0) + seconds

            # Формируем заголовок и проверяем наличие данных
            month_name = MONTH_NAMES_RU.get(target_month, str(target_month))
            data_period_str = f"за {month_name} {target_year}" if month is not None or year is not None else "за текущий месяц"

            if not monthly_data:
                embed = discord.Embed(
                    title=f"📊 Статистика {target_user.display_name}",
                    description=f"Нет данных об активности {data_period_str} 😢",
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed, ephemeral=True)
                return

            # Сортируем игры по времени
            sorted_games: List[Tuple[str, int]] = sorted(monthly_data.items(), key=lambda item: item[1], reverse=True)

            # Создаем и отправляем View
            title = f"📊 Статистика {target_user.display_name} {data_period_str}"
            # Убираем cog из StatsView
            view = StatsView(title, sorted_games, user=target_user, items_per_page=10) # Увеличим кол-во игр на страницу
            message = await ctx.send(embed=view.get_current_embed(), view=view, ephemeral=True) # Статистика обычно персональная
            view.message = message

            # Показываем текущую сессию, если смотрим текущий месяц
            if is_current_month and user_id in self.current_activities:
                game_name, start_time = self.current_activities[user_id]
                now_utc = datetime.now(pytz.UTC)
                current_session_seconds = int((now_utc - start_time).total_seconds())
                if current_session_seconds > 10: # Показываем только если сессия длится > 10 сек
                    current_info = f"🔴 **{target_user.display_name}** сейчас играет в **{game_name}** (текущая сессия: {format_time_short(current_session_seconds)})"
                    # Отправляем отдельно и тоже эфемерно
                    await ctx.send(current_info, ephemeral=True)

        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /mystats: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}", ephemeral=True)

    @commands.hybrid_command(
        name="mystatsall",
        description="Показывает статистику игровой активности пользователя за всё время."
    )
    @app_commands.describe(user="Пользователь, чью статистику показать (по умолчанию - вы).")
    async def mystatsall_command(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        Показывает суммарную статистику игровой активности пользователя за всё время.
        """
        target_user = user if user else ctx.author
        logger.info(f"Команда /mystatsall вызвана {ctx.author} для {target_user}")

        try:
            user_id = target_user.id
            # Обновляем текущие сессии перед получением статистики за всё время
            await self.update_current_activities()
            all_user_games = await self.data_manager.get_all_time_stats(user_id)

            if not all_user_games:
                embed = discord.Embed(
                    title=f"📊 Статистика {target_user.display_name}",
                    description="Нет данных об активности за всё время 😢",
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await ctx.send(embed=embed, ephemeral=True)
                return

            # Сортируем игры по времени
            sorted_games: List[Tuple[str, int]] = sorted(all_user_games.items(), key=lambda item: item[1], reverse=True)

            # Создаем и отправляем View
            title = f"📊 Статистика {target_user.display_name} за всё время"
            view = StatsView(title, sorted_games, user=target_user, items_per_page=10)
            message = await ctx.send(embed=view.get_current_embed(), view=view, ephemeral=True)
            view.message = message

        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /mystatsall: {e}", exc_info=True)
            await ctx.send(f"Произошла ошибка при получении статистики: {e}", ephemeral=True)

    # --- Команды для ручного запуска отчетов ---

    @commands.hybrid_command(
        name="report_daily",
        description="[Админ] Отправить отчет об активности за указанный день."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        year="Год (например, 2024).",
        month="Месяц (1-12).",
        day="День (1-31)."
    )
    async def report_daily_command(self, ctx: commands.Context, year: int, month: int, day: int):
        """
        Позволяет администратору вручную запустить генерацию и отправку
        ежедневного отчета за конкретную дату. Не выполняет перенос данных.
        """
        logger.info(f"Команда /report_daily вызвана {ctx.author} для даты {year}-{month:02d}-{day:02d}")
        try:
            target_date = date(year, month, day)
            # Проверяем, что дата не в будущем
            if target_date >= date.today():
                 await ctx.send("Нельзя генерировать отчет за сегодня или будущую дату.", ephemeral=True)
                 return

        except ValueError:
            await ctx.send("Некорректная дата. Проверьте год, месяц и день.", ephemeral=True)
            return

        try:
            await ctx.defer(ephemeral=True) # Даем боту время на генерацию
            config = getattr(self.bot, 'config', {})
            # Передаем текущий канал в функцию send_daily_report
            success = await send_daily_report(target_date, self.bot, self.data_manager, config, channel=ctx.channel)

            if success:
                # Проверяем, является ли команда слэш-командой
                if hasattr(ctx, 'interaction') and ctx.interaction:
                    await ctx.followup.send(f"Ежедневный отчет за {target_date.strftime('%d.%m.%Y')} успешно отправлен (или данных не было).", ephemeral=True)
                else:
                    await ctx.send(f"Ежедневный отчет за {target_date.strftime('%d.%m.%Y')} успешно отправлен (или данных не было).")
            else:
                if hasattr(ctx, 'interaction') and ctx.interaction:
                    await ctx.followup.send(f"Не удалось отправить ежедневный отчет за {target_date.strftime('%d.%m.%Y')}. Проверьте логи.", ephemeral=True)
                else:
                    await ctx.send(f"Не удалось отправить ежедневный отчет за {target_date.strftime('%d.%m.%Y')}. Проверьте логи.")

        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /report_daily: {e}", exc_info=True)
            try:
                # Используем followup, если взаимодействие было отложено (defer)
                if hasattr(ctx, 'interaction') and ctx.interaction and ctx.interaction.response.is_done():
                    await ctx.followup.send(f"Произошла критическая ошибка при выполнении команды: {e}", ephemeral=True)
                else:
                    await ctx.send(f"Произошла критическая ошибка при выполнении команды: {e}")
            except Exception as send_error:
                logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {send_error}")


    @commands.hybrid_command(
        name="report_monthly",
        description="[Админ] Отправить отчет об активности за указанный месяц."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        year="Год (например, 2024).",
        month="Месяц (1-12)."
    )
    async def report_monthly_command(self, ctx: commands.Context, year: int, month: int):
        """
        Позволяет администратору вручную запустить генерацию и отправку
        ежемесячного отчета за конкретный месяц и год.
        """
        logger.info(f"Команда /report_monthly вызвана {ctx.author} для периода {year}-{month:02d}")
        # Валидация месяца
        if not 1 <= month <= 12:
            await ctx.send("Неверный номер месяца. Укажите число от 1 до 12.", ephemeral=True)
            return
        # Валидация года (простая проверка на разумность)
        if not 2020 <= year <= date.today().year + 1:
             await ctx.send("Некорректный год.", ephemeral=True)
             return

        # Проверяем, что запрашиваемый период не текущий или будущий месяц
        today = date.today()
        if year > today.year or (year == today.year and month >= today.month):
             await ctx.send("Нельзя генерировать месячный отчет за текущий или будущий месяц.", ephemeral=True)
             return

        try:
            await ctx.defer(ephemeral=True) # Даем боту время на генерацию
            config = getattr(self.bot, 'config', {})
            # Передаем текущий канал в функцию send_monthly_report
            success = await send_monthly_report(year, month, self.bot, self.data_manager, config, channel=ctx.channel)

            if success:
                month_name = MONTH_NAMES_RU.get(month, str(month))
                if hasattr(ctx, 'interaction') and ctx.interaction:
                    await ctx.followup.send(f"Ежемесячный отчет за {month_name} {year} успешно отправлен (или данных не было).", ephemeral=True)
                else:
                    await ctx.send(f"Ежемесячный отчет за {month_name} {year} успешно отправлен (или данных не было).")
            else:
                if hasattr(ctx, 'interaction') and ctx.interaction:
                    await ctx.followup.send(f"Не удалось отправить ежемесячный отчет за {year}-{month:02d}. Проверьте логи.", ephemeral=True)
                else:
                    await ctx.send(f"Не удалось отправить ежемесячный отчет за {year}-{month:02d}. Проверьте логи.")

        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /report_monthly: {e}", exc_info=True)
            try:
                # Используем followup, если взаимодействие было отложено (defer)
                if hasattr(ctx, 'interaction') and ctx.interaction and ctx.interaction.response.is_done():
                    await ctx.followup.send(f"Произошла критическая ошибка при выполнении команды: {e}", ephemeral=True)
                else:
                    await ctx.send(f"Произошла критическая ошибка при выполнении команды: {e}")
            except Exception as send_error:
                logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {send_error}")


    # --- Обработчики ошибок для команд кога ---
    # (Используем общий обработчик или специфичные для каждой команды)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Локальный обработчик ошибок для команд этого кога."""
        # Обработка стандартных ошибок
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("У вас недостаточно прав для использования этой команды.", ephemeral=True)
        elif isinstance(error, commands.UserInputError):
             await ctx.send(f"Ошибка ввода: {error}", ephemeral=True)
        elif isinstance(error, commands.UserNotFound):
             await ctx.send("Не удалось найти указанного пользователя. Проверьте правильность имени или ID.", ephemeral=True)
        # Обработка ошибок app_commands (например, при неверном типе параметра)
        elif isinstance(error, app_commands.AppCommandError):
             logger.warning(f"Ошибка AppCommand в ActivityTracker: {error}", exc_info=True)
             await ctx.send(f"Произошла ошибка команды: {error}", ephemeral=True)
        else:
            # Логируем все остальные ошибки
            logger.error(f"Необработанная ошибка в команде кога ActivityTracker ({ctx.command.name if ctx.command else 'N/A'}): {error}", exc_info=True)
            # Отправляем общее сообщение пользователю
            try:
                # Используем followup, если взаимодействие было отложено (defer)
                if ctx.interaction and ctx.interaction.response.is_done():
                     await ctx.followup.send("Произошла непредвиденная ошибка при выполнении команды.", ephemeral=True)
                else:
                     await ctx.send("Произошла непредвиденная ошибка при выполнении команды.", ephemeral=True)
            except Exception as send_error:
                 logger.error(f"Не удалось отправить сообщение об ошибке пользователю: {send_error}")


async def setup(bot: commands.Bot):
    """Загружает ког ActivityTracker в бота."""
    await bot.add_cog(ActivityTracker(bot))
    logger.info("Ког ActivityTracker успешно загружен.")
