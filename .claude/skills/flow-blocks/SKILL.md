# Flow Text Blocks — полный справочник

Используй этот навык при работе с `FlowTextBlkItem`, `_update_flow_layout`, shrink/grow, auto-font-sizing, boundary control points, или при исправлении ошибок выхода текста за границы блока.

---

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `ui/flow_textitem.py` | `FlowTextBlkItem` — основной класс, auto-shrink/grow, control points |
| `ui/scene_textlayout.py` | `HorizontalTextDocumentLayout` — custom layout engine с boundary functions |
| `ui/flow_shapecontrol.py` | `FlowShapeControl` — handle'ы для перетаскивания boundary control points |
| `ui/scenetext_manager.py` | `layout_textblk()`, `_find_best_font_size()` — pipeline layout |
| `ui/textitem.py` | `TextBlkItem` — базовый класс |
| `ui/drawing_commands.py` | `RunBlkTransCommand` — undo-команда для перевода блоков |
| `ui/font_auto_adjuster.py` | `FontAutoAdjuster` — shrink/grow логика |
| `ui/canvas.py` | Canvas — рендеринг, mouse events, делегирование в FlowShapeControl |
| `ui/textedit_commands.py` | Undo/redo команды для текста |
| `utils/shared.py` | `LOG_PREFIXES` — фильтрация логов по префиксу текста блока |

### Не трогались (используют duck-typing / hasattr):
- `ui/scenetext_manager.py` (кроме layout_textblk)
- `ui/textedit_commands.py`
- `ui/texteditshapecontrol.py`
- `ui/textitem.py`
- `utils/textblock.py`

---

## Архитектура Flow Text Layout

### Control Points (границы)

Каждый `FlowTextBlkItem` имеет **6 контрольных точек** (3 слева + 3 справа) для изогнутых границ:
- `_left_points`: `[QPointF(0, 0), QPointF(0, h/2), QPointF(0, h)]`
- `_right_points`: `[QPointF(w, 0), QPointF(w, h/2), QPointF(w, h)]`

Points хранятся в item-local coordinates.

**Ключевые функции:**
- `interpolate_boundary(points, y)` — линейная интерполяция между точками границы
- `build_quad_path(points)` — квадратичный Bezier path через 3 точки (проходит через ВСЕ 3)
- `_init_points_from_rect()` — инициализация 3+3 точек из прямоугольника
- `_get_line_x_offsets()` — per-line смещения для layout
- `save_flow_points()` — сериализация точек в `TextBlock.left_points/right_points`

### Layout Engine

`HorizontalTextDocumentLayout` (наследник `SceneTextLayout`):
- Использует **callable boundary functions** (`left_fn`, `right_fn`) вместо per-line-index dicts
- `set_boundary_functions(left_fn, right_fn)` → вызывает `reLayout()`
- Каждая строка получает ширину из boundary functions на своей y-позиции
- `_line_left_offsets`, `_line_right_offsets` — словари per-line смещений
- `set_line_x_offsets(left_offsets, right_offsets)` — установка и relayout

### Ключевые метрики

| Метрика | Описание | Использование |
|---------|----------|---------------|
| `layout.shrink_height` | Фактическая высота текста внутри boundaries | **ИСПОЛЬЗОВАТЬ ЭТО** |
| `layout.shrink_width` | Фактическая ширина текста | Использовать для width overflow |
| `document().size().height()` | Qt document height | **НЕ ИСПОЛЬЗОВАТЬ** для flow layout |
| `layout.available_height` | Текущая доступная высота | Меняется `reLayout()` |
| `layout.max_height` | Максимальная высота layout | Меняется `reLayout()` |

---

## `_update_flow_layout()` — все места вызова

### Определение
`ui/flow_textitem.py:406` — единственное определение метода.

### Вызовы из production кода

