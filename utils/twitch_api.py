import aiohttp
import logging
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
import json

logger = logging.getLogger("bot.twitch_api")

class TwitchAPI:
    """
    Класс для взаимодействия с Twitch API.
    """
    def __init__(self, client_id: str, client_secret: str):
        """
        Инициализирует клиент Twitch API.
        
        Args:
            client_id: Client ID приложения Twitch
            client_secret: Client Secret приложения Twitch
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = 0
        self.base_url = "https://api.twitch.tv/helix"
        self.auth_url = "https://id.twitch.tv/oauth2/token"
        self.session = None
    
    async def initialize(self):
        """Инициализирует сессию и получает токен доступа."""
        self.session = aiohttp.ClientSession()
        await self.get_access_token()
    
    async def close(self):
        """Закрывает сессию."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_access_token(self) -> bool:
        """
        Получает токен доступа для Twitch API.
        
        Returns:
            bool: True если токен получен успешно, False в случае ошибки
        """
        # Если токен еще действителен, не запрашиваем новый
        if self.access_token and time.time() < self.token_expires_at:
            return True
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            params = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials'
            }
            
            async with self.session.post(self.auth_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self.access_token = data['access_token']
                    # Устанавливаем время истечения токена (с запасом в 10 минут)
                    self.token_expires_at = time.time() + data['expires_in'] - 600
                    logger.info("Получен новый токен доступа Twitch API")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка при получении токена доступа: {response.status} - {error_text}")
                    return False
        except Exception as e:
            logger.error(f"Исключение при получении токена доступа: {e}", exc_info=True)
            return False
    
    async def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Выполняет запрос к Twitch API с автоматическим обновлением токена.
        
        Args:
            endpoint: Конечная точка API (без базового URL)
            params: Параметры запроса
            
        Returns:
            Optional[Dict]: Данные ответа или None в случае ошибки
        """
        if not await self.get_access_token():
            return None
        
        url = f"{self.base_url}/{endpoint}"
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {self.access_token}'
        }
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    # Токен истек, получаем новый и повторяем запрос
                    logger.warning("Токен доступа истек, получаем новый")
                    self.access_token = None
                    if await self.get_access_token():
                        return await self._make_request(endpoint, params)
                    return None
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка API: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при запросе к API: {e}", exc_info=True)
            return None
    
    async def get_users(self, usernames: List[str]) -> List[Dict]:
        """
        Получает информацию о пользователях Twitch по их именам.
        
        Args:
            usernames: Список имен пользователей Twitch
            
        Returns:
            List[Dict]: Список словарей с информацией о пользователях
        """
        if not usernames:
            return []
        
        # Twitch API позволяет запрашивать до 100 пользователей за раз
        chunk_size = 100
        all_users = []
        
        for i in range(0, len(usernames), chunk_size):
            chunk = usernames[i:i + chunk_size]
            params = {'login': chunk}
            
            response = await self._make_request('users', params)
            if response and 'data' in response:
                all_users.extend(response['data'])
        
        return all_users
    
    async def get_streams(self, user_ids: List[str]) -> List[Dict]:
        """
        Получает информацию о текущих стримах пользователей.
        
        Args:
            user_ids: Список ID пользователей Twitch
            
        Returns:
            List[Dict]: Список словарей с информацией о стримах
        """
        if not user_ids:
            return []
        
        # Twitch API позволяет запрашивать до 100 стримов за раз
        chunk_size = 100
        all_streams = []
        
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            params = {'user_id': chunk}
            
            response = await self._make_request('streams', params)
            if response and 'data' in response:
                all_streams.extend(response['data'])
        
        return all_streams
    
    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        """
        Получает информацию о пользователе Twitch по его имени.
        
        Args:
            username: Имя пользователя Twitch
            
        Returns:
            Optional[Dict]: Словарь с информацией о пользователе или None
        """
        users = await self.get_users([username])
        return users[0] if users else None
    
    async def is_user_live(self, user_id: str) -> Tuple[bool, Optional[Dict]]:
        """
        Проверяет, ведет ли пользователь стрим в данный момент.
        
        Args:
            user_id: ID пользователя Twitch
            
        Returns:
            Tuple[bool, Optional[Dict]]: (True, данные стрима) если пользователь онлайн, (False, None) если оффлайн
        """
        streams = await self.get_streams([user_id])
        if streams:
            return True, streams[0]
        return False, None
