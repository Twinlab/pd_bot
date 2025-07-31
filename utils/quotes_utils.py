"""Утилиты для работы с модулем quotes - отправка случайных изображений из папок.

Этот модуль предоставляет функции для:
- Сканирования папок с изображениями в assets/quotes/
- Получения случайных изображений из указанных папок
- Валидации существования папок и файлов
- Поддержки различных форматов изображений
"""

import logging
import random
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands

from config.settings import get_settings

logger = logging.getLogger("bot.utils.quotes_utils")


class QuotesError(Exception):
    """Базовое исключение для ошибок модуля quotes."""

    pass


class FolderNotFoundError(QuotesError):
    """Исключение для случаев, когда папка не найдена."""

    pass


class NoImagesFoundError(QuotesError):
    """Исключение для случаев, когда в папке нет изображений."""

    pass


def get_quotes_path() -> Path:
    """Получает путь к папке с изображениями quotes.

    Returns:
        Path: Путь к папке assets/quotes/
    """
    settings = get_settings()
    return Path(settings.fun.quotes.assets_path)


def get_supported_extensions() -> list[str]:
    """Получает список поддерживаемых расширений файлов.

    Returns:
        list[str]: Список расширений (например, ['.jpg', '.png'])
    """
    settings = get_settings()
    return settings.fun.quotes.supported_extensions


def scan_quotes_folders() -> list[str]:
    """Сканирует папку assets/quotes/ и возвращает список доступных папок.

    Returns:
        list[str]: Список имен папок, содержащих изображения

    Examples:
        >>> scan_quotes_folders()
        ['odji', 'fineser', 'qustic', 'ifuwanna']
    """
    quotes_path = get_quotes_path()
    supported_extensions = get_supported_extensions()

    if not quotes_path.exists():
        logger.warning(f"Папка quotes не найдена: {quotes_path}")
        return []

    folders = []

    try:
        for item in quotes_path.iterdir():
            if item.is_dir():
                # Проверяем, есть ли в папке изображения
                has_images = any(
                    file.suffix.lower() in supported_extensions
                    for file in item.iterdir()
                    if file.is_file()
                )

                if has_images:
                    folders.append(item.name)
                    logger.debug(f"Найдена папка с изображениями: {item.name}")
                else:
                    logger.debug(f"Папка {item.name} не содержит изображений")

    except Exception as e:
        logger.error(f"Ошибка при сканировании папок quotes: {e}", exc_info=True)
        return []

    folders.sort()  # Сортируем для консистентности
    logger.info(f"Найдено папок с изображениями: {len(folders)}")
    return folders


def validate_folder_exists(folder_name: str) -> bool:
    """Проверяет, существует ли папка и содержит ли она изображения.

    Args:
        folder_name: Имя папки для проверки

    Returns:
        bool: True, если папка существует и содержит изображения
    """
    if not folder_name:
        return False

    quotes_path = get_quotes_path()
    folder_path = quotes_path / folder_name
    supported_extensions = get_supported_extensions()

    if not folder_path.exists() or not folder_path.is_dir():
        return False

    # Проверяем наличие изображений в папке
    try:
        has_images = any(
            file.suffix.lower() in supported_extensions
            for file in folder_path.iterdir()
            if file.is_file()
        )
        return has_images
    except Exception as e:
        logger.error(f"Ошибка при проверке папки {folder_name}: {e}")
        return False


