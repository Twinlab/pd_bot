from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from utils.activity.reports import (
    _get_monthly_summary_text,
    _get_report_channel,
    run_automatic_daily_report,
    run_automatic_monthly_report,
    send_daily_report,
    send_monthly_report,
)

# --- Фикстуры ---


@pytest.fixture
def mock_bot():
    """Создает мок для бота Discord."""
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)  # По умолчанию канал не найден
    # _get_report_channel читает bot.settings.channels.activity_reports и
    # bot.settings.timeouts.activity_monthly_min_time — настраиваем дефолты.
    bot.settings.channels.activity_reports = 123456789
    bot.settings.timeouts.activity_monthly_min_time = 1800
    return bot


@pytest.fixture
def mock_channel():
    """Создает мок для текстового канала Discord."""
    channel = AsyncMock(spec=discord.TextChannel)
    channel.send = AsyncMock()

    # Создаем мок для гильдии
    guild = MagicMock()
    guild.name = "Test Guild"

    # Создаем несколько моков для участников
    members = {}
    for user_id in [1, 2, 3]:
        member = MagicMock()
        member.name = f"User{user_id}"
        member.id = user_id
        members[user_id] = member

    # Настраиваем метод get_member гильдии
    guild.get_member = lambda user_id: members.get(user_id)

    # Привязываем гильдию к каналу
    channel.guild = guild

    return channel


@pytest.fixture
def mock_data_manager():
    """Создает мок для ActivityDataManager."""
    manager = AsyncMock()
    manager.get_daily_stats = AsyncMock(return_value={})  # По умолчанию пустые данные
    manager.get_aggregated_monthly_stats = AsyncMock(return_value={})  # По умолчанию пустые данные
    manager.get_pending_daily_dates = AsyncMock(return_value=[])
    manager.transfer_daily_to_monthly = AsyncMock(
        return_value=True
    )  # По умолчанию успешный перенос
    return manager


@pytest.fixture
def mock_config():
    """Заглушка для совместимости — _get_report_channel больше не читает dict-конфиг.

    Оставлено, чтобы не переписывать сигнатуры существующих тестов; реально
    используется только как фиктивный аргумент-маркер там, где старые тесты
    его передавали.
    """
    return {"REPORT_CHANNEL_ID": 123456789}


@pytest.fixture
def mock_cog(mock_bot, mock_data_manager):
    """Создает мок для кога ActivityTracker."""
    cog = MagicMock()
    cog.bot = mock_bot
    cog.data_manager = mock_data_manager
    cog.update_current_activities = AsyncMock()
    return cog


@pytest.fixture
def sample_activity_data():
    """Создает тестовые данные активности."""
    return {
        1: {"Game1": 3600, "Game2": 1800},  # User1: 1 час Game1, 30 минут Game2
        2: {"Game1": 7200},  # User2: 2 часа Game1
        3: {"Game3": 5400, "Game2": 900},  # User3: 1.5 часа Game3, 15 минут Game2
    }


@pytest.fixture
def long_activity_data():
    """Создает данные активности, которые точно приведут к разбивке сообщения."""
    data = {}
    for i in range(1, 51):  # 50 пользователей
        user_id = i
        games = {}
        for j in range(1, 6):  # 5 игр у каждого
            game_name = f"VeryLongGameNameThatTakesUpSpace_{i}_{j}"
            time_spent = (i * j * 100) % 36000 + 1800  # Разное время > 30 мин
            games[game_name] = time_spent
        data[user_id] = games
    return data


# --- Тесты для _get_report_channel ---


@pytest.mark.asyncio
async def test_get_report_channel_not_found(mock_bot):
    """Проверяет, что функция возвращает None, если канал не найден."""
    mock_bot.get_channel.return_value = None
    channel = await _get_report_channel(mock_bot)
    assert channel is None
    mock_bot.get_channel.assert_called_once_with(mock_bot.settings.channels.activity_reports)


@pytest.mark.asyncio
async def test_get_report_channel_not_text_channel(mock_bot):
    """Проверяет, что функция возвращает None, если канал не является текстовым."""
    voice_channel = MagicMock(spec=discord.VoiceChannel)
    mock_bot.get_channel.return_value = voice_channel
    channel = await _get_report_channel(mock_bot)
    assert channel is None


