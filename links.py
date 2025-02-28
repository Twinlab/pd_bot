import json
import os
import logging
import discord

# Настройка логирования
logger = logging.getLogger("bot")

# Файл для хранения привязок
user_links_file = "user_links.json"

# Загрузка данных из файла
def load_user_links():
    if not os.path.exists(user_links_file):
        logger.info(f"Файл {user_links_file} не существует, создаем пустой словарь")
        return {}
 
    try:
        with open(user_links_file, "r") as f:
            data = json.load(f)
        
        # Преобразуем все ключи в строки (если вдруг они не строки)
        str_data = {}
        for k, v in data.items():
            str_data[str(k)] = v
            
        logger.info(f"Загружены данные привязок аккаунтов: {str_data}")
        return str_data
        
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON в {user_links_file}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке {user_links_file}: {e}")
        return {}

# Сохранение данных в файл
def save_user_links(user_links):
    try:
        # Создаем папку, если её нет
        os.makedirs(os.path.dirname(user_links_file) or '.', exist_ok=True)
        
        with open(user_links_file, "w") as f:
            json.dump(user_links, f, indent=4)
            
        logger.info(f"Данные привязок аккаунтов сохранены в {user_links_file}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных привязок аккаунтов: {e}")
        return False

# Вспомогательная функция для отправки приватного ответа
async def send_response(ctx, message):
    """Отправляет приватный ответ в зависимости от типа контекста команды."""
    try:
        # Для slash-команд с отложенным ответом
        if hasattr(ctx, 'followup'):
            await ctx.followup.send(message, ephemeral=True)
        # Для slash-команд без отложенного ответа
        elif hasattr(ctx, 'respond'):
            await ctx.respond(message, ephemeral=True)
        # Для обычных префиксных команд - пытаемся сделать приватным
        else:
            try:
                # Пробуем через скрытый ответ
                await ctx.reply(message, ephemeral=True)
            except:
                # Если не получается, отправляем DM
                await ctx.author.send(message)
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа: {e}")
        # Запасной вариант - отправка в личку
        try:
            await ctx.author.send(message)
        except:
            logger.error(f"Не удалось отправить приватный ответ")
            # В крайнем случае отправляем обычное сообщение
            try:
                await ctx.send(message)
                # И сразу удаляем через 10 секунд
                import asyncio
                msg = await ctx.send(message)
                await asyncio.sleep(10)
                await msg.delete()
            except:
                logger.error(f"Не удалось отправить ответ вообще")

# Привязка аккаунта Dota 2
async def handle_link(ctx, player_id, user_links=None):
    """Привязывает аккаунт Dota 2 к Discord аккаунту.
    
    Args:
        ctx: Контекст команды Discord
        player_id: ID игрока Dota 2
        user_links: Словарь с привязками аккаунтов (опционально)
    """
    if user_links is None:
        user_links = load_user_links()
    
    # Всегда используем строковый ID
    user_id = str(ctx.author.id)
    
    logger.info(f"Привязка аккаунта Dota 2 {player_id} к Discord ID {user_id}")
    
    # Если у пользователя еще нет привязок, создаем список
    if user_id not in user_links:
        user_links[user_id] = []
    
    # Проверяем, не привязан ли уже этот аккаунт
    if player_id in user_links[user_id]:
        await send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} уже привязан к вашему аккаунту Discord.")
        return
    
    # Добавляем аккаунт в список привязок
    user_links[user_id].append(player_id)
    
    # Сохраняем изменения
    success = save_user_links(user_links)
    
    if success:
        await send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} успешно привязан к вашему аккаунту Discord.")
        
        # Если это первый привязанный аккаунт, добавляем подсказку
        if len(user_links[user_id]) == 1:
            await send_response(ctx, "Теперь вы можете использовать команду `/lastmatch`, чтобы увидеть информацию о вашем последнем матче.")
        else:
            all_accounts = ", ".join(str(acc) for acc in user_links[user_id])
            await send_response(ctx, f"У вас привязано несколько аккаунтов: {all_accounts}. "+
                          "При использовании `/lastmatch` бот автоматически выберет аккаунт с самым последним матчем.")
    else:
        await send_response(ctx, "Произошла ошибка при сохранении привязки. Пожалуйста, попробуйте снова.")

