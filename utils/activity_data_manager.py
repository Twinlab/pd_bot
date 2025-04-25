import json
import os
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any

logger = logging.getLogger("bot.data_manager")

class ActivityDataManager:
    """
    Управляет загрузкой, сохранением, архивированием и миграцией
    данных об игровой активности пользователей.
    """
    def __init__(self, data_dir: str = "data"):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, data_dir)
        self.archive_dir = os.path.join(self.data_dir, "activity_archives")

        # Создаем директории, если их нет
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        self.data_file = os.path.join(self.data_dir, "user_activities.json")  # Дневные данные
        self.monthly_file = os.path.join(self.data_dir, "monthly_activities.json")  # Месячные данные

        self.user_activities: Dict[int, Dict[str, int]] = {}  # Дневная статистика {user_id: {game: seconds}}
        self.monthly_activities: Dict[int, Dict[str, int]] = {}  # Месячная статистика {user_id: {game: seconds}}

        logger.info(f"Инициализация ActivityDataManager в директории: {self.data_dir}")
        self.check_data_migration()
        self.load_data()
        self.load_monthly_data()

    def _filter_zero_values(self, data: Dict[int, Dict[str, int]]) -> Dict[int, Dict[str, int]]:
        """Удаляет записи с нулевым временем из данных активности."""
        filtered_data = {}
        for user_id, games in data.items():
            filtered_games = {game: time for game, time in games.items() if time > 0}
            if filtered_games:
                filtered_data[user_id] = filtered_games
        return filtered_data

    def _safe_save_json(self, file_path: str, data: Dict[Any, Any]):
        """Безопасно сохраняет данные в JSON файл через временный файл."""
        try:
            directory = os.path.dirname(file_path)
            os.makedirs(directory, exist_ok=True)

            temp_file = f"{file_path}.tmp"

            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Проверяем, что файл не пустой перед переименованием
            if os.path.getsize(temp_file) > 0:
                os.replace(temp_file, file_path)
                logger.debug(f"Данные успешно сохранены в {file_path}")
            else:
                logger.warning(f"Временный файл {temp_file} пуст, не переименовываем")
                # Если основной файл существует и пуст, удаляем его тоже
                if os.path.exists(file_path) and os.path.getsize(file_path) == 0:
                     os.remove(file_path)
                # Удаляем временный файл
                if os.path.exists(temp_file):
                    os.remove(temp_file)

        except Exception as e:
            logger.error(f"Ошибка при сохранении данных в {file_path}: {e}", exc_info=True)
            # Попытка удалить временный файл, если он остался
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass # Игнорируем ошибку удаления

    def _load_json_data(self, file_path: str) -> Dict[int, Dict[str, int]]:
        """Загружает данные активности из JSON файла."""
        data_loaded: Dict[int, Dict[str, int]] = {}
        try:
            if os.path.exists(file_path):
                if os.path.getsize(file_path) > 0:
                    logger.info(f"Загрузка данных из {file_path}")
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Преобразуем строковые ключи обратно в числа и фильтруем нулевые значения
                    for user_id_str, activities in data.items():
                        try:
                            user_id = int(user_id_str)
                            filtered_activities = {game: time for game, time in activities.items() if time > 0}
                            if filtered_activities:
                                data_loaded[user_id] = filtered_activities
                        except ValueError:
                             logger.warning(f"Некорректный user_id '{user_id_str}' в файле {file_path}, пропускаем.")

                    logger.info(f"Загружено {len(data_loaded)} записей из {file_path}")
                else:
                    logger.info(f"Файл {file_path} пуст, используем пустой словарь")
            else:
                logger.info(f"Файл {file_path} не найден, используем пустой словарь")
                # Создаем пустой файл, если он не существует
                self._safe_save_json(file_path, {})

        except json.JSONDecodeError:
             logger.error(f"Ошибка декодирования JSON в {file_path}. Файл может быть поврежден.", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных из {file_path}: {e}", exc_info=True)

        return data_loaded

    def check_data_migration(self):
        """Проверяет, нужна ли миграция данных из старого формата в новый."""
        try:
            # Если уже есть monthly_file, миграция не нужна
            if os.path.exists(self.monthly_file):
                return

            # Если есть старый файл с данными (user_activities.json), нужно мигрировать
            if os.path.exists(self.data_file) and os.path.getsize(self.data_file) > 0:
                logger.info("Обнаружен старый формат данных (только user_activities.json), выполняем миграцию...")

                # Загружаем старые данные
                old_data = self._load_json_data(self.data_file)

                # Сохраняем их как месячные данные
                self._safe_save_json(self.monthly_file, old_data)

                # Очищаем дневные данные (сохраняем пустой словарь)
                self._safe_save_json(self.data_file, {})

                logger.info("Миграция данных завершена: старые данные перенесены в monthly_activities.json, user_activities.json сброшен")

        except Exception as e:
            logger.error(f"Ошибка при миграции данных активности: {e}", exc_info=True)

    def load_data(self):
        """Загружает дневные данные об активности."""
        self.user_activities = self._load_json_data(self.data_file)

    def load_monthly_data(self):
        """Загружает месячные данные об активности."""
        self.monthly_activities = self._load_json_data(self.monthly_file)

    def save_data(self):
        """Сохраняет дневные данные об активности в файл."""
        filtered_data = self._filter_zero_values(self.user_activities)
        self._safe_save_json(self.data_file, filtered_data)

    def save_monthly_data(self):
        """Сохраняет месячные данные об активности в файл."""
        filtered_data = self._filter_zero_values(self.monthly_activities)
        self._safe_save_json(self.monthly_file, filtered_data)

    def reset_daily_data(self):
        """Сбрасывает дневные данные об активности."""
        self.user_activities = {}
        self.save_data()
        logger.info("Дневные данные сброшены")

    def archive_monthly_data(self, year: int, month: int) -> bool:
        """
        Архивирует данные за указанный месяц и год и сбрасывает текущие месячные данные.
        Возвращает True в случае успеха, False в случае ошибки или отсутствия данных.
        """
        try:
            # Сохраняем текущие месячные данные перед архивацией
            self.save_monthly_data()

            # Формируем имя файла архива
            archive_filename = f"activity_{year}_{month:02d}.json"
            archive_path = os.path.join(self.archive_dir, archive_filename)

            # Проверяем, есть ли что архивировать
            if not os.path.exists(self.monthly_file) or os.path.getsize(self.monthly_file) == 0:
                logger.warning(f"Не удалось архивировать данные за {month}/{year} - файл месячных данных пуст или не существует.")
                # Сбрасываем месячные данные на всякий случай
                self.monthly_activities = {}
                self.save_monthly_data()
                return False

            # Фильтруем данные перед архивацией (на всякий случай)
            filtered_data = self._filter_zero_values(self.monthly_activities)
            if not filtered_data:
                 logger.warning(f"Не удалось архивировать данные за {month}/{year} - нет ненулевых данных.")
                 self.monthly_activities = {}
                 self.save_monthly_data()
                 return False

            # Сохраняем в архивный файл (используем безопасное сохранение)
            self._safe_save_json(archive_path, filtered_data)
            logger.info(f"Данные за {month}/{year} успешно архивированы: {archive_path}")

            # Сбрасываем месячные данные
            self.monthly_activities = {}
            self.save_monthly_data()
            logger.info("Месячные данные сброшены для нового месяца")
            return True

        except Exception as e:
            logger.error(f"Ошибка при архивировании месячных данных за {month}/{year}: {e}", exc_info=True)
            return False

    def load_archived_data(self, year: int, month: int) -> Dict[int, Dict[str, int]]:
        """Загружает архивные данные за указанный месяц и год."""
        archive_filename = f"activity_{year}_{month:02d}.json"
        archive_path = os.path.join(self.archive_dir, archive_filename)
        logger.info(f"Загрузка архивных данных: {archive_path}")
        return self._load_json_data(archive_path)

    def get_all_user_data(self, user_id: int) -> Dict[str, int]:
        """
        Собирает все данные об активности пользователя из текущего месяца и всех архивов.
        """
        all_user_games: Dict[str, int] = defaultdict(int)

        # 1. Добавляем данные из текущего месяца
        current_month_data = self._filter_zero_values(self.monthly_activities) # Получаем актуальные отфильтрованные данные
        if user_id in current_month_data:
            for game_name, time_spent in current_month_data[user_id].items():
                all_user_games[game_name] += time_spent

        # 2. Сканируем архивную директорию и добавляем данные пользователя из всех архивов
        try:
            for filename in os.listdir(self.archive_dir):
                if filename.endswith('.json') and filename.startswith('activity_'):
                    try:
                        # Извлекаем год и месяц из имени файла
                        parts = filename[:-5].split('_')
                        if len(parts) >= 3:
                            year = int(parts[1])
                            month = int(parts[2])

                            # Загружаем архивные данные
                            archived_data = self.load_archived_data(year, month)

                            # Добавляем данные пользователя, если они есть
                            if user_id in archived_data:
                                for game_name, time_spent in archived_data[user_id].items():
                                    all_user_games[game_name] += time_spent
                    except Exception as e:
                        logger.error(f"Ошибка при обработке архивного файла {filename} для пользователя {user_id}: {e}", exc_info=True)
        except FileNotFoundError:
             logger.warning(f"Директория архивов {self.archive_dir} не найдена.")
        except Exception as e:
             logger.error(f"Ошибка при чтении директории архивов {self.archive_dir}: {e}", exc_info=True)


        return dict(all_user_games) # Возвращаем как обычный dict

    def update_activity(self, user_id: int, game_name: str, elapsed_seconds: int):
        """Обновляет дневную и месячную статистику для пользователя и игры."""
        if elapsed_seconds <= 0:
            return

        # Обновляем ДНЕВНУЮ статистику
        if user_id not in self.user_activities:
            self.user_activities[user_id] = {}
        self.user_activities[user_id][game_name] = self.user_activities[user_id].get(game_name, 0) + elapsed_seconds

        # Обновляем МЕСЯЧНУЮ статистику
        if user_id not in self.monthly_activities:
            self.monthly_activities[user_id] = {}
        self.monthly_activities[user_id][game_name] = self.monthly_activities[user_id].get(game_name, 0) + elapsed_seconds

        logger.debug(f"Обновлена активность для {user_id} - {game_name}: +{elapsed_seconds} сек.")
