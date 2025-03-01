import discord
import json
import os
import logging
from typing import Optional
from discord.ext import commands
from discord import Intents, app_commands

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("bot")


# Импорты функций из модулей
from on_message import handle_message
from snipe import on_message_delete as handle_message_delete, handle_snipe
from jokes import handle_penis
from links import handle_link, handle_unlink, handle_links, user_links_file
from avatar import handle_avatar
from giveaway import handle_giveaway
from deathbattle import handle_deathbattle
from admin import clear_messages
from lastmatch import handle_lastmatch
from music import handle_play, handle_skip, handle_stop, handle_pause, handle_resume, handle_remove

# Функция загрузки конфигурации
def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {"BOT_TOKEN": None}

# Функция для загрузки привязок аккаунтов
def load_user_links():
    if not os.path.exists(user_links_file):
        logger.info(f"Файл {user_links_file} не существует, создаем пустой словарь")
        return {}
 
    try:
        with open(user_links_file, "r") as f:
            data = json.load(f)
 
        # Если данные в старом формате (список), конвертируем
        if isinstance(data, list):
            logger.info(f"Данные в {user_links_file} в старом формате, конвертируем")
            new_data = {}
            for item in data:
                if isinstance(item, dict) and "user" in item and "links" in item:
                    user_id = str(item["user"])
                    new_data[user_id] = item["links"]
 
            # Сохраняем конвертированные данные
            with open(user_links_file, "w") as f:
                json.dump(new_data, f, indent=4)
 
            logger.info(f"Данные в {user_links_file} были конвертированы в новый формат")
            return new_data
 
        # Если данные уже в новом формате (словарь)
        elif isinstance(data, dict):
            logger.info(f"Данные в {user_links_file} уже в новом формате")
            return data
 
        # Если формат неизвестен
        else:
            logger.warning(f"Неизвестный формат данных в {user_links_file}")
            return {}
 
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в {user_links_file}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке {user_links_file}: {e}")
        return {}

# Загрузка конфигурации
config = load_config()

# Настройка интентов бота
intents = Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True

# Создание экземпляра бота
bot = commands.Bot(command_prefix="!", intents=intents)

# Обработчики событий
@bot.event
async def on_ready():
    """Вызывается, когда бот готов к работе"""
    logger.info(f"Бот запущен как {bot.user.name}")
    logger.info(f"Discord.py версия: {discord.__version__}")
    
    # Синхронизация команд
    try:
        synced = await bot.tree.sync()
        logger.info(f"Синхронизировано {len(synced)} команд")
    except Exception as e:
        logger.error(f"Ошибка при синхронизации команд: {e}")
    
    # Установка статуса
    await bot.change_presence(activity=discord.Game(name="Делаю милые вещи и пью чай"))
    
    # Запуск фоновых задач
    #bot.loop.create_task(check_streams(bot))

@bot.event
async def on_message(message):
    """Обработка сообщений"""
    if message.author.bot:
        return
    await handle_message(message)
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    """Обработка изменений голосового состояния безопасным способом"""
    try:
        # Если это бот отключился от канала
        if member.id == bot.user.id and before.channel and not after.channel:
            # Импортируем только здесь, чтобы избежать циклических импортов
            from music import cleanup_player
            await cleanup_player(member.guild)
            return
            
        # Если пользователь (не бот) покинул канал, где находится бот
        if before.channel and member != bot.user and not member.bot:
            # Проверяем, находится ли бот в этом канале
            voice_client = member.guild.voice_client
            if voice_client and voice_client.channel == before.channel:
                # Проверяем, остались ли пользователи (не боты) в канале
                users_in_channel = [m for m in before.channel.members if not m.bot]
                
                if not users_in_channel:
                    # Импортируем только здесь, чтобы избежать циклических импортов
                    from music import auto_disconnect
                    await auto_disconnect(member.guild, before.channel)
    except Exception as e:
        # Логируем любые ошибки, чтобы избежать падения бота
        print(f"Ошибка в обработчике voice_state_update: {e}")

