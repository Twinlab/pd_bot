import discord
from typing import List, Dict, Optional
from .embeds import create_embed, format_duration
from .player import MusicPlayer

class PlayerControlView(discord.ui.View):
    """View с кнопками управления плеером."""
    def __init__(self, player: MusicPlayer, timeout: Optional[float] = 600):
        super().__init__(timeout=timeout)
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        vc = self.player.voice_client
        can_control = vc is not None and self.player.current_track is not None
        pause_resume_button = discord.utils.get(self.children, custom_id="music:pause_resume")
        if pause_resume_button:
            pause_resume_button.disabled = not can_control
            if self.player.is_paused:
                pause_resume_button.label = "▶️ Продолжить"
                pause_resume_button.style = discord.ButtonStyle.green
            else:
                pause_resume_button.label = "⏸️ Пауза"
                pause_resume_button.style = discord.ButtonStyle.secondary
        skip_button = discord.utils.get(self.children, custom_id="music:skip")
        if skip_button:
            skip_button.disabled = not can_control
        stop_button = discord.utils.get(self.children, custom_id="music:stop")
        if stop_button:
            stop_button.disabled = vc is None
        queue_button = discord.utils.get(self.children, custom_id="music:queue")
        if queue_button:
            queue_button.disabled = False

    async def _check_voice_channel(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале!", ephemeral=True)
            return False
        if self.player.voice_client and interaction.user.voice.channel != self.player.voice_client.channel:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале, что и бот!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.secondary, custom_id="music:pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        if self.player.is_paused:
            await self.player.resume(interaction)
        else:
            await self.player.pause(interaction)
        self._update_buttons()
        if not interaction.response.is_done():
            await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.primary, custom_id="music:skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await self.player.skip(interaction)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await self.player.stop(interaction)

    @discord.ui.button(label="📜 Очередь", style=discord.ButtonStyle.blurple, custom_id="music:queue", row=0)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.show_queue(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def on_timeout(self):
        if self.player.now_playing_message:
            try:
                await self.player.now_playing_message.edit(view=None)
            except discord.NotFound:
                pass
            except Exception:
                pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

class SearchResultSelect(discord.ui.Select):
    """Выпадающий список для выбора трека из результатов поиска."""
    def __init__(self, player: MusicPlayer, interaction: discord.Interaction, entries: List[Dict]):
        self.player = player
        self.original_interaction = interaction
        self.entries = entries
        options = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            label = entry.get('title', f'Неизвестное название {i+1}')
            if len(label) > 100:
                label = label[:97] + "..."
            desc = f"Автор: {entry.get('uploader', 'Н/Д')} | {format_duration(entry.get('duration'))}"
            if len(desc) > 100:
                desc = desc[:97] + "..."
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))
        if not options:
            options.append(discord.SelectOption(label="Ничего не найдено", value="-1", description="Попробуйте другой запрос"))
        super().__init__(placeholder="Выберите трек для добавления...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_index = int(self.values[0])
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass
        except Exception:
            pass
        if selected_index == -1:
            await interaction.response.send_message("Поиск отменен.", ephemeral=True, delete_after=10)
            return
        if not (0 <= selected_index < len(self.entries)):
            await interaction.response.send_message("Неверный выбор.", ephemeral=True, delete_after=10)
            return
        selected_entry = self.entries[selected_index]
        url = selected_entry.get('webpage_url', selected_entry.get('original_url', selected_entry.get('url')))
        if not url:
            await interaction.response.send_message("❌ Ошибка: Не удалось получить URL для выбранного трека.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Вы должны быть в голосовом канале, чтобы добавить трек!", ephemeral=True)
            return
        connected = await self.player.connect(interaction.user.voice.channel)
        if not connected:
            await interaction.response.send_message("Не удалось подключиться к вашему голосовому каналу.", ephemeral=True)
            return
        requester = self.original_interaction.user
        await interaction.response.send_message(f"⏳ Добавляем '{selected_entry.get('title', 'выбранный трек')}'...", ephemeral=True)
        await self.player.queue_track(url, requester, interaction)

class SearchView(discord.ui.View):
    """View, содержащая выпадающий список результатов поиска."""
    def __init__(self, player: MusicPlayer, interaction: discord.Interaction, entries: List[Dict], timeout=60.0):
        super().__init__(timeout=timeout)
        self.player = player
        self.original_interaction = interaction
        self.add_item(SearchResultSelect(player, interaction, entries))

    async def on_timeout(self):
        try:
            await self.original_interaction.edit_original_response(content="⏱️ Время выбора трека истекло.", view=None, embed=None)
        except discord.NotFound:
            pass
        except Exception:
            pass
        self.stop()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Только пользователь, запустивший поиск, может выбрать трек.", ephemeral=True)
            return False
        return True
