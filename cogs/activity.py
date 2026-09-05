"""Ког для отслеживания игровой активности пользователей.

Генерирует отчеты и предоставляет статистику активности.
Этот модуль отвечает за:
- Отслеживание игровой активности пользователей в реальном времени
- Сохранение статистики активности в базу данных
- Генерацию ежедневных и ежемесячных отчетов
- Предоставление команд для просмотра статистики активности
- Автоматическое выполнение периодических задач по сохранению и отчетности

Модуль использует систему фоновых задач discord.ext.tasks для периодического
сохранения данных и генерации отчетов в заданное время.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import get_settings
from utils.activity.helpers import is_application
from utils.activity.reports import (
    MONTH_NAMES_RU,
    run_automatic_daily_report,
    run_automatic_monthly_report,
    send_daily_report,
    send_monthly_report,
)
from utils.activity.views import ActivityView
from utils.activity_data_manager import ActivityDataManager
from utils.error_handler import command_error_handler, safe_send, safe_send_error
from utils.time_utils import MOSCOW_TZ, moscow_today, split_interval_by_local_date

logger: logging.Logger = logging.getLogger("bot.cogs.activity")


class ActivityTracker(commands.Cog):
    """Ког для отслеживания игровой активности пользователей.

    Генерирует отчеты и предоставляет статистику.
    Отслеживает, какие игры запускают пользователи и как долго они играют,
    сохраняет эту информацию в базу данных и предоставляет команды для
    просмотра статистики. Также автоматически генерирует ежедневные и
    ежемесячные отчеты об активности.

    Attributes:
        bot: Экземпляр бота Discord.
        data_manager: Менеджер данных для работы с базой данных активности.
        current_activities: Словарь текущих активных игровых сессий в памяти.
        scan_scheduled: Флаг для предотвращения многократного запуска сканирования.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        Инициализация кога ActivityTracker.

        Args:
            bot: Экземпляр бота.
        """
        self.bot: commands.Bot = bot
        self.data_manager: ActivityDataManager = ActivityDataManager()
        logger.info("Инициализация ActivityDataManager завершена.")

        # {user_id: (game_name, start_time_utc)}
        self.current_activities: dict[int, tuple[str, datetime]] = {}
        self._pending_activity: dict[tuple[int, str, date], int] = {}
        self._activity_lock = asyncio.Lock()

        self.scan_scheduled = False

        try:
            # Интервал берём из настроек тут, а не в декораторе — иначе он замораживается
            # на момент импорта модуля и правки YAML/env не подхватываются.
            periodic_save_seconds = get_settings().timeouts.activity_periodic_save
            self.periodic_save.change_interval(seconds=periodic_save_seconds)
            self.periodic_save.start()
            self.daily_report.start()
            self.monthly_report.start()
            logger.info(
                "Фоновые задачи ActivityTracker запущены (periodic_save=%ss).",
                periodic_save_seconds,
            )
        except Exception as e:
            logger.error(f"Не удалось запустить фоновые задачи ActivityTracker: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Выполняется при готовности бота, запускает начальное сканирование активности."""
        if not self.scan_scheduled:
            self.scan_scheduled = True
            logger.info("Бот готов. Запуск начального сканирования активности...")
            await self.scan_all_users_activity()

    async def scan_all_users_activity(self) -> None:
        """Сканирует активность всех пользователей на сервере при запуске бота."""
        try:
            await self.bot.wait_until_ready()
            logger.info("Начинаем сканирование активности всех пользователей после запуска.")
            guild = self.bot.guilds[0] if self.bot.guilds else None
            if guild is None:
                logger.warning("scan_all_users_activity: бот не подключен ни к одному серверу.")
                return

            now_utc = datetime.now(UTC)
            found_activities = 0
            async with self._activity_lock:
                for member in guild.members:
                    if member.bot or is_application(member):
                        continue

                    playing_activity = None
                    for activity in member.activities:
                        if activity.type == discord.ActivityType.playing:
                            playing_activity = activity
                            break

                    if playing_activity and playing_activity.name:
                        assert playing_activity.name is not None
                        self.current_activities[member.id] = (playing_activity.name, now_utc)
                        found_activities += 1
                        logger.debug(
                            f"Обнаружена активная игра у {member.name} ({member.id}): "
                            f"{playing_activity.name}"
                        )

            logger.info(
                f"Сканирование завершено. Обнаружено {found_activities} активных игровых сессий."
            )

        except Exception as e:
            logger.error(f"Ошибка при сканировании активности пользователей: {e}", exc_info=True)

    async def cog_unload(self) -> None:
        """
        Выполняется при выгрузке кога, останавливает фоновые задачи.

        Останавливает все фоновые задачи (daily_report, monthly_report, periodic_save)
        и выполняет финальное сохранение текущих данных об активности перед выгрузкой.
        """
        self.daily_report.cancel()
        self.monthly_report.cancel()
        self.periodic_save.cancel()
        logger.info("Фоновые задачи ActivityTracker остановлены.")
        # Попытка сохранить последние данные об активности перед выгрузкой
        try:
            logger.info("Попытка финального сохранения активности перед выгрузкой...")
            await self.update_current_activities(final_save=True)
            logger.info("Финальное сохранение активности завершено.")
        except RuntimeError as e:
            logger.warning(
                "Не удалось выполнить финальное сохранение активности "
                f"(возможно, цикл событий остановлен): {e}"
            )
        except Exception as e:
            logger.error(
                f"Ошибка при финальном сохранении активности во время выгрузки: {e}", exc_info=True
            )
        logger.info("Ког ActivityTracker выгружен.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Очищает активную сессию пользователя, покинувшего сервер.

        При выходе участника из сервера Discord не генерирует on_presence_update,
        поэтому активная сессия может остаться в памяти и накапливать фиктивное время.
        """
        if member.bot:
            return

        async with self._activity_lock:
            await self._close_member_session(member)

    async def _close_member_session(self, member: discord.Member) -> None:
        """Закрывает игровую сессию вышедшего участника под общим lock."""
        user_id = member.id

        # Проверяем, есть ли у пользователя активная сессия
        if user_id not in self.current_activities:
            return

        game_name, start_time = self.current_activities.pop(user_id)
        now_utc = datetime.now(UTC)
        elapsed_seconds = int((now_utc - start_time).total_seconds())

        # Записываем валидную часть в БД
        settings = get_settings()
        min_threshold = settings.timeouts.activity_min_record
        max_threshold = settings.timeouts.activity_max_record

        if min_threshold <= elapsed_seconds < max_threshold:
            logger.info(
                f"Пользователь {member.name} ({user_id}) покинул сервер. "
                f"Сохраняем сессию {game_name} ({elapsed_seconds} сек) в БД."
            )
            self._queue_activity_interval(user_id, game_name, start_time, now_utc)
        else:
            logger.info(
                f"Пользователь {member.name} ({user_id}) покинул сервер. "
                f"Сессия {game_name} ({elapsed_seconds} сек) не записана "
                f"(вне допустимого диапазона)."
            )

        await self._flush_pending_activity()

    def _queue_activity_interval(
        self,
        user_id: int,
        game_name: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        """Фиксирует интервал для записи под общим lock, не продлевая его при сбое БД."""
        for target_date, seconds in split_interval_by_local_date(started_at, ended_at):
            key = (user_id, game_name, target_date)
            self._pending_activity[key] = self._pending_activity.get(key, 0) + seconds

    async def _flush_pending_activity(self) -> None:
        """Записывает накопленные интервалы; неудачные записи остаются для повтора."""
        for key, seconds in list(self._pending_activity.items()):
            user_id, game_name, target_date = key
            try:
                await self.data_manager.update_activity(
                    user_id,
                    game_name,
                    seconds,
                    target_date=target_date,
                )
            except Exception:
                logger.exception(
                    "Не удалось сохранить активность %s (%s) за %s; интервал оставлен для повтора",
                    user_id,
                    game_name,
                    target_date,
                )
                return
            del self._pending_activity[key]

    async def update_current_activities(self, final_save: bool = False) -> None:
        """Обновляет статистику для текущих активных сессий, записывая данные в БД.

        Вызывается периодически задачей periodic_save и при завершении сессии в on_presence_update.

        Args:
            final_save: Если True, выполняется финальное сохранение перед выгрузкой кога.
                        В этом режиме время старта в current_activities не обновляется.
        """
        async with self._activity_lock:
            await self._update_current_activities(final_save=final_save)
            await self._flush_pending_activity()

    async def _update_current_activities(self, *, final_save: bool) -> None:
        """Сохраняет активные сессии; вызывается только под ``_activity_lock``."""
        now_utc = datetime.now(UTC)
        if not self.current_activities:
            logger.debug("update_current_activities: Нет активных сессий для обновления.")
            return

        logger.debug(
            f"update_current_activities: Обновление "
            f"{len(self.current_activities)} активных сессий..."
        )
        guild = self.bot.guilds[0] if self.bot.guilds else None
        settings = get_settings()
        min_record_threshold = settings.timeouts.activity_min_record
        max_record_threshold = settings.timeouts.activity_max_record

        for user_id, (game_name, start_time) in list(self.current_activities.items()):
            elapsed_seconds = int((now_utc - start_time).total_seconds())
            is_stale = guild is not None and guild.get_member(user_id) is None

            if elapsed_seconds >= min_record_threshold and elapsed_seconds < max_record_threshold:
                self._queue_activity_interval(user_id, game_name, start_time, now_utc)

                if is_stale:
                    self.current_activities.pop(user_id, None)
                    logger.warning(
                        "Закрыта зависшая игровая сессия %s (%s): пользователь не найден",
                        user_id,
                        game_name,
                    )
                elif not final_save:
                    self.current_activities[user_id] = (game_name, now_utc)
            elif elapsed_seconds < 0:
                logger.warning(
                    f"Обнаружено отрицательное время ({elapsed_seconds}s) для {user_id} "
                    f"в {game_name}. "
                    "Сбрасываем время начала сессии в памяти."
                )
                self.current_activities[user_id] = (game_name, now_utc)
            elif elapsed_seconds >= max_record_threshold:
                logger.warning(
                    f"Обнаружено слишком большое время ({elapsed_seconds}s > "
                    f"{max_record_threshold}s) "
                    f"для {user_id} в {game_name}. Сессия будет проигнорирована и сброшена."
                )
                if (
                    user_id in self.current_activities
                    and self.current_activities[user_id][0] == game_name
                ):
                    del self.current_activities[user_id]
            elif is_stale:
                self.current_activities.pop(user_id, None)
                logger.warning(
                    "Удалена короткая зависшая игровая сессия %s (%s)", user_id, game_name
                )

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Отслеживает изменения статуса и игровой активности пользователей.

        Записывает завершенные сессии и начало новых.
        """
        # Игнорируем ботов и приложения
        if after.bot or is_application(after):  # Используем хелпер
            return

        async with self._activity_lock:
            await self._process_presence_update(before, after)

    async def _process_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Изменяет игровую сессию участника под общим lock."""
        try:
            now_utc = datetime.now(UTC)
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

            logger.debug(
                f"Изменение активности {after.name} ({user_id}): '{before_game}' -> '{after_game}'"
            )

            # --- Обработка завершения игры ---
            if before_game is not None:
                # Проверяем, отслеживали ли мы эту сессию
                if (
                    user_id in self.current_activities
                    and self.current_activities[user_id][0] == before_game
                ):
                    _, start_time = self.current_activities.pop(user_id)
                    elapsed_seconds = int((now_utc - start_time).total_seconds())

                    # Записываем в БД, если время сессии достаточное
                    settings = get_settings()
                    min_record_threshold = settings.timeouts.activity_min_record
                    if elapsed_seconds >= min_record_threshold:
                        logger.debug(
                            f"Завершилась сессия {user_id} - {before_game} "
                            f"({elapsed_seconds} сек). Запись в БД..."
                        )
                        self._queue_activity_interval(
                            user_id,
                            before_game,
                            start_time,
                            now_utc,
                        )
                    else:
                        logger.debug(
                            f"Сессия {user_id} - {before_game} была слишком короткой "
                            f"({elapsed_seconds} сек), пропуск записи."
                        )

                    logger.debug(f"Сессия {user_id} - {before_game} удалена из памяти.")

            # --- Обработка начала новой игры ---
            if after_game is not None:
                # Если пользователь уже играет во что-то другое (маловероятно, но возможно),
                # или если сессия уже есть (например, после перезапуска бота),
                # обновляем время начала.
                if (
                    user_id not in self.current_activities
                    or self.current_activities[user_id][0] != after_game
                ):
                    self.current_activities[user_id] = (after_game, now_utc)
                    logger.debug(f"Началась новая сессия: {user_id} - {after_game}")

            await self._flush_pending_activity()

        except Exception as e:
            logger.error(
                f"Ошибка при обработке изменения присутствия для {after.name} ({after.id}): {e}",
                exc_info=True,
            )

    # --- Фоновые задачи ---

    # Реальный интервал ставится в cog_load через change_interval(...).
    @tasks.loop(seconds=60)
    async def periodic_save(self) -> None:
        """
        Периодически обновляет время текущих активных сессий в БД.

        Запускается каждые 5 минут и вызывает метод update_current_activities
        для сохранения прогресса текущих игровых сессий в базу данных.
        Это позволяет не потерять данные при перезапуске бота или сбоях.
        """
        logger.debug("periodic_save: Запуск периодического сохранения...")
        try:
            # Вызываем метод обновления, который работает с self.current_activities
            await self.update_current_activities()
            logger.debug("periodic_save: Периодическое сохранение завершено.")
        except Exception as e:
            # Логируем ошибку, но задача должна продолжать работать
            logger.error(f"Ошибка в задаче periodic_save: {e}", exc_info=True)

    @periodic_save.before_loop
    async def before_periodic_save(self) -> None:
        """Ожидает готовности бота перед первым запуском periodic_save."""
        try:
            logger.debug("before_periodic_save: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача periodic_save готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug(
                    "before_periodic_save: Бот еще не инициализирован, задача будет запущена позже."
                )
            else:
                logger.error(f"Ошибка в before_periodic_save: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_periodic_save: {e}", exc_info=True)

    @tasks.loop(time=time(hour=9, minute=0, tzinfo=UTC))  # 12:00 МСК (09:00 UTC)
    async def monthly_report(self) -> None:
        """
        Выполняет автоматическую логику ежемесячного отчета.

        Запускается в 12:00 по московскому времени (09:00 UTC) 1-го числа каждого месяца.
        Вызывает функцию run_automatic_monthly_report для генерации и отправки
        отчета об активности за предыдущий месяц.
        """
        logger.info("monthly_report: Запуск автоматической задачи ежемесячного отчета...")
        # Вызываем перенесенную логику
        await run_automatic_monthly_report(self)
        logger.info("monthly_report: Автоматическая задача ежемесячного отчета завершена.")

    @monthly_report.before_loop
    async def before_monthly_report(self) -> None:
        """Ожидает готовности бота перед первым запуском ежемесячной задачи."""
        try:
            logger.debug("before_monthly_report: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача monthly_report готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug(
                    "before_monthly_report: Бот еще не инициализирован, "
                    "задача будет запущена позже."
                )
            else:
                logger.error(f"Ошибка в before_monthly_report: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_monthly_report: {e}", exc_info=True)

    # Устанавливаем правильный часовой пояс для времени запуска (UTC)
    @tasks.loop(time=time(hour=21, minute=0, tzinfo=UTC))  # 00:00 МСК (21:00 UTC пред. дня)
    async def daily_report(self) -> None:
        """
        Выполняет автоматическую логику ежедневного отчета.

        Запускается в 00:00 по московскому времени (21:00 UTC) каждый день.
        Вызывает функцию run_automatic_daily_report для генерации и отправки
        отчета об активности за предыдущий день, а также переноса данных
        из daily_activity в monthly_activity.
        """
        now = datetime.now(MOSCOW_TZ)
        logger.info(
            "daily_report: Запуск автоматической задачи ежедневного отчета... "
            f"(фактическое время: {now.strftime('%Y-%m-%d %H:%M:%S %Z')})"
        )
        # Вызываем перенесенную логику
        await run_automatic_daily_report(self)
        now_end = datetime.now(MOSCOW_TZ)
        logger.info(
            "daily_report: Автоматическая задача ежедневного отчета завершена. "
            f"(фактическое время: {now_end.strftime('%Y-%m-%d %H:%M:%S %Z')})"
        )

    @daily_report.before_loop
    async def before_daily_report(self) -> None:
        """Ожидает готовности бота перед первым запуском ежедневной задачи."""
        try:
            logger.debug("before_daily_report: Ожидание готовности бота...")
            await self.bot.wait_until_ready()
            logger.info("Задача daily_report готова к запуску.")
        except RuntimeError as e:
            if "Client has not been properly initialised" in str(e):
                logger.debug(
                    "before_daily_report: Бот еще не инициализирован, задача будет запущена позже."
                )
            else:
                logger.error(f"Ошибка в before_daily_report: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка в before_daily_report: {e}", exc_info=True)

    # --- Команды ---

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="activity", description="Показать текущую статистику игровой активности за сегодня."
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        test_mode="[Только для теста] Использовать тестовые данные, если реальных нет."
    )
    @command_error_handler
    async def activity_command(self, ctx: commands.Context, test_mode: bool = False) -> None:
        """Показывает статистику игровой активности за СЕГОДНЯШНИЙ день.

        Доступно администраторам. Позволяет использовать тестовые данные.
        """
        logger.info(
            f"Команда /activity вызвана пользователем {ctx.author} "
            f"(ID: {ctx.author.id}), test_mode={test_mode}"
        )
        # Обновляем текущие сессии перед показом статистики
        await self.update_current_activities()
        today_data = await self.data_manager.get_daily_stats(moscow_today())

        # Генерация тестовых данных, если запрошено и реальных данных нет
        if not today_data and test_mode:
            logger.info("Генерация тестовых данных для /activity.")
            today_data = {ctx.author.id: {"Test Game 1": 3660, "Test Game 2": 1800}}
            # Пытаемся добавить еще пару пользователей для теста
            if ctx.guild:
                members = [m for m in ctx.guild.members if not m.bot and m.id != ctx.author.id][:2]
                if len(members) > 0:
                    today_data[members[0].id] = {"Another Game": 7200}
                if len(members) > 1:
                    today_data[members[1].id] = {"Test Game 1": 1200, "Third Game": 5000}

        if not today_data:
            await safe_send(ctx, "Сегодня пока никто не играл в игры 😢", ephemeral=True)
            return

        # Создаем и отправляем View
        view = ActivityView(self.bot, today_data, ctx=ctx, report_type="command")
        prefix = "**[ТЕСТ]** " if test_mode else ""
        message_content = f"{prefix}Статистика активности за сегодня:"
        # Отправляем как обычное сообщение, чтобы кнопки были видны всем
        message = await ctx.send(
            content=f"{message_content}\n{view.get_current_content()}", view=view
        )
        view.message = message  # Сохраняем для таймаута

    # --- Команды для ручного запуска отчетов ---

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="report_daily", description="[Админ] Отправить отчет об активности за указанный день."
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(year="Год (например, 2024).", month="Месяц (1-12).", day="День (1-31).")
    @command_error_handler
    async def report_daily_command(
        self, ctx: commands.Context, year: int, month: int, day: int
    ) -> None:
        """Позволяет администратору вручную запустить генерацию и отправку ежедневного отчета.

        Отчет генерируется за конкретную дату. Не выполняет перенос данных.
        """
        logger.info(
            f"Команда /report_daily вызвана {ctx.author} для даты {year}-{month:02d}-{day:02d}"
        )
        try:
            target_date = date(year, month, day)
        except ValueError:
            await safe_send_error(ctx, "Некорректная дата. Проверьте год, месяц и день.")
            return

        if target_date >= moscow_today():
            await safe_send_error(ctx, "Нельзя генерировать отчет за сегодня или будущую дату.")
            return

        await ctx.defer(ephemeral=True)  # Даем боту время на генерацию
        report_channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        success = await send_daily_report(
            target_date, self.bot, self.data_manager, channel=report_channel
        )

        date_str = target_date.strftime("%d.%m.%Y")
        if success:
            await safe_send(
                ctx,
                f"Ежедневный отчет за {date_str} успешно отправлен (или данных не было).",
                ephemeral=True,
            )
        else:
            await safe_send(
                ctx,
                f"Не удалось отправить ежедневный отчет за {date_str}. Проверьте логи.",
                ephemeral=True,
            )

    @commands.hybrid_command(  # type: ignore[arg-type]
        name="report_monthly",
        description="[Админ] Отправить отчет об активности за указанный месяц.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(year="Год (например, 2024).", month="Месяц (1-12).")
    @command_error_handler
    async def report_monthly_command(self, ctx: commands.Context, year: int, month: int) -> None:
        """Позволяет администратору вручную запустить генерацию и отправку ежемесячного отчета.

        Отчет генерируется за конкретный месяц и год.
        """
        logger.info(f"Команда /report_monthly вызвана {ctx.author} для периода {year}-{month:02d}")
        if not 1 <= month <= 12:
            await safe_send_error(ctx, "Неверный номер месяца. Укажите число от 1 до 12.")
            return
        today = moscow_today()
        if not 2020 <= year <= today.year + 1:
            await safe_send_error(ctx, "Некорректный год.")
            return

        if year > today.year or (year == today.year and month >= today.month):
            await safe_send_error(
                ctx, "Нельзя генерировать месячный отчет за текущий или будущий месяц."
            )
            return

        await ctx.defer(ephemeral=True)  # Даем боту время на генерацию
        report_channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        success = await send_monthly_report(
            year, month, self.bot, self.data_manager, channel=report_channel
        )

        month_name = MONTH_NAMES_RU.get(month, str(month))
        if success:
            await safe_send(
                ctx,
                f"Ежемесячный отчет за {month_name} {year} успешно отправлен (или данных не было).",
                ephemeral=True,
            )
        else:
            await safe_send(
                ctx,
                f"Не удалось отправить ежемесячный отчет за {year}-{month:02d}. Проверьте логи.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Загружает ког ActivityTracker в бота.

    Args:
        bot: Экземпляр бота Discord.
    """
    await bot.add_cog(ActivityTracker(bot))
    logger.info("Ког ActivityTracker успешно загружен.")