| # | Файл | Строка | Контекст | ГROW включён? |
|---|------|--------|----------|---------------|
| 1 | `flow_textitem.py` | 554 | `setVertical()` — переключение vertical/horizontal | **Да** |
| 2 | `flow_textitem.py` | 619 | `set_size(auto_font_adjust=True)` | Зависит от `auto_font_adjust` |
| 3 | `flow_textitem.py` | 749 | `mouseReleaseEvent()` — endReshape | **Да** |
| 4 | `scenetext_manager.py` | 974 | `layout_textblk()` — pipeline auto-layout | **Нет** (отключён через `_auto_grow_enabled=False`) |
| 5 | `drawing_commands.py` | 152 | `RunBlkTransCommand` — после бинарного поиска | **Нет** (отключён через `_auto_grow_enabled=False`) |
| 6 | `flow_shapecontrol.py` | 85 | `rebuildHandles()` — после rebuild | **Да** |
| 7 | `flow_shapecontrol.py` | 123 | `mousePressEvent()` — начало drag | **Да** |
| 8 | `flow_shapecontrol.py` | 202 | `mouseMoveEvent()` — during drag | **Да** |
| 9 | `flow_shapecontrol.py` | 293 | `mouseReleaseEvent()` — end drag | **Да** |
| 10 | `textedit_commands.py` | 138 | `InsertTextCommand.redo()` | **Да** |
| 11 | `textedit_commands.py` | 151 | `InsertTextCommand.undo()` | **Да** |

### Важно: `set_size(auto_font_adjust=False)` НЕ вызывает `_update_flow_layout()`

```python
# flow_textitem.py:617-624
if self._left_points and self._right_points:
    if auto_font_adjust:
        self._update_flow_layout()
    else:
        pass  # Skip — boundaries setup and reLayout() will run later
```

---

## `_auto_font_adjust` — флаг управления shrink/grow

| Значение | Поведение | Когда |
|----------|-----------|-------|
| `True` | shrink/grow запускается | После создания блока, resize, handle drag |
| `False` | shrink/grow пропущен | Во время бинарного поиска, ручного изменения шрифта |

### Где сбрасывается в False:
- `setFontSize()` — при внешнем вызове (не `_internal_font_change`)
- `squeezeBoundingRect()` — временно

### Где восстанавливается в True:
- `_update_flow_layout()` line 486 — **всегда** после прохода shrink/grow
- `layout_textblk()` line 970 — после бинарного поиска
- `RunBlkTransCommand` line 149 — после бинарного поиска

---

## `_auto_grow_enabled` — флаг FontAutoAdjuster

| Значение | Поведение |
|----------|-----------|
| `True` | grow запускается если shrink не применился |
| `False` | grow никогда не запускается |

### КРИТИЧЕСКИ ВАЖНО: отключать grow после бинарного поиска!

Бинарный поиск (`_find_best_font_size`) находит оптимальный размер шрифта.
Grow pass УВЕЛИЧИВАЕТ шрифт после бинарного поиска, вызывая overflow.

**Оба места вызова `_update_flow_layout()` после бинарного поиска должны отключать grow:**

```python
# Вариант 1: drawing_commands.py (RunBlkTransCommand)
blkitem._auto_font_adjust = True
saved_grow = blkitem.font_adjuster._auto_grow_enabled
blkitem.font_adjuster._auto_grow_enabled = False
blkitem._update_flow_layout()
blkitem.font_adjuster._auto_grow_enabled = saved_grow

# Вариант 2: scenetext_manager.py (layout_textblk)
blkitem._auto_font_adjust = True
saved_grow = blkitem.font_adjuster._auto_grow_enabled
blkitem.font_adjuster._auto_grow_enabled = False
blkitem._update_flow_layout()
blkitem.font_adjuster._auto_grow_enabled = saved_grow
```

---

## `_update_flow_layout()` — что делает (пошагово)