@pytest.mark.asyncio
async def test_get_report_channel_success(mock_bot, mock_channel):
    """Проверяет, что функция возвращает канал, если он найден и является текстовым."""
    mock_bot.get_channel.return_value = mock_channel
    channel = await _get_report_channel(mock_bot)
    assert channel is mock_channel


@pytest.mark.asyncio
async def test_get_report_channel_reads_from_bot_settings(mock_bot):
    """Канал должен браться из bot.settings.channels.activity_reports."""
    mock_bot.settings.channels.activity_reports = 999111222
    mock_bot.get_channel.return_value = None
    await _get_report_channel(mock_bot)
    mock_bot.get_channel.assert_called_once_with(999111222)


@pytest.mark.asyncio
async def test_get_report_channel_without_bot_settings(mock_bot):
    """Если у бота нет settings — функция возвращает None и не падает."""
    del mock_bot.settings
    channel = await _get_report_channel(mock_bot)
    assert channel is None


# --- Тесты для _get_monthly_summary_text ---


def test_get_monthly_summary_text_empty_data() -> None:
    """Проверяет формирование сводки для пустых данных."""
    summary = _get_monthly_summary_text({}, 5, 2024)
    assert "Май 2024" in summary
    assert "Всего активных игроков: **0**" in summary
    assert "Уникальных игр: **0**" in summary
    assert "Общее время в играх: **0m**" in summary


def test_get_monthly_summary_text_with_data(sample_activity_data) -> None:
    """Проверяет формирование сводки для тестовых данных."""
    summary = _get_monthly_summary_text(sample_activity_data, 5, 2024)

    # Проверяем заголовок
    assert "## 📊 Общая статистика за Май 2024" in summary

    # Проверяем общую информацию
    assert "Всего активных игроков: **3**" in summary
    assert "Уникальных игр: **3**" in summary

    # Проверяем самую популярную игру (Game1 - 2 игрока)
    assert "Самая популярная игра: **Game1**" in summary
    assert "(2 игрока)" in summary

    # В данном случае Game1 и самая популярная, и с наибольшим временем,
    # поэтому строка "Игра с наибольшим временем" не добавляется
    # (это предусмотрено в коде _get_monthly_summary_text)


def test_get_monthly_summary_text_same_popular_and_time_game(sample_activity_data) -> None:
    """Проверяет, что игра с наибольшим временем не дублируется,
    если она совпадает с самой популярной."""
    # Изменяем данные так, чтобы Game1 была и самой популярной, и с наибольшим временем
    data = {1: {"Game1": 5000}, 2: {"Game1": 5000}, 3: {"Game2": 1000}}

    summary = _get_monthly_summary_text(data, 5, 2024)

    # Проверяем, что есть информация о самой популярной игре
    assert "Самая популярная игра: **Game1**" in summary

    # Проверяем, что нет дублирования информации об игре с наибольшим временем
    assert "Игра с наибольшим временем:" not in summary


# --- Тесты для send_daily_report ---


@pytest.mark.asyncio
async def test_send_daily_report_channel_not_found(mock_bot, mock_data_manager):
    """Проверяет, что функция возвращает False, если канал не найден."""
    mock_bot.get_channel.return_value = None
    result = await send_daily_report(date.today(), mock_bot, mock_data_manager)
    assert result is False


@pytest.mark.asyncio
async def test_send_daily_report_no_data(mock_bot, mock_channel, mock_data_manager):
    """Проверяет отправку сообщения при отсутствии данных."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_daily_stats.return_value = {}  # Пустые данные

    result = await send_daily_report(date.today(), mock_bot, mock_data_manager)

    assert result is True
    mock_channel.send.assert_called_once()
    # Проверяем, что в сообщении есть фраза "никто не играл"
    assert "никто не играл" in mock_channel.send.call_args[0][0]


@pytest.mark.asyncio
async def test_send_daily_report_with_data(
    mock_bot, mock_channel, mock_data_manager, sample_activity_data
):
    """Проверяет отправку отчета при наличии данных."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_daily_stats.return_value = sample_activity_data

    # Мокаем ActivityView, чтобы не создавать реальный объект
    with patch("utils.activity.reports.ActivityView") as MockActivityView:
        mock_view = MagicMock()
        mock_view.get_current_content.return_value = "Test Content"
        MockActivityView.return_value = mock_view

        result = await send_daily_report(date.today(), mock_bot, mock_data_manager)

        assert result is True
        # Проверяем, что был создан ActivityView с правильными параметрами
        # Используем assert_called_once() вместо assert_called_once_with(),
        # так как date_str формируется динамически на основе текущей даты
        MockActivityView.assert_called_once()
        call_args = MockActivityView.call_args
        assert call_args.args[0] == mock_bot
        assert call_args.args[1] == sample_activity_data
        assert call_args.kwargs["report_type"] == "daily"
        assert "date_str" in call_args.kwargs  # Проверяем наличие параметра date_str
        # Проверяем, что было отправлено сообщение с контентом и view
        mock_channel.send.assert_called_once_with(content="Test Content", view=mock_view)
        # Проверяем, что сообщение было сохранено в view
        assert mock_view.message is mock_channel.send.return_value


