# Сплеши карт CS2 для карточек `/cslastmatch`

Сюда кладутся фоновые картинки карт CS2. Имя файла — это имя карты **без префикса
`de_`** (как его отдаёт FACEIT в `round_stats["Map"]`), расширение — `jpg`, `jpeg`,
`png` или `webp`. Примеры:

```
dust2.jpg
mirage.jpg
inferno.jpg
nuke.jpg
overpass.jpg
ancient.jpg
anubis.jpg
vertigo.jpg
train.jpg
```

Рекомендуемый размер — не меньше 1080×1080 (картинка обрезается «cover» под квадрат
и затемняется). Если файла для карты нет, рендер рисует procedural-фон (тёмный
градиент, тонированный результатом) — карточка не ломается.

Загрузчик: `utils/match_card/images.py::load_map_image`.

## Текущий набор

Скриншоты карт взяты из [ghostcap-gaming/cs2-map-images](https://github.com/ghostcap-gaming/cs2-map-images)
(in-game скриншоты CS2, ассеты Valve), сжаты в JPEG q85. Лежат: `dust2`, `mirage`,
`inferno`, `nuke`, `ancient`, `anubis`, `vertigo`, `overpass`, `train`, `cache`.
Чтобы добавить/обновить карту — положи `<карта>.jpg` сюда.
