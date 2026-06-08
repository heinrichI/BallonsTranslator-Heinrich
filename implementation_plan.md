# Implementation Plan

Извлечение хардкода количества контрольных точек кривых (3) в именованные константы в FlowTextBlkItem и FlowShapeControl.

В коде FlowTextBlkItem и FlowShapeControl число 3 (количество контрольных точек на одну сторону границы) используется в 16+ местах как хардкод. Это делает код хрупким при любом изменении количества точек. Требуется вынести все вхождения в одну из двух констант: `DEFAULT_POINTS_PER_SIDE` (для инициализации из прямоугольника) и `MIN_POINTS_PER_SIDE` (для проверок минимально допустимого количества). Константы определяются в `ui/flow_textitem.py` и импортируются в `ui/flow_shapecontrol.py`.

[Types]

Типы не меняются — только числовые литералы заменяются на константы. Определение констант:

```python
# ui/flow_textitem.py, module-level
DEFAULT_POINTS_PER_SIDE: int = 3  # количество точек при инициализации из прямоугольника
MIN_POINTS_PER_SIDE: int = 3      # минимальное количество точек для кривой Безье и удаления
```

[Files]

Два существующих файла изменяются, новых файлов не создаётся.

- **ui/flow_textitem.py** — определить константы в начале файла, заменить все вхождения `3` (как количество точек) на константы
- **ui/flow_shapecontrol.py** — импортировать константы из `flow_textitem`, заменить все вхождения

[Functions]

Изменяемые функции (сигнатуры не меняются, только логика использует константы вместо литералов):

**`ui/flow_textitem.py`:**
1. `build_quad_path(points)` — строка `elif len(pts) >= 3:` → `elif len(pts) >= MIN_POINTS_PER_SIDE:`
2. `FlowTextBlkItem._init_points_from_rect(rect)` — жёстко закодированные 3 точки (top, mid, bottom) заменить на цикл по `range(DEFAULT_POINTS_PER_SIDE)`, интерполируя y-координаты равномерно между y0 и y1
3. `FlowTextBlkItem.showFlowContextMenu(scene_pos, screen_pos)` — комментарии и докстринги обновить

**`ui/flow_shapecontrol.py`:**
1. `FlowShapeControl.__init__` — `for idx in range(3)` x2 → `range(DEFAULT_POINTS_PER_SIDE)`
2. `FlowControlHandle.showHandleContextMenu` — `can_delete = len(pts) > 2` → `> MIN_POINTS_PER_SIDE`
3. `FlowResizeHandle.mouseMoveEvent` — индексы `[0]`, `[1]`, `[-1]`, `[mid]` **не трогать** (уже работают с динамической длиной); оставить как есть, так как они корректно работают при любом `len >= MIN_POINTS_PER_SIDE`
4. `FlowShapeControl.updateHandlePositions` — индексы `[0]`, `[-1]` **не трогать** (динамические)

[Classes]

Изменяемые классы (структура не меняется, только использование констант):

- **`FlowTextBlkItem`** (`ui/flow_textitem.py`): докстринги (2 места), `_init_points_from_rect` (3→DEFAULT)
- **`FlowShapeControl`** (`ui/flow_shapecontrol.py`): `__init__` (range(DEFAULT)), `rebuildHandles` (range(len(...)) — уже динамическое, не трогать), комментарии
- **`FlowControlHandle`** (`ui/flow_shapecontrol.py`): `showHandleContextMenu` (`> 2` → `> MIN_POINTS_PER_SIDE`)
- **`FlowResizeHandle`** (`ui/flow_shapecontrol.py`): `mouseMoveEvent` — оставить как есть (динамические индексы)

[Dependencies]

Нет новых зависимостей. Константы — Python-переменные, не требующие импорта пакетов.

[Testing]

- `tests/test_scenetext_manager_visibility.py` — запустить для проверки, что поведение не изменилось
- Ручная проверка: создать FlowTextBlkItem, убедиться что 3+3 хендла, удаление точки блокируется когда остаётся 3, добавление точки работает, кривая Безье строится
- Визуальная проверка: скриншот границ до и после изменений

[Implementation Order]

1. Открыть `ui/flow_textitem.py`, определить `DEFAULT_POINTS_PER_SIDE` и `MIN_POINTS_PER_SIDE` в начале файла (после импортов, до helper-функций)
2. Заменить `build_quad_path` — `len(pts) >= 3` на `len(pts) >= MIN_POINTS_PER_SIDE`
3. Заменить `_init_points_from_rect` — с жёстко 3 точек на цикл по `range(DEFAULT_POINTS_PER_SIDE)` с равномерной интерполяцией y
4. Обновить докстринги в `FlowTextBlkItem.__init__` и в docstring файла
5. Открыть `ui/flow_shapecontrol.py`, добавить импорт констант
6. Заменить `range(3)` x2 в `FlowShapeControl.__init__` на `range(DEFAULT_POINTS_PER_SIDE)`
7. Заменить `len(pts) > 2` в `FlowControlHandle.showHandleContextMenu` на `len(pts) > MIN_POINTS_PER_SIDE`
8. Обновить комментарий `# 6 handles: left[0,1,2] then right[0,1,2]`
9. Запустить тесты и проверить что ничего не сломалось