@pytest.mark.asyncio
async def test_send_daily_report_exception(mock_bot, mock_channel, mock_data_manager):
    """Проверяет обработку исключений при отправке отчета."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_daily_stats.side_effect = Exception("Test error")

    result = await send_daily_report(date.today(), mock_bot, mock_data_manager)

    assert result is False
    # Проверяем, что было отправлено сообщение об ошибке
    assert mock_channel.send.called
    assert "Не удалось сформировать" in mock_channel.send.call_args[0][0]
    # Сообщение об ошибке не содержит детали ошибки, только общее уведомление
    assert "Попробуйте позже или обратитесь к администратору" in mock_channel.send.call_args[0][0]


# --- Тесты для send_monthly_report ---


@pytest.mark.asyncio
async def test_send_monthly_report_channel_not_found(mock_bot, mock_data_manager):
    """Проверяет, что функция возвращает False, если канал не найден."""
    mock_bot.get_channel.return_value = None
    result = await send_monthly_report(2024, 5, mock_bot, mock_data_manager)
    assert result is False


@pytest.mark.asyncio
async def test_send_monthly_report_no_data(mock_bot, mock_channel, mock_data_manager):
    """Проверяет отправку сообщения при отсутствии данных."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_aggregated_monthly_stats.return_value = {}  # Пустые данные

    result = await send_monthly_report(2024, 5, mock_bot, mock_data_manager)

    assert result is True
    mock_channel.send.assert_called_once()
    # Проверяем, что в сообщении есть фраза "Нет данных"
    assert "Нет данных" in mock_channel.send.call_args[0][0]
    assert "Май 2024" in mock_channel.send.call_args[0][0]