1. **Re-entrancy guard**: `if self._updating_flow: return`
2. **Compute target dimensions** из control points (y-range → `target_height`, x-range → `target_width`)
3. **Set document margin** = `min_y` (чтобы текст начинался от верхней границы)
4. **Set max size** = `target_width + 2*min_y`, `target_height + 2*min_y`
5. **Set boundary functions** → `layout.set_boundary_functions(left_fn, right_fn)` → `reLayout()`
6. **Shrink pass**: `font_adjuster.shrink()` — уменьшает шрифт если текст выходит за границы
7. **Grow pass**: `font_adjuster.grow()` — увеличивает шрифт если текст заполняет < 70% высоты (ТОЛЬКО если `_auto_grow_enabled=True`)
8. **Reset** `_auto_font_adjust = True`

---

## Known Bugs и паттерны

### #1 КОРНЕВАЯ ПРИЧИНА ВСЕХ ПРОБЛЕМ: `reLayout()` расширяет `available_height`

**Это не баг, а фича движка, которую надо компенсировать.**

```python
# scene_textlayout.py:949-955
if new_height > self.available_height:
    self.max_height = new_height + doc_margin * 2
    self.available_height = new_height  # ← расширяет!
```

**Следствие**: После `setRelFontSize()` → `reLayoutEverything()` → `reLayout()`, constraint исчезает. Цикл shrink думает "всё влезает" и останавливается на первой итерации.

**Решение**: Всегда сбрасывать `layout.available_height` и `layout.max_height` до target значений ПОСЛЕ любого вызова, меняющего размер шрифта, ПЕРЕД чтением `shrink_height`.

### #2 Grow pass увеличивает шрифт после бинарного поиска

**Проблема**: Бинарный поиск находит оптимальный размер. Grow pass увеличивает его на ~8% (factor 1.08). `reLayout()` расширяет `available_height` до нового размера текста → overflow за границы блока.

**Решение**: Отключать `_auto_grow_enabled = False` перед `_update_flow_layout()` после бинарного поиска.

### #3 `set_size(auto_font_adjust=False)` вызывал `_update_flow_layout()`

**Проблема**: `set_size()` с `auto_font_adjust=False` всё равно вызывал `_update_flow_layout()`, который расширял `available_height` через `reLayout()`.

**Решение**: `set_size()` пропускает `_update_flow_layout()` когда `auto_font_adjust=False`.

### #4 `_auto_font_adjust` застряёт на False

**Проблема**: `setFontSize()` безусловно ставил `_auto_font_adjust = False`, даже при внутренних вызовах из shrink/grow.

**Решение**: Флаг `_internal_font_change` — `setFontSize()` сбрасывает `_auto_font_adjust` только при внешнем вызове.

### #5 Auto-shrink не работал (текст обрезался)

**Проблема**: `_auto_shrink_font()` не уменьшал шрифт достаточно, текст обрезался за пределами блока.

**Причина**: `setRelFontSize()` вызывал `reLayoutEverything()` → `reLayout()`, который расширял `available_height` при переполнении. После первого уменьшения шрифта, расширенный `available_height` делал `shrink_height` всегда ≤ `available_height`, и цикл завершался на первой итерации.

**Решение**: После `setRelFontSize()` сбрасываем `layout.available_height` и `layout.max_height` обратно к целевым значениям и вызываем `layout.reLayout()` принудительно перед проверкой `shrink_height`.

### #6 Верхний ромб меняет красную пунктирную рамку

**Проблема**: При перетаскивании верхнего ромбовидного хендла (ResizeHandle top) красная пунктирная рамка (`_draw_accessories`) меняла размер.

**Причина**: `boundingRect()` расширен за счёт `united(pts_rect)` (включает все контрольные точки). Когда верхний хендл двигал левую/правую верхнюю точку, `boundingRect()` расширялся, и рамка растягивалась.

**Решение**: `FlowTextBlkItem._draw_accessories()` — override, который рисует `background_pixmap` как обычно, но подавляет отрисовку пунктирной рамки, когда `under_ctrl=True`.

---

## Бинарный поиск `_find_best_font_size()`

`scenetext_manager.py:1068` — ищет максимальный размер шрифта, при котором текст помещается в `target_w × target_h`.

