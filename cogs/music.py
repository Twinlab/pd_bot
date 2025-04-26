import discord
from discord.ext import commands
import logging
from typing import Optional, Dict
import asyncio # Нужен для sleep в on_voice_state_update

# Импортируем обработчик ошибок и UI элементы
from utils.error_handler import command_error_handler
from discord import ui, ButtonStyle, Interaction

logger = logging.getLogger("bot")

# Импортируем ТОЛЬКО класс плеера
from utils.music_utils import MusicPlayer, YDL_OPTS # YDL_OPTS нужен для search

# --- Интерактивное View для управления плеером ---
class MusicView(ui.View):
    def __init__(self, player: MusicPlayer, timeout=None):
        super().__init__(timeout=timeout)
        self.player = player
        self.update_buttons() # Устанавливаем начальное состояние кнопок

    def update_buttons(self):
        """Обновляет состояние кнопки паузы/возобновления."""
        pause_resume_button = discord.utils.get(self.children, custom_id="pause_resume")
        if pause_resume_button:
            if self.player.is_paused:
                pause_resume_button.label = "▶️ Resume"
                pause_resume_button.style = ButtonStyle.green
            else:
                pause_resume_button.label = "⏸️ Pause"
                pause_resume_button.style = ButtonStyle.secondary
        # Логика обновления кнопок loop и shuffle удалена

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Проверяет, находится ли пользователь в том же канале, что и бот."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале.", ephemeral=True)
            return False
        if self.player.voice_client and interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале.", ephemeral=True)
            return False
        return True

    @ui.button(label="⏸️ Pause", style=ButtonStyle.secondary, custom_id="pause_resume")
    async def pause_resume(self, interaction: Interaction, button: ui.Button):
        if self.player.is_paused:
            await self.player.resume(interaction)
        else:
            await self.player.pause(interaction)
        self.update_buttons()
        # Пытаемся отредактировать сообщение, игнорируем ошибку если не получилось (например, сообщение удалено)
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException as e:
             logger.warning(f"Не удалось обновить кнопки MusicView после pause/resume: {e}")


    @ui.button(label="⏭️ Skip", style=ButtonStyle.secondary, custom_id="skip")
    async def skip(self, interaction: Interaction, button: ui.Button):
        await self.player.skip(interaction)
        # View обновится автоматически при смене трека или остановке

    @ui.button(label="⏹️ Stop", style=ButtonStyle.danger, custom_id="stop")
    async def stop(self, interaction: Interaction, button: ui.Button):
        await self.player.stop(interaction)
        # View будет удален в методе stop плеера

    # Кнопки loop и shuffle удалены

# --- Основной Ког ---
class Music(commands.Cog):
    """Ког, предоставляющий команды для управления музыкальным плеером."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: Dict[int, MusicPlayer] = {}
        logger.info(f"Ког {self.__class__.__name__} загружен")

    async def get_player(self, ctx: commands.Context) -> Optional[MusicPlayer]:
        """Получает или создает экземпляр плеера для гильдии и подключается к каналу."""
        guild_id = ctx.guild.id
        player = self.players.get(guild_id)
        if not player:
            logger.info(f"Создание нового MusicPlayer для гильдии {guild_id}")
            player = MusicPlayer(self.bot, guild_id)
            self.players[guild_id] = player
        if not await player._ensure_voice(ctx): return None
        player.text_channel = ctx.channel
        return player

    # --- Команды ---
    @commands.hybrid_command(description='Воспроизвести музыку или добавить в очередь')
    @command_error_handler
    async def play(self, ctx: commands.Context, *, query: str):
        """Воспроизводит музыку по URL/поиску или добавляет в очередь."""
        player = await self.get_player(ctx)
        if not player: return
        if query.startswith(('http://', 'https://')): await player.add_track(ctx, query)
        else: await player.search_tracks(ctx, query)

    @commands.hybrid_command(description='Пропустить текущий трек')
    @command_error_handler
    async def skip(self, ctx: commands.Context):
        """Голосует за пропуск трека или пропускает его (DJ/запросивший)."""
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client: await ctx.send("Бот не воспроизводит музыку.", ephemeral=True); return
        await player.skip(ctx)

    @commands.hybrid_command(description='Остановить воспроизведение и покинуть канал')
    @command_error_handler
    async def stop(self, ctx: commands.Context):
        """Останавливает музыку, очищает очередь и отключает бота."""
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client: await ctx.send("Бот не в голосовом канале.", ephemeral=True); return
        await player.stop(ctx)
        if ctx.guild.id in self.players: del self.players[ctx.guild.id]; logger.info(f"Экземпляр MusicPlayer удален для гильдии {ctx.guild.id}")

    @commands.hybrid_command(description='Приостановить воспроизведение')
    @command_error_handler
    async def pause(self, ctx: commands.Context):
        """Ставит текущий трек на паузу."""
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client: await ctx.send("Бот не воспроизводит музыку.", ephemeral=True); return
        await player.pause(ctx)

    @commands.hybrid_command(description='Возобновить воспроизведение')
    @command_error_handler
    async def resume(self, ctx: commands.Context):
        """Возобновляет воспроизведение после паузы."""
        player = self.players.get(ctx.guild.id)
        if not player or not player.voice_client: await ctx.send("Бот не на паузе или не в канале.", ephemeral=True); return
        await player.resume(ctx)

    @commands.hybrid_command(description='Удалить трек из очереди')
    @command_error_handler
    async def remove(self, ctx: commands.Context, position: int):
        """Удаляет трек из очереди по номеру (начиная с 1)."""
        player = self.players.get(ctx.guild.id)
        if not player: await ctx.send("Очередь пуста.", ephemeral=True); return
        await player.remove(ctx, position)

    @commands.hybrid_command(description='Показать очередь воспроизведения')
    @command_error_handler
    async def queue(self, ctx: commands.Context):
        """Показывает текущий трек и следующие в очереди."""
        player = self.players.get(ctx.guild.id)
        if not player: await ctx.send("Очередь пуста.", ephemeral=True); return
        await player.show_queue(ctx)

    # Команды volume, loop, shuffle удалены

    # --- Обработчик событий для автоотключения ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Автоматически отключает бота, если он остается один в канале."""
        if member.id == self.bot.user.id or before.channel == after.channel: return

        vc = member.guild.voice_client
        if vc and vc.channel == before.channel:
            await asyncio.sleep(1)
            vc = member.guild.voice_client # Перепроверяем vc
            if vc and len(vc.channel.members) == 1:
                logger.info(f"Бот остался один в канале {vc.channel.name}. Автоотключение.")
                player = self.players.get(member.guild.id)
                if player:
                    await player.stop() # Вызываем stop плеера (он сам отключится)
                    if member.guild.id in self.players: del self.players[member.guild.id]; logger.info(f"MusicPlayer удален для гильдии {member.guild.id} (автоотключение).")
                elif vc: # Если плеера нет, но бот в канале
                     await vc.disconnect(); logger.warning(f"Бот был один в канале {vc.channel.name}, плеер не найден. Принудительное отключение.")

async def setup(bot):
    await bot.add_cog(Music(bot))