# Отвязка аккаунта Dota 2
async def handle_unlink(ctx, user_links=None, player_id=None):
    """Отвязывает аккаунт Dota 2 от Discord аккаунта.
    
    Args:
        ctx: Контекст команды Discord
        user_links: Словарь с привязками аккаунтов (опционально)
        player_id: ID игрока Dota 2 для отвязки (если None, то отвязываются все аккаунты)
    """
    if user_links is None:
        user_links = load_user_links()
    
    # Всегда используем строковый ID
    user_id = str(ctx.author.id)
    
    logger.info(f"Отвязка аккаунта Dota 2 от Discord ID {user_id}. Player ID: {player_id}")
    
    # Проверяем, есть ли вообще привязки у пользователя
    if user_id not in user_links or not user_links[user_id]:
        await send_response(ctx, "У вас нет привязанных аккаунтов Dota 2.")
        return
    
    # Если указан конкретный ID для отвязки
    if player_id is not None:
        if player_id in user_links[user_id]:
            user_links[user_id].remove(player_id)
            save_success = save_user_links(user_links)
            
            if save_success:
                await send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} успешно отвязан от вашего аккаунта Discord.")
                
                # Если остались другие аккаунты, показываем их
                if user_links[user_id]:
                    remaining = ", ".join(str(acc) for acc in user_links[user_id])
                    await send_response(ctx, f"У вас остаются привязанными следующие аккаунты: {remaining}")
            else:
                await send_response(ctx, "Произошла ошибка при сохранении изменений. Пожалуйста, попробуйте снова.")
        else:
            # Показываем список привязанных аккаунтов, если пользователь указал неверный ID
            accounts = ", ".join(str(acc) for acc in user_links[user_id])
            await send_response(ctx, f"Аккаунт Dota 2 с ID {player_id} не привязан к вашему аккаунту Discord.\n"+
                          f"Ваши привязанные аккаунты: {accounts}")
    else:
        # Отвязываем все аккаунты
        user_links[user_id] = []
        save_success = save_user_links(user_links)
        
        if save_success:
            await send_response(ctx, f"Все аккаунты Dota 2 были успешно отвязаны от вашего аккаунта Discord.")
        else:
            await send_response(ctx, "Произошла ошибка при сохранении изменений. Пожалуйста, попробуйте снова.")
 
# Просмотр привязанных аккаунтов
async def handle_links(ctx, user_links=None):
    """Показывает список аккаунтов Dota 2, привязанных к Discord аккаунту.
    
    Args:
        ctx: Контекст команды Discord
        user_links: Словарь с привязками аккаунтов (опционально)
    """
    if user_links is None:
        user_links = load_user_links()
    
    # Всегда используем строковый ID
    user_id = str(ctx.author.id)
    
    logger.info(f"Запрос списка привязанных аккаунтов для Discord ID {user_id}. Доступные ключи: {list(user_links.keys())}")
    
    # Проверяем, есть ли привязки у пользователя
    if user_id in user_links and user_links[user_id]:
        linked_accounts = "\n".join(str(account_id) for account_id in user_links[user_id])
        await send_response(ctx, f"Ваши привязанные аккаунты Dota 2:\n{linked_accounts}")
        
        if len(user_links[user_id]) > 1:
            await send_response(ctx, "При использовании команды `/lastmatch` бот автоматически выберет аккаунт с самым последним матчем.")
    else:
        await send_response(ctx, "У вас нет привязанных аккаунтов Dota 2. Используйте команду `/link PLAYER_ID`, чтобы привязать свой аккаунт.")