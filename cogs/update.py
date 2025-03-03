# cogs/update.py
import discord
from discord.ext import commands
import subprocess
import asyncio
import os

class Update(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.hybrid_command(
        name="update",
        description="Обновляет бота с GitHub и перезапускает его"
    )
    @commands.is_owner()
    async def update(self, ctx):
        """Обновляет бота с GitHub и перезапускает."""
        await ctx.defer()
        
        message = await ctx.send("🔄 Проверка обновлений...")
        
        try:
            # Получаем обновления
            await message.edit(content="🔄 Получение последних изменений...")
            result = subprocess.run(["git", "pull"], capture_output=True, text=True)
            
            # Проверяем результат
            if "Already up to date" in result.stdout:
                return await message.edit(content="✅ Бот уже обновлен до последней версии!")
            
            if "fatal" in result.stderr or "error" in result.stderr:
                return await message.edit(content=f"❌ Ошибка Git: ```{result.stderr}```")
            
            # Успешное обновление
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
            
            # Закрываем бота
            await asyncio.sleep(0.5)
            await self.bot.close()
            
        except Exception as e:
            await message.edit(content=f"❌ Ошибка при обновлении: {str(e)}")

async def setup(bot):
    await bot.add_cog(Update(bot))