### Алгоритм:
1. `lo = max(LAYOUT_MIN_FONT_PT, 4.0)`, `hi = max(original_size * 3.0, 120.0)`
2. Подавляет `repaint_on_changed` и `blockSignals(True)`
3. Сохраняет `orig_avail_h` и `orig_max_h` (сбрасывает перед каждой итерацией!)
4. До 30 итераций:
   - `mid = (lo + hi) / 2`
   - Сбрасывает `available_height` и `max_height`
   - `setFontSize(mid)` → `setPlainText(text)` → `set_size(w, h, auto_font_adjust=False)`
   - Читает `shrink_height` → сравнивает с `target_h`
   - `fits` → `lo = mid`, иначе `hi = mid`
5. Восстанавливает `blockSignals(False)` и `repaint_on_changed`

---

## Ключевые особенности

1. 6 контрольных точек (3 слева + 3 справа) для изогнутых границ
2. Quadratic Bezier — кривая проходит через ВСЕ 3 точки (не только крайние)
3. Per-line интерполяция — каждая строка текста подстраивается под границы
4. Перетаскивание хендлов — обновление layout'а в реальном времени
5. Resize сверху/снизу — сдвиг всей верхней/нижней границы
6. Добавление/удаление точек через контекстное меню
7. Hover-подсветка границ (только при наведении или выборе)
8. `draw_boundaries=False` — подавление границ в экспортированном изображении
9. Сериализация в `TextBlock.left_points/right_points`
10. `_auto_shrink_font()` — итеративное уменьшение шрифта при переполнении
11. `_auto_grow_font()` — итеративное увеличение шрифта при пустом месте
12. `_draw_accessories()` — подавление пунктирной рамки при `under_ctrl`

---

## LOG_PREFIXES — фильтрация логов

Определено в `utils/shared.py`:
```python
LOG_PREFIXES = ("ВПЕРЁД!",)
```

Используется в:
- `flow_textitem.py` — `_log()` фильтрует DEBUG логи
- `scene_textlayout.py` — `reLayout()` expanding логи

### Поведение:
- `QUIET_UI = True` → все DEBUG логи подавлены
- `QUIET_UI = False` → DEBUG логи только для блоков с префиксом из `LOG_PREFIXES`
- INFO/WARNING/ERROR → всегда логируются

### Для смены префикса:
Менять только `LOG_PREFIXES` в `utils/shared.py`.

---

## Как можно было решить быстрее (retrospective)

1. Первым делом прочитать **SceneTextLayout.reLayout()** и понять, что он модифицирует `available_height`. Это единственная причина всех проблем.
2. Сразу спроектировать `_auto_grow_font` вместе с `_auto_shrink_font` — они симметричны и используют одни и те же механизмы.
3. Всегда делать reset constraints после любого вызова `setRelFontSize` или `setFontSize` перед чтением `shrink_height`.

---

## Тестирование

```bash
# Все тесты flow text
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py -v

# Конкретный тест
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py::TestAutoShrink -v

# Все UI тесты
myenv\Scripts\python -m pytest tests/ui/ -v

# Полный набор
myenv\Scripts\python -m pytest -v
```

### Тесты покрывают:
- `TestFlowTextBlkInit` — создание, control points
- `TestFlowBoundaryLayout` — reflow при изменении границ
- `TestAutoShrink` — shrink при overflow
- `TestAutoGrow` — grow при small text
- `TestShrinkGrowSymmetry` — стабильность после shrink+grow
- `TestBinarySearchFontSizing` — бинарный поиск шрифта
- `TestAutoFontAdjustFlag` — поведение флага `_auto_font_adjust`
- `TestBlockResizeShrinkGrow` — resize → shrink/grow
- `TestEmptyBlockNoGrow` — grow пропускается для пустых блоков
- `TestUndoFontRestore` — undo восстанавливает шрифт
- `TestAutoAdjustReset` — флаг сбрасывается после update_flow_layout
- `TestFontPanelAfterResize` — sync шрифта после resize