def get_images_from_folder(folder_name: str) -> list[Path]:
    """Получает список всех изображений из указанной папки.

    Args:
        folder_name: Имя папки

    Returns:
        list[Path]: Список путей к файлам изображений

    Raises:
        FolderNotFoundError: Если папка не найдена
        NoImagesFoundError: Если в папке нет изображений
    """
    if not validate_folder_exists(folder_name):
        raise FolderNotFoundError(f"Папка '{folder_name}' не найдена или не содержит изображений")

    quotes_path = get_quotes_path()
    folder_path = quotes_path / folder_name
    supported_extensions = get_supported_extensions()

    images = []

    try:
        for file in folder_path.iterdir():
            if file.is_file() and file.suffix.lower() in supported_extensions:
                images.append(file)
    except Exception as e:
        logger.error(f"Ошибка при получении изображений из папки {folder_name}: {e}")
        raise NoImagesFoundError(f"Не удалось получить изображения из папки '{folder_name}'")

    if not images:
        raise NoImagesFoundError(f"В папке '{folder_name}' не найдено изображений")

    return images


def get_random_image_from_folder(folder_name: str) -> Path:
    """Получает случайное изображение из указанной папки.

    Args:
        folder_name: Имя папки

    Returns:
        Path: Путь к случайному изображению

    Raises:
        FolderNotFoundError: Если папка не найдена
        NoImagesFoundError: Если в папке нет изображений
    """
    images = get_images_from_folder(folder_name)
    selected_image = random.choice(images)

    logger.info(f"Выбрано случайное изображение: {selected_image.name} из папки {folder_name}")
    return selected_image


async def send_random_quote_image(
    ctx: commands.Context, folder_name: str, ephemeral: bool = False, embed: bool = True
) -> None:
    """Отправляет случайное изображение из указанной папки.

    Args:
        ctx: Контекст команды Discord
        folder_name: Имя папки с изображениями
        ephemeral: Отправить сообщение только автору команды
        embed: Отправить с embed или только изображение

    Raises:
        FolderNotFoundError: Если папка не найдена
        NoImagesFoundError: Если в папке нет изображений
    """
    try:
        # Получаем случайное изображение
        image_path = get_random_image_from_folder(folder_name)

        # Отправляем изображение
        with open(image_path, "rb") as f:
            file = discord.File(f, filename=image_path.name)

            if embed:
                # Создаем эмбед
                settings = get_settings()
                embed_obj = discord.Embed(
                    title=f"📸 Случайное изображение из {folder_name}",
                    color=discord.Color(int(settings.colors.default[1:], 16)),
                )
                # Добавляем информацию о файле
                embed_obj.set_footer(text=f"Файл: {image_path.name}")
                embed_obj.set_image(url=f"attachment://{image_path.name}")

                await ctx.send(embed=embed_obj, file=file, ephemeral=ephemeral)
            else:
                # Отправляем только изображение
                await ctx.send(file=file, ephemeral=ephemeral)

        logger.info(f"Отправлено изображение {image_path.name} из папки {folder_name}")

    except (FolderNotFoundError, NoImagesFoundError) as e:
        error_message = str(e)
        logger.warning(f"Ошибка при отправке изображения: {error_message}")

        # Создаем эмбед с ошибкой
        settings = get_settings()
        error_embed = discord.Embed(
            title="❌ Ошибка",
            description=error_message,
            color=discord.Color(int(settings.colors.error[1:], 16)),
        )

        await ctx.send(embed=error_embed, ephemeral=True)

    except Exception as e:
        logger.error(f"Неожиданная ошибка при отправке изображения: {e}", exc_info=True)

        # Создаем эмбед с общей ошибкой
        settings = get_settings()
        error_embed = discord.Embed(
            title="❌ Произошла ошибка",
            description="Не удалось отправить изображение. Попробуйте позже.",
            color=discord.Color(int(settings.colors.error[1:], 16)),
        )

        await ctx.send(embed=error_embed, ephemeral=True)


def get_folder_stats(folder_name: str) -> dict[str, int]:
    """Получает статистику по папке с изображениями.

    Args:
        folder_name: Имя папки

    Returns:
        dict[str, int]: Словарь со статистикой:
            - total_images: общее количество изображений
    """
    if not validate_folder_exists(folder_name):
        return {"total_images": 0}

    try:
        images = get_images_from_folder(folder_name)
        return {"total_images": len(images)}

    except Exception as e:
        logger.error(f"Ошибка при получении статистики папки {folder_name}: {e}")
        return {"total_images": 0}


