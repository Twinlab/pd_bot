"""Ког для обновления бота с GitHub и его перезапуска через systemd."""
import discord
from discord.ext import commands
import subprocess
import asyncio
import logging

from utils.error_handler import command_error_handler

logger = logging.getLogger("bot.update")

class UpdateCog(commands.Cog):
    """Ког для обновления бота с GitHub и его перезапуска."""
    
    def __init__(self, bot: commands.Bot):
        """
        Инициализирует ког UpdateCog.

        Args:
            bot: Экземпляр бота discord.ext.commands.Bot.
        """
        self.bot = bot
        
    @commands.hybrid_command(
        name="update",
        description="Обновляет бота с GitHub и перезапускает его"
    )
    @commands.is_owner()
    @command_error_handler
    async def update(self, ctx: commands.Context):
        """
        (Только для владельца) Обновляет код бота из Git-репозитория (`git pull`)
        и инициирует перезапуск через пользовательский сервис systemd.

        ТРЕБОВАНИЯ:
        - Бот должен быть настроен как пользовательский сервис systemd (например, `discord-bot.service`).
        - Пользователь, от имени которого запущен бот, должен иметь права на перезапуск этого сервиса (`systemctl --user restart discord-bot.service`).
        - Имя сервиса `discord-bot.service` жестко задано в коде. Измените его при необходимости.
        """
        await ctx.defer(ephemeral=True) # Делаем ответ эфемерным
        logger.info(f"Команда /update вызвана пользователем {ctx.author} (ID: {ctx.author.id})")
        message = await ctx.send("🔄 Проверка обновлений...", ephemeral=True)

        # Получаем обновления
        try:
            await message.edit(content="🔄 Получение последних изменений...")
            # Используем asyncio.create_subprocess_exec для асинхронного выполнения
            process = await asyncio.create_subprocess_exec(
                "git", "pull",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            logger.info(f"Результат git pull: stdout={stdout_str!r}, stderr={stderr_str!r}")

            if process.returncode != 0:
                 logger.error(f"Ошибка Git при обновлении (код {process.returncode}): {stderr_str}")
                 return await message.edit(content=f"❌ Ошибка Git: ```{stderr_str}```")

            if "Already up to date" in stdout_str:
                logger.info("Бот уже обновлен до последней версии (git pull: Already up to date)")
                return await message.edit(content="✅ Бот уже обновлен до последней версии!")

            # Успешное обновление
            logger.info("Обновление получено, инициируем перезапуск бота через systemctl --user...")

            # Ограничиваем длину вывода для Discord (максимум 1900 символов)
            max_len = 1900
            if len(stdout_str) > max_len:
                display_stdout = stdout_str[:max_len] + "\n... (truncated)"
            else:
                display_stdout = stdout_str

            try:
                await message.edit(content=f"✅ Обновление получено!\n```{display_stdout}```\n🔄 Перезапуск бота...")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения об обновлении: {e}", exc_info=True)
                # Не блокируем рестарт

            # Команда перезапуска пользовательского сервиса
            restart_command = ["systemctl", "--user", "restart", "discord-bot.service"]
            try:
                # Запускаем без ожидания завершения, т.к. бот должен закрыться
                subprocess.Popen(restart_command)
                logger.info(f"Команда перезапуска '{' '.join(restart_command)}' отправлена.")
            except Exception as e:
                logger.error(f"Ошибка при попытке перезапуска через systemctl --user: {e}", exc_info=True)
                # Не закрываем бота, чтобы владелец видел ошибку
                try:
                    await message.edit(content=f"✅ Обновление получено, но не удалось инициировать перезапуск: {e}")
                except Exception:
                    pass
                return

            # Даем немного времени на запуск команды перед закрытием
            await asyncio.sleep(1)
            logger.info("Бот завершает работу для перезапуска...")
            await self.bot.close()

        except FileNotFoundError:
            logger.error("Ошибка: команда 'git' не найдена. Убедитесь, что Git установлен и доступен в PATH.")
            await message.edit(content="❌ Ошибка: команда 'git' не найдена.")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обновлении: {e}", exc_info=True)
            await message.edit(content=f"❌ Непредвиденная ошибка при обновлении: {e}")

async def setup(bot: commands.Bot):
    """
    Добавляет ког UpdateCog к боту.

    Args:
        bot: Экземпляр бота discord.ext.commands.Bot.
    """
    await bot.add_cog(UpdateCog(bot))
    logger.info("Ког UpdateCog успешно загружен.")
