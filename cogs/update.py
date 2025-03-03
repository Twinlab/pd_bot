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
        
    @commands.command()
    @commands.is_owner() # Ограничиваем команду только владельцем бота
    async def update(self, ctx):
        """Обновляет бота с GitHub и перезапускает."""
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
            if os.path.exists("/bin/systemctl"):
                # Если используется systemd
                subprocess.Popen(["systemctl", "--user", "restart", "discord-bot.service"])
            else:
                # Альтернативный способ перезапуска
                subprocess.Popen([sys.executable, "main.py"])
                await self.bot.close()
            
        except Exception as e:
            await message.edit(content=f"❌ Ошибка при обновлении: {str(e)}")

async def setup(bot):
    await bot.add_cog(Update(bot))