def get_all_folders_stats() -> dict[str, dict[str, int]]:
    """Получает статистику по всем папкам с изображениями.

    Returns:
        dict[str, dict[str, int]]: Словарь со статистикой по каждой папке
    """
    folders = scan_quotes_folders()
    all_stats = {}

    for folder in folders:
        all_stats[folder] = get_folder_stats(folder)

    return all_stats


# UI компоненты для выбора папок


class QuotesFolderSelect(discord.ui.Select):
    """Выпадающий список для выбора папки с изображениями quotes."""

    def __init__(self, original_interaction: discord.Interaction):
        """Инициализирует выпадающий список папок.

        Args:
            original_interaction: Исходное взаимодействие, инициировавшее команду.
        """
        self.original_interaction = original_interaction

        # Получаем список доступных папок
        folders = scan_quotes_folders()
        settings = get_settings()
        max_folders = settings.fun.quotes.max_folders_in_select

        options: list[discord.SelectOption] = []

        if not folders:
            options.append(
                discord.SelectOption(
                    label="Папки не найдены",
                    value="none",
                    description="Нет доступных папок с изображениями",
                    emoji="❌",
                )
            )
        else:
            # Ограничиваем количество папок согласно Discord лимитам
            folders_to_show = folders[:max_folders]

            for folder in folders_to_show:
                stats = get_folder_stats(folder)
                total_images = stats.get("total_images", 0)

                # Создаем описание с количеством изображений
                description = f"{total_images} изображений"
                if len(description) > 100:
                    description = description[:97] + "..."

                # Добавляем эмодзи в зависимости от количества изображений
                emoji = "📁"
                if total_images > 10:
                    emoji = "📂"
                elif total_images > 5:
                    emoji = "🗂️"

                options.append(
                    discord.SelectOption(
                        label=folder, value=folder, description=description, emoji=emoji
                    )
                )

            # Если папок больше лимита, добавляем информацию об этом
            if len(folders) > max_folders:
                remaining = len(folders) - max_folders
                options.append(
                    discord.SelectOption(
                        label=f"+ еще {remaining} папок",
                        value="more",
                        description="Используйте команду с параметром для доступа ко всем папкам",
                        emoji="➕",
                    )
                )

        super().__init__(
            placeholder="Выберите папку с изображениями...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Обрабатывает выбор пользователя из выпадающего списка.

        Args:
            interaction: Взаимодействие от выбора элемента.
        """
        selected_folder = self.values[0]

        # Удаляем исходное сообщение с выбором папок
        if interaction.message:
            try:
                await interaction.message.delete()
                logger.debug(f"Сообщение с выбором папок (ID: {interaction.message.id}) удалено.")
            except discord.NotFound:
                logger.warning("Сообщение с выбором папок не найдено для удаления.")
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения с выбором папок: {e}")

        # Обрабатываем специальные случаи
        if selected_folder == "none":
            await interaction.response.send_message(
                "❌ Нет доступных папок с изображениями.", ephemeral=True
            )
            return

        if selected_folder == "more":
            available_folders = scan_quotes_folders()
            folders_text = ", ".join(available_folders)

            settings = get_settings()
            embed = discord.Embed(
                title="📁 Все доступные папки",
                description=(
                    f"Используйте команду `/quote <folder_name>` с одним из этих названий:"
                    f"\n\n`{folders_text}`"
                ),
                color=discord.Color(int(settings.colors.info[1:], 16)),
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Отправляем случайное изображение из выбранной папки
        await interaction.response.defer()

        try:
            # Создаем контекст для функции send_random_quote_image
            # Используем interaction как псевдо-контекст
            # Создаем псевдо-контекст для совместимости с send_random_quote_image
            class PseudoContext:
                def __init__(self, interaction: discord.Interaction) -> None:
                    self.interaction = interaction

                async def send(
                    self,
                    embed: Optional[discord.Embed] = None,
                    file: Optional[discord.File] = None,
                    ephemeral: bool = False,
                ) -> discord.WebhookMessage:
                    return await self.interaction.followup.send(
                        embed=embed, file=file, ephemeral=ephemeral
                    )

            # Используем прямой вызов вместо псевдо-контекста

            # Получаем случайное изображение
            image_path = get_random_image_from_folder(selected_folder)

            # Создаем эмбед
            settings = get_settings()
            embed = discord.Embed(
                title=f"📸 Случайное изображение из {selected_folder}",
                color=discord.Color(int(settings.colors.default[1:], 16)),
            )
            embed.set_footer(text=f"Файл: {image_path.name}")

            # Отправляем изображение
            with open(image_path, "rb") as f:
                file = discord.File(f, filename=image_path.name)
                embed.set_image(url=f"attachment://{image_path.name}")

                await interaction.followup.send(embed=embed, file=file)

            logger.info(
                f"Отправлено изображение {image_path.name} из папки {selected_folder} через UI"
            )

        except (FolderNotFoundError, NoImagesFoundError) as e:
            error_message = str(e)
            logger.warning(f"Ошибка при отправке изображения через UI: {error_message}")

            settings = get_settings()
            error_embed = discord.Embed(
                title="❌ Ошибка",
                description=error_message,
                color=discord.Color(int(settings.colors.error[1:], 16)),
            )

            await interaction.followup.send(embed=error_embed, ephemeral=True)

        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при отправке изображения через UI: {e}", exc_info=True
            )

            settings = get_settings()
            error_embed = discord.Embed(
                title="❌ Произошла ошибка",
                description="Не удалось отправить изображение. Попробуйте позже.",
                color=discord.Color(int(settings.colors.error[1:], 16)),
            )

            await interaction.followup.send(embed=error_embed, ephemeral=True)


class QuotesSelectView(discord.ui.View):
    """View с выпадающим списком для выбора папки с изображениями quotes."""

    def __init__(self, original_interaction: discord.Interaction, timeout: Optional[float] = None):
        """Инициализирует View для выбора папки.

        Args:
            original_interaction: Исходное взаимодействие, инициировавшее команду.
            timeout: Время в секундах, после которого View станет неактивной.
        """
        if timeout is None:
            settings = get_settings()
            timeout = float(settings.fun.quotes.view_timeout)

        super().__init__(timeout=timeout)
        self.original_interaction = original_interaction
        self.add_item(QuotesFolderSelect(original_interaction))

    async def on_timeout(self) -> None:
        """Вызывается при истечении времени ожидания View."""
        logger.debug(f"QuotesSelectView для взаимодействия {self.original_interaction.id} истек.")

        try:
            await self.original_interaction.edit_original_response(
                content=(
                    "⏱️ Время выбора папки истекло. " "Используйте команду снова, если необходимо."
                ),
                view=None,
                embed=None,
            )
            logger.debug("Сообщение выбора папки отредактировано по таймауту.")
        except discord.NotFound:
            logger.warning("Исходное сообщение для QuotesSelectView не найдено при таймауте.")
        except discord.HTTPException as e:
            logger.error(
                f"Ошибка HTTP при редактировании сообщения QuotesSelectView по таймауту: {e}"
            )
        except Exception as e:
            logger.error(
                f"Непредвиденная ошибка при обработке таймаута QuotesSelectView: {e}", exc_info=True
            )

        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Проверяет, что взаимодействие с View исходит от инициатора команды.

        Args:
            interaction: Взаимодействие с View.

        Returns:
            bool: True, если пользователь может взаимодействовать с View.
        """
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message(
                "Только пользователь, запустивший команду, может выбрать папку.", ephemeral=True
            )
            return False
        return True
