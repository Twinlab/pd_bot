"""Pydantic схемы для валидации данных API."""

from pydantic import BaseModel


class Item(BaseModel):
    """Модель предмета Dota 2."""

    id: int
    name: str
    displayName: str | None = None
    image: str | None = None


class ItemResponse(BaseModel):
    """Ответ API Stratz на запрос предметов."""

    items: list[Item]


class ConstantsResponse(BaseModel):
    """Обертка constants в ответе API."""

    constants: ItemResponse


class StratzResponse(BaseModel):
    """Корневой ответ API Stratz."""

    data: ConstantsResponse | None = None
