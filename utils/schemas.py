"""Pydantic схемы для валидации данных API."""

from typing import List, Optional

from pydantic import BaseModel


class Item(BaseModel):
    """Модель предмета Dota 2."""

    id: int
    name: str
    displayName: Optional[str] = None
    image: Optional[str] = None


class ItemResponse(BaseModel):
    """Ответ API Stratz на запрос предметов."""

    items: List[Item]


class ConstantsResponse(BaseModel):
    """Обертка constants в ответе API."""

    constants: ItemResponse


class StratzResponse(BaseModel):
    """Корневой ответ API Stratz."""

    data: Optional[ConstantsResponse] = None