@pytest.mark.asyncio
async def test_send_monthly_report_with_data(
    mock_bot, mock_channel, mock_data_manager, sample_activity_data
):
    """Проверяет отправку отчета при наличии данных."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_aggregated_monthly_stats.return_value = sample_activity_data

    # Мокаем _get_monthly_summary_text, чтобы не тестировать его здесь
    with patch("utils.activity.reports._get_monthly_summary_text") as mock_summary:
        mock_summary.return_value = "## 📊 Общая статистика\nТестовая статистика"

        result = await send_monthly_report(2024, 5, mock_bot, mock_data_manager)

        assert result is True
        # Проверяем, что было отправлено сообщение
        mock_channel.send.assert_called_once()
        # Проверяем, что в сообщении есть заголовок
        assert "# 📊 Ежемесячный отчет за Май 2024" in mock_channel.send.call_args[0][0]
        # Проверяем, что была вызвана функция _get_monthly_summary_text
        mock_summary.assert_called_once_with(sample_activity_data, 5, 2024)


# Убираем skip и реализуем тест
# @pytest.mark.skip(reason="Вызывает рекурсию из-за сложной структуры моков")
@pytest.mark.asyncio
async def test_send_monthly_report_long_content(
    mock_bot, mock_channel, mock_data_manager, long_activity_data
):
    """Проверяет разбивку длинного отчета на части."""
    mock_bot.get_channel.return_value = mock_channel
    mock_data_manager.get_aggregated_monthly_stats.return_value = long_activity_data

    # Мокаем _get_monthly_summary_text и asyncio.sleep
    with (
        patch("utils.activity.reports._get_monthly_summary_text") as mock_summary,
        patch("utils.activity.reports.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_summary.return_value = "## 📊 Общая статистика\nТестовая статистика"

        result = await send_monthly_report(2024, 5, mock_bot, mock_data_manager)

        assert result is True
        # Проверяем, что send был вызван несколько раз
        # (заголовок + заголовок контента + чанки + финальная часть)
        # Точное число зависит от данных, но должно быть > 3
        assert mock_channel.send.call_count > 3
        # Проверяем, что sleep вызывался между чанками
        assert mock_sleep.called

        # Дополнительно: проверим, что первый вызов - это заголовок
        assert "# 📊 Ежемесячный отчет" in mock_channel.send.call_args_list[0].args[0]
        # Проверим, что второй вызов - это заголовок контента
        assert "## 👤 Активность всех пользователей" in mock_channel.send.call_args_list[1].args[0]
        # Проверим, что последний вызов содержит общую статистику
        assert "## 📊 Общая статистика" in mock_channel.send.call_args_list[-1].args[0]


# --- Тесты для run_automatic_daily_report ---


@pytest.mark.asyncio
async def test_run_automatic_daily_report(mock_cog, mock_channel):
    """Проверяет полную логику автоматического ежедневного отчета."""
    # Мокаем datetime.now, чтобы вернуть фиксированную дату
    with patch("utils.activity.reports.datetime") as mock_datetime:
        # Создаем мок для now
        mock_now = MagicMock()
        mock_datetime.now.return_value = mock_now

        # Настраиваем date() для mock_now
        today = date(2025, 5, 2)
        yesterday = date(2025, 5, 1)
        mock_now.date.return_value = today

        # Настраиваем мок для _get_report_channel, чтобы вернуть mock_channel
        with patch("utils.activity.reports._get_report_channel", return_value=mock_channel):
            # Настраиваем мок для send_daily_report
            with patch("utils.activity.reports.send_daily_report") as mock_send_report:
                await run_automatic_daily_report(mock_cog)

                # Проверяем, что был вызван update_current_activities
                mock_cog.update_current_activities.assert_called_once()

                # Проверяем, что был вызван send_daily_report с правильными параметрами
                # Используем any_call вместо assert_called_once_with,
                # чтобы проверить только первые три аргумента
                assert mock_send_report.call_args.args[:3] == (
                    yesterday,
                    mock_cog.bot,
                    mock_cog.data_manager,
                )

                # Проверяем, что был вызван transfer_daily_to_monthly
                mock_cog.data_manager.transfer_daily_to_monthly.assert_called_once_with(yesterday)
                mock_cog.data_manager.get_pending_daily_dates.assert_awaited_once_with(today)


@pytest.mark.asyncio
async def test_run_automatic_daily_report_transfer_failure(mock_cog, mock_channel):
    """Проверяет обработку ошибки при переносе данных."""
    # Мокаем datetime.now, чтобы вернуть фиксированную дату
    with patch("utils.activity.reports.datetime") as mock_datetime:
        # Создаем мок для now
        mock_now = MagicMock()
        mock_datetime.now.return_value = mock_now

        # Настраиваем date() для mock_now
        today = date(2025, 5, 2)
        # Переменная yesterday не используется в этом тесте
        mock_now.date.return_value = today

        # Настраиваем мок для _get_report_channel, чтобы вернуть mock_channel
        with patch("utils.activity.reports._get_report_channel", return_value=mock_channel):
            # Настраиваем мок для send_daily_report
            with patch("utils.activity.reports.send_daily_report"):
                # Настраиваем transfer_daily_to_monthly, чтобы вернуть False (ошибка)
                mock_cog.data_manager.transfer_daily_to_monthly.return_value = False

                await run_automatic_daily_report(mock_cog)

                # Проверяем, что был вызван transfer_daily_to_monthly
                mock_cog.data_manager.transfer_daily_to_monthly.assert_called_once()


@pytest.mark.asyncio
async def test_run_automatic_daily_report_archives_data_when_send_fails(mock_cog, mock_channel):
    """Архивирует дневные данные независимо от результата отправки в Discord."""
    with patch("utils.activity.reports.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.date.return_value = date(2025, 5, 2)
        mock_datetime.now.return_value = mock_now

        with (
            patch("utils.activity.reports._get_report_channel", return_value=mock_channel),
            patch(
                "utils.activity.reports.send_daily_report",
                new=AsyncMock(return_value=False),
            ),
        ):
            await run_automatic_daily_report(mock_cog)

    mock_cog.data_manager.transfer_daily_to_monthly.assert_awaited_once_with(date(2025, 5, 1))


@pytest.mark.asyncio
async def test_run_automatic_daily_report_archives_data_when_send_raises(mock_cog, mock_channel):
    """Необработанная ошибка доставки не блокирует перенос дневной статистики."""
    with patch("utils.activity.reports.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.date.return_value = date(2025, 5, 2)
        mock_datetime.now.return_value = mock_now

        with patch(
            "utils.activity.reports.send_daily_report",
            new=AsyncMock(side_effect=RuntimeError("Discord unavailable")),
        ):
            await run_automatic_daily_report(mock_cog)

    mock_cog.data_manager.transfer_daily_to_monthly.assert_awaited_once_with(date(2025, 5, 1))


@pytest.mark.asyncio
async def test_run_automatic_daily_report_archives_stale_dates_without_publishing_them(
    mock_cog, mock_channel
):
    """После простоя архивирует хвосты, но публикует только вчерашний отчёт."""
    mock_cog.data_manager.get_pending_daily_dates.return_value = [
        date(2025, 4, 29),
        date(2025, 4, 30),
    ]

    with patch("utils.activity.reports.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.date.return_value = date(2025, 5, 2)
        mock_datetime.now.return_value = mock_now

        with patch(
            "utils.activity.reports.send_daily_report",
            new=AsyncMock(return_value=True),
        ) as mock_send_report:
            await run_automatic_daily_report(mock_cog)

    processed_dates = [
        call.args[0] for call in mock_cog.data_manager.transfer_daily_to_monthly.await_args_list
    ]
    reported_dates = [call.args[0] for call in mock_send_report.await_args_list]
    assert processed_dates == [
        date(2025, 4, 29),
        date(2025, 4, 30),
        date(2025, 5, 1),
    ]
    assert reported_dates == [date(2025, 5, 1)]


# --- Тесты для run_automatic_monthly_report ---


@pytest.mark.asyncio
async def test_run_automatic_monthly_report_not_first_day(mock_cog):
    """Проверяет, что отчет не отправляется, если сегодня не 1-е число."""
    # Мокаем date.today(), чтобы вернуть не 1-е число
    with patch("utils.activity.reports.date") as mock_date:
        mock_today = MagicMock()
        mock_today.day = 2  # Не 1-е число
        mock_date.today.return_value = mock_today

        await run_automatic_monthly_report(mock_cog)

        # Проверяем, что get_aggregated_monthly_stats не был вызван
        # (так как функция должна завершиться раньше, если не 1-е число)
        mock_cog.data_manager.get_aggregated_monthly_stats.assert_not_called()


@pytest.mark.asyncio
async def test_run_automatic_monthly_report_first_day(mock_cog, mock_channel):
    """Проверяет отправку отчета, если сегодня 1-е число."""
    # Мокаем datetime.now, чтобы вернуть 1-е число
    with patch("utils.activity.reports.datetime") as mock_datetime:
        # Создаем мок для now
        mock_now = MagicMock()
        mock_datetime.now.return_value = mock_now

        # Настраиваем date() для mock_now, чтобы вернуть 1-е число
        mock_today = MagicMock()
        mock_today.day = 1  # 1-е число
        mock_now.date.return_value = mock_today

        # Создаем мок для replace
        mock_first_day = MagicMock()
        mock_today.replace.return_value = mock_first_day

        # Создаем мок для last_day_of_prev_month
        mock_last_day = MagicMock()
        mock_last_day.month = 4  # Апрель
        mock_last_day.year = 2024

        # Настраиваем вычитание дней
        mock_first_day.__sub__.return_value = mock_last_day

        # Настраиваем мок для _get_report_channel, чтобы вернуть mock_channel
        with patch("utils.activity.reports._get_report_channel", return_value=mock_channel):
            # Настраиваем мок для send_monthly_report
            with patch("utils.activity.reports.send_monthly_report") as mock_send_report:
                await run_automatic_monthly_report(mock_cog)

                # Проверяем, что был вызван send_monthly_report с правильными параметрами
                # Используем any_call вместо assert_called_once_with,
                # чтобы проверить только первые четыре аргумента
                assert mock_send_report.call_args.args[:4] == (
                    2024,
                    4,
                    mock_cog.bot,
                    mock_cog.data_manager,
                )
