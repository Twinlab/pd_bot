# cogs/update.py
import discord
from discord.ext import commands
import subprocess
import asyncio
import sys
import os

class Update(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.hybrid_command(
        name="update",
        description="Обновляет бота с GitHub и перезапускает его"
    )
    @commands.is_owner()  # Ограничение команды только для владельца бота
    async def update(self, ctx):
        """Обновляет бота с GitHub и перезапускает."""
        await ctx.defer()  # Отложенный ответ для slash-команд, чтобы дать время на выполнение
        
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
            
            # Перезапуск бота
            await asyncio.sleep(1)
            if os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl"):
                # Если используется systemd
                subprocess.Popen(["systemctl", "--user", "restart", "discord-bot.service"])
                # Альтернативный вариант, если требуются права sudo
                # subprocess.Popen(["sudo", "systemctl", "restart", "discord-bot.service"])
            else:
                # Альтернативный способ перезапуска через Python
                subprocess.Popen([sys.executable, "main.py"])
                await self.bot.close()
            
        except Exception as e:
            await message.edit(content=f"❌ Ошибка при обновлении: {str(e)}")

async def setup(bot):
    await bot.add_cog(Update(bot))