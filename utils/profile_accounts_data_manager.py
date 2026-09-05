"""Изменение игровых привязок из профиля с проверкой лимитов."""

import asyncio
import logging
from typing import Literal
from weakref import WeakValueDictionary

from tortoise.transactions import in_transaction

from utils.models import CsLink, Link

AccountGame = Literal["dota", "cs"]
logger = logging.getLogger("bot.utils.profile_accounts")
_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


class AccountLinkError(ValueError):
    """Ожидаемая ошибка изменения привязки, которую можно показать пользователю."""


class ProfileAccountsDataManager:
    """Сохраняет привязки в существующих таблицах Dota и FACEIT."""

    async def add_link(
        self, user_id: int, game: AccountGame, identifier: str, nickname: str, *, limit: int
    ) -> None:
        """Добавляет аккаунт, атомарно проверяя дубликаты и лимит пользователя."""
        lock = _locks.setdefault(user_id, asyncio.Lock())
        async with lock, in_transaction() as connection:
            if game == "dota":
                dota_links = Link.filter(discord_user_id=user_id).using_db(connection)
                if await dota_links.filter(steam_id=int(identifier)).exists():
                    raise AccountLinkError("Этот аккаунт Dota 2 уже привязан.")
                if await dota_links.count() >= limit:
                    raise AccountLinkError(f"Можно привязать до {limit} аккаунтов Dota 2.")
                await Link.create(
                    discord_user_id=user_id, steam_id=int(identifier), using_db=connection
                )
            else:
                cs_links = CsLink.filter(discord_user_id=user_id).using_db(connection)
                if await cs_links.filter(faceit_player_id=identifier).exists():
                    raise AccountLinkError("Этот аккаунт FACEIT уже привязан.")
                if await cs_links.count() >= limit:
                    raise AccountLinkError(f"Можно привязать до {limit} аккаунтов FACEIT.")
                await CsLink.create(
                    discord_user_id=user_id,
                    faceit_player_id=identifier,
                    nickname=nickname,
                    using_db=connection,
                )
        logger.info("Привязан аккаунт %s пользователя %s", game, user_id)

    async def remove_link(self, user_id: int, game: AccountGame, identifier: str) -> None:
        """Отвязывает только выбранный аккаунт указанного пользователя."""
        if game == "dota":
            deleted = await Link.filter(discord_user_id=user_id, steam_id=int(identifier)).delete()
        else:
            deleted = await CsLink.filter(
                discord_user_id=user_id, faceit_player_id=identifier
            ).delete()
        if not deleted:
            raise AccountLinkError("Этот аккаунт уже отвязан. Обновите вкладку «Аккаунты».")
        logger.info("Отвязан аккаунт %s пользователя %s", game, user_id)
