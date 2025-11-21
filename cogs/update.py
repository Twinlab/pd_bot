"""Ког для обновления бота с GitHub и его перезапуска через systemd.

Этот модуль предоставляет функциональность для:
- Получения последних изменений из Git-репозитория (git pull)
- Перезапуска бота через пользовательский сервис systemd
- Логирования процесса обновления и перезапуска

Требует настроенного пользовательского сервиса systemd для корректной работы.
"""

import asyncio
import logging
import subprocess

from discord.ext import commands

from config import get_settings
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot.cogs.update")


class UpdateCog(commands.Cog):
    """Ког для обновления бота с GitHub и его перезапуска.

    Предоставляет команду для владельца бота, позволяющую обновить код
    из Git-репозитория и перезапустить бота через systemd без необходимости
    ручного вмешательства. Это упрощает процесс развертывания обновлений
    и поддержки бота в актуальном состоянии.

    Attributes:
        bot: Экземпляр бота Discord
    """

    bot: commands.Bot

    def __init__(self, bot: commands.Bot):
        """Инициализирует ког UpdateCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot

    @commands.hybrid_command(
        name="update", description="Обновляет бота с GitHub и перезапускает его"
    )
    @commands.is_owner()
    @command_error_handler
    async def update(self, ctx: commands.Context) -> None:
        """(Владелец) Обновляет код бота (`git pull`) и перезапускает его.

        В среде Docker это выполняет `git pull` внутри контейнера (обновляя примонтированный код)
        и завершает процесс, чтобы Docker перезапустил его с новым кодом.
        """
        await ctx.defer(ephemeral=True)
        logger.info(f"Команда /update вызвана пользователем {ctx.author} (ID: {ctx.author.id})")
        message = await ctx.send("🔄 Проверка обновлений...", ephemeral=True)

        try:
            await message.edit(content="🔄 Получение последних изменений...")
            process = await asyncio.create_subprocess_exec(
                "git", "pull", stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            logger.info(f"Результат git pull: stdout={stdout_str!r}, stderr={stderr_str!r}")

            if process.returncode != 0:
                logger.error(f"Ошибка Git при обновлении (код {process.returncode}): {stderr_str}")
                await message.edit(content=f"❌ Ошибка Git: ```{stderr_str}```")
                return

            if "Already up to date" in stdout_str:
                logger.info("Бот уже обновлен до последней версии (git pull: Already up to date)")
                await message.edit(content="✅ Бот уже обновлен до последней версии!")
                return

            # Успешное обновление
            logger.info("Обновление получено, инициируем перезапуск...")

            settings = get_settings()
            max_len = settings.limits.update_output_max_length
            if len(stdout_str) > max_len:
                display_stdout = stdout_str[:max_len] + "\n... (truncated)"
            else:
                display_stdout = stdout_str

            try:
                await message.edit(
                    content=f"✅ Обновление получено!\n```{display_stdout}```\n🔄 Перезапуск бота..."
                )
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение об успехе: {e}")

            # Даем время на отправку сообщения (если получилось)
            await asyncio.sleep(1)
            logger.info("Бот завершает работу для перезапуска (Docker поднимет его снова)...")
            await self.bot.close()

        except FileNotFoundError:
            logger.error(
                "Ошибка: команда 'git' не найдена. Убедитесь, что Git установлен в контейнере."
            )
            await message.edit(content="❌ Ошибка: команда 'git' не найдена.")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обновлении: {e}", exc_info=True)
            await message.edit(content=f"❌ Непредвиденная ошибка при обновлении: {e}")

    async def cog_unload(self) -> None:
        """Вызывается при выгрузке кога.

        Выполняет необходимые действия для корректного завершения работы кога.
        """
        logger.info("Выгрузка кога UpdateCog")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Обрабатывает ошибки команд для этого кога.

        Args:
            ctx: Контекст команды
            error: Возникшая ошибка
        """
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ Эта команда доступна только владельцу бота.", ephemeral=True)
            cmd_name = ctx.command.name if ctx.command else "неизвестная команда"
            logger.warning(
                f"Пользователь {ctx.author} (ID: {ctx.author.id}) попытался использовать "
                f"команду только для владельца: {cmd_name}"
            )
        else:
            cmd_name = ctx.command.name if ctx.command else "неизвестная команда"
            logger.error(
                f"Ошибка в команде {cmd_name}: {error}",
                exc_info=error,
            )
            await ctx.send(f"❌ Произошла ошибка: {error}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Добавляет ког UpdateCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(UpdateCog(bot))
    logger.info("Ког UpdateCog успешно загружен.")