@bot.event
async def on_message_delete(message):
    """Обработка удаленных сообщений"""
    await handle_message_delete(message)

@bot.event
async def on_member_remove(member: discord.Member):
    """Обработка выхода участника с сервера"""
    try:
        channel = discord.utils.get(member.guild.text_channels, name='general')
        if channel:
            await channel.send(f"**{member.name}** ббак")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о выходе участника: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Глобальный обработчик ошибок команд"""
    if isinstance(error, commands.CommandNotFound):
        pass  # Игнорируем ошибки о ненайденных командах
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Отсутствует обязательный аргумент: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Неверный аргумент команды")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("У вас недостаточно прав для выполнения этой команды")
    else:
        logger.error(f"Необработанная ошибка команды: {error}")

# Команды
@bot.hybrid_command(name='deathbattle', description='Запускает дезбаттл между двумя пользователями')
async def deathbattle_cmd(ctx, member1: Optional[discord.Member] = None, member2: Optional[discord.Member] = None):
    """Запускает битву между двумя пользователями"""
    await handle_deathbattle(ctx, member1, member2)

@bot.hybrid_command(description='Показывает последнее удаленное сообщение')
async def snipe(ctx):
    """Показывает последнее удаленное сообщение"""
    await handle_snipe(ctx)

@bot.hybrid_command(description='Показывает размер пениса')
async def penis(ctx):
    """Генерирует случайный размер пениса"""
    await handle_penis(ctx)

@bot.hybrid_command(description='Показывает аватар пользователя')
async def avatar(ctx, mentioned_user: Optional[discord.Member] = None):
    """Показывает аватар указанного пользователя или автора команды"""
    await handle_avatar(ctx, mentioned_user)

@bot.hybrid_command(description='Привязать аккаунт Dota 2')
async def link(ctx, player_id: int):
    """Привязывает аккаунт Dota 2 к Discord аккаунту"""
    try:
        # Для slash-команд делаем ответ приватным
        if hasattr(ctx, 'defer'):
            await ctx.defer(ephemeral=True)
        
        user_links = load_user_links()
        await handle_link(ctx, player_id, user_links)
    except Exception as e:
        logger.error(f"Ошибка в команде link: {e}", exc_info=True)
        try:
            # Пытаемся отправить приватное сообщение об ошибке
            await ctx.author.send(f"Произошла ошибка: {e}")
        except:
            pass
 
@bot.hybrid_command(description='Отвязать аккаунт Dota 2')
async def unlink(ctx, player_id: Optional[int] = None):
    """Отвязывает аккаунт Dota 2 от Discord аккаунта"""
    try:
        # Для slash-команд делаем ответ приватным
        if hasattr(ctx, 'defer'):
            await ctx.defer(ephemeral=True)
        
        user_links = load_user_links()
        await handle_unlink(ctx, user_links, player_id)
    except Exception as e:
        logger.error(f"Ошибка в команде unlink: {e}", exc_info=True)
        try:
            # Пытаемся отправить приватное сообщение об ошибке
            await ctx.author.send(f"Произошла ошибка: {e}")
        except:
            pass
 
@bot.hybrid_command(description='Показать привязанные аккаунты Dota 2')
async def links(ctx):
    """Показывает список привязанных аккаунтов Dota 2"""
    try:
        # Для slash-команд делаем ответ приватным
        if hasattr(ctx, 'defer'):
            await ctx.defer(ephemeral=True)
        
        user_links = load_user_links()
        await handle_links(ctx, user_links)
    except Exception as e:
        logger.error(f"Ошибка в команде links: {e}", exc_info=True)
        try:
            # Пытаемся отправить приватное сообщение об ошибке
            await ctx.author.send(f"Произошла ошибка: {e}")
        except:
            pass
 
@bot.hybrid_command(description='Показать информацию о последнем матче')
async def lastmatch(ctx, member: Optional[discord.Member] = None):
    """Показывает информацию о последнем матче Dota 2"""
    try:
        user_links = load_user_links()
        await ctx.defer()
        await handle_lastmatch(ctx, user_links, member)
    except Exception as e:
        logger.error(f"Ошибка в команде lastmatch: {e}", exc_info=True)
        await ctx.send(f"Произошла ошибка: {e}")
# Музыкальные команды
 
@bot.hybrid_command(description='Воспроизвести музыку по ссылке YouTube или поисковому запросу')
async def play(ctx, *, query: str):
    """Воспроизводит музыку из YouTube с возможностью поиска"""
    await handle_play(ctx, query)
 
@bot.hybrid_command(description='Пропустить текущий трек')
async def skip(ctx):
    """Пропускает текущий трек"""
    await handle_skip(ctx)
 
@bot.hybrid_command(description='Остановить воспроизведение и очистить очередь')
async def stop(ctx):
    """Останавливает воспроизведение и очищает очередь"""
    await handle_stop(ctx)
 
@bot.hybrid_command(description='Приостановить воспроизведение')
async def pause(ctx):
    """Ставит воспроизведение на паузу"""
    await handle_pause(ctx)
 
@bot.hybrid_command(description='Возобновить воспроизведение')
async def resume(ctx):
    """Возобновляет воспроизведение"""
    await handle_resume(ctx)
 
@bot.hybrid_command(description='Показать очередь воспроизведения')
async def queue(ctx):
    """Показывает очередь воспроизведения"""
    await handle_queue(ctx)
 
@bot.hybrid_command(description='Удалить трек из очереди по позиции')
async def remove(ctx, position: int):
    """Удаляет трек из очереди по позиции"""
    await handle_remove(ctx, position)

# Команды администратора
@bot.hybrid_command(description='Создать розыгрыш')
@commands.has_permissions(administrator=True)
async def giveaway(ctx, duration: str, *, description: str):
    """Создает розыгрыш с указанной длительностью и описанием"""
    await handle_giveaway(ctx, duration, description=description)

@bot.hybrid_command(description='Очистить сообщения')
@commands.has_permissions(administrator=True)
async def clear(ctx, count: Optional[int] = None):
    """Очищает указанное количество сообщений в канале"""
    try:
        # Сначала откладываем ответ
        await ctx.defer()
        # Затем выполняем очистку
        await clear_messages(ctx, count=count)
    except discord.NotFound:
        # Игнорируем ошибку "Unknown interaction", т.к. команда все равно выполняется
        pass
    except Exception as e:
        logger.error(f"Ошибка при очистке сообщений: {e}", exc_info=True)
        try:
            await ctx.followup.send(f"Произошла ошибка: {e}")
        except:
            pass

@bot.hybrid_command(name="clear_user", description='Очистить сообщения пользователя')
@commands.has_permissions(administrator=True)
async def clear_user(ctx, user: discord.Member, count: Optional[int] = None):
    """Очищает сообщения указанного пользователя"""
    try:
        # Сначала откладываем ответ
        await ctx.defer()
        # Затем выполняем очистку
        await clear_messages(ctx, user=user, count=count)
    except discord.NotFound:
        # Игнорируем ошибку "Unknown interaction"
        pass
    except Exception as e:
        logger.error(f"Ошибка при очистке сообщений пользователя: {e}", exc_info=True)
        try:
            await ctx.followup.send(f"Произошла ошибка: {e}")
        except:
            pass

# Запуск бота
if __name__ == "__main__":
    # Проверяем наличие токена
    if not config.get("BOT_TOKEN"):
        logger.critical("Токен бота не найден в config.json!")
        exit(1)
    
    # Запускаем бота
    try:
        bot.run(config["BOT_TOKEN"])
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")
        exit(1)