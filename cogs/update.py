import discord
from discord.ext import commands
import subprocess
import asyncio
import os

import logging
# Импортируем обработчик ошибок
from utils.error_handler import command_error_handler

logger = logging.getLogger("bot")

class Update(commands.Cog):
    def __init__(self, bot):
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
        и инициирует перезапуск через системный сервис systemd.

        ВНИМАНИЕ:
        - Требует настройки прав sudo без пароля для пользователя бота на команду `systemctl restart discord-bot`.
        - Жестко использует имя сервиса systemd `discord-bot`. Измените его при необходимости.
        - Создает временный исполняемый файл `restart.sh` в корневой директории проекта.
        - Задержка перед перезапуском может быть недостаточной (`sleep 1`).
        """
        await ctx.defer()
        logger.info("Запущена команда обновления бота через /update")
        message = await ctx.send("🔄 Проверка обновлений...")

        # Получаем обновления
        await message.edit(content="🔄 Получение последних изменений...")
        result = subprocess.run(["git", "pull"], capture_output=True, text=True)
        logger.info(f"Результат git pull: stdout={result.stdout!r}, stderr={result.stderr!r}")

        # Проверяем результат
        if "Already up to date" in result.stdout:
            logger.info("Бот уже обновлен до последней версии (git pull: Already up to date)")
            return await message.edit(content="✅ Бот уже обновлен до последней версии!")

        if "fatal" in result.stderr or "error" in result.stderr:
            logger.error(f"Ошибка Git при обновлении: {result.stderr}")
            return await message.edit(content=f"❌ Ошибка Git: ```{result.stderr}```")

        # Успешное обновление
        logger.info("Обновление получено, инициируем перезапуск бота через restart.sh")
        await message.edit(content=f"✅ Обновление получено!\n```{result.stdout}```\n🔄 Перезапуск бота...")

        # Создаем очень простой скрипт для перезапуска
        with open("restart.sh", "w") as f:
            f.write("#!/bin/bash\n")
            f.write("sleep 1\n")  # Ждем 1 секунду
            f.write("sudo systemctl restart discord-bot\n")  # Перезапускаем сервис с sudo

        # Делаем скрипт исполняемым
        os.chmod("restart.sh", 0o755)

        # Запускаем скрипт в фоновом режиме
        subprocess.Popen(["bash", "restart.sh"], start_new_session=True)
        logger.info("Скрипт restart.sh запущен, бот завершает работу")

        # Закрываем бота
        await asyncio.sleep(0.5)
        await self.bot.close()

async def setup(bot):
    await bot.add_cog(Update(bot))
