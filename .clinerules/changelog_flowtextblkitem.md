# FlowTextBlkItem — Изогнутые текстовые блоки

## Описание
Добавление поддержки изогнутых/трапециевидных текстовых блоков с перетаскиваемыми контрольными точками границ.

## Ветка
`FlowTextBlkItem-Cline-claude2`

## Новые файлы

### ui/flow_textitem.py (339 строк)
- `FlowTextBlkItem(TextBlkItem)` — изогнутые текстовые блоки
  - 3+3 контрольные точки границ (левая/правая сторона)
  - `interpolate_boundary()` — линейная интерполяция между точками
  - `build_quad_path()` — квадратичный Bezier через 3 точки
  - `_init_points_from_rect()`, `_get_line_x_offsets()`, `_update_flow_layout()`
  - `save_flow_points()` — сериализация в TextBlock
  - Переопределения `set_size/on_document_enlarged/docSizeChanged` — pos() не сдвигается
  - `boundingRect()` — включает все контрольные точки
  - Hover-отрисовка границ, контекстное меню для добавления точек

### ui/flow_shapecontrol.py (466 строк)
- `FlowShapeControl(QGraphicsItem)` — замена TextBlkShapeControl для FlowTextBlkItem
  - Public API совместим с TextBlkShapeControl
  - `handleContextMenu()` — инкапсуляция правого клика
  - `FlowControlHandle` — 6 перетаскиваемых кругов (3 слева + 3 справа)
  - `FlowResizeHandle` — 2 ромбовидных хендла для высоты
  - `_NullPixmapItem` — заглушка previewPixmap

## Изменённые файлы

### ui/canvas.py (5 мест)
- import FlowShapeControl (вместо TextBlkShapeControl)
- init, scale, render (draw_boundaries=False), делегирование правого клика

### ui/scene_textlayout.py (3 места)
- `_line_left_offsets`, `_line_right_offsets` — per-line смещения
- `set_line_x_offsets()` — установка и relayout
- `layoutBlock()` — динамическая ширина строк

## Исправления

### 2026-06-08 — commit 8e01f1b5 — контекстное меню: стандартные пункты пропадали
- **Проблема**: При добавлении пунктов "Добавить точку к левой/правой стороне" в контекстное меню FlowTextBlkItem, стандартные пункты (Copy, Paste, Delete и др.) переставали отображаться.
- **Причина**: PyQt6 требует, чтобы QAction имел parent при вставке через `insertAction`. В showFlowContextMenu() action'ы создавались без parent'а.
- **Исправление**:
  * flow_textitem.py — добавлен `parent=menu` для всех action'ов
  * canvas.py — убрана прямая проверка isinstance(FlowTextBlkItem), теперь handleContextMenu() сам определяет тип и маршрутизирует
- **Статус**: Исправлено

### 2026-06-10 — handle'ы в левом верхнем углу после нового распознавания
- **Проблема**: При клике на текстовый блок после пересоздания сцены (новое распознавание) handle'ы управления отображались в левом верхнем углу страницы, а не на позиции блока.
- **Причина**: `FlowShapeControl` — дочерний элемент `baseLayer`, у которого может быть `scale != 1.0` (zoom-уровень). `updateHandlePositions()` вызывал `blk_item.mapToScene(pt)`, возвращавший координаты в scene-пространстве, уже включающие масштаб baseLayer. Затем `handle.setPos(scene_pos)` устанавливал позицию handle в родительских координатах `FlowShapeControl`, который сам находится под `baseLayer`. Происходило **двойное масштабирование**: scene-координаты (уже scaled) применялись как родительские координаты (которые baseLayer снова умножает на scale).
- **Исправление**:
  * `flow_shapecontrol.py` — в `updateHandlePositions()` добавлен расчёт `inv_scale = 1.0 / topLevelItem().scale()`. Позиция handle теперь устанавливается как `parent_pos = scene_pos * inv_scale`, что компенсирует двойное масштабирование.
  * Аналогично исправлены `top_handle` и `bottom_handle`.
- **Статус**: Исправлено

### 2026-06-10 — Bug 1: Вертикальный режим — текст сдвигается к правому краю
- **Проблема**: В вертикальном режиме весь текст FlowTextBlkItem отображается у правого края красного bounding box, игнорируя flow-точки.
- **Причина**: `_get_line_x_offsets()` возвращает пустые словари для `VerticalTextDocumentLayout`. Layout использует `block_ideal_width` (макс. ширина символа) между doc margins, что сдвигает весь текст к правому краю.
- **Исправление**: `setVertical()` в `FlowTextBlkItem` теперь сбрасывает flow-точки в прямоугольник из `absBoundingRect()` перед вызовом `super().setVertical()`. При переключении обратно на горизонтальный режим — тоже сбрасывает.
- **Изменённые файлы**:
  * `ui/flow_textitem.py` — новый override `setVertical(vertical)`
  * `ui/flow_shapecontrol.py` — `_is_vertical()`, `_flow_handles_visible()` скрывают flow-handles в вертикальном режиме
- **Статус**: Исправлено

### 2026-06-10 — Bug 2: Текст обрезается вместо уменьшения шрифта
- **Проблема**: Если bounding box слишком мал, текст обрезается за его пределами, вместо того чтобы шрифт уменьшился.
- **Причина**: В `HorizontalTextDocumentLayout.reLayout()` нет механизма уменьшения шрифта при превышении `available_height`.
- **Исправление**: Добавлен `_auto_shrink_font()` в `FlowTextBlkItem`, вызываемый из `_update_flow_layout()`. Алгоритм: после layout, если `shrink_height > available_height`, итеративно уменьшает шрифт на `FONT_SHRINK_FACTOR` (0.9) с запасом 5%, пока текст не поместится или не достигнет `MIN_FONT_SIZE_PT` (5pt). Максимум 20 итераций.
- **Изменённые файлы**:
  * `ui/flow_textitem.py` — новые константы `MIN_FONT_SIZE_PT`, `FONT_SHRINK_FACTOR`, метод `_auto_shrink_font()`
- **Статус**: Исправлено

## Ключевые особенности (дополнение)
10. `_auto_shrink_font()` — итеративное уменьшение шрифта при переполнении
11. `setVertical()` — сброс flow-точек в прямоугольник при смене ориентации
12. `_is_vertical()` / `_flow_handles_visible()` — скрытие flow-handles в вертикальном режиме

## Не тронуты (duck-typing / hasattr)
scenetext_manager.py, textedit_commands.py, texteditshapecontrol.py, textitem.py, utils/textblock.py

## Ключевые особенности
1. 6 контрольных точек (3 слева + 3 справа)
2. Quadratic Bezier через все 3 точки
3. Per-line интерполяция для layout
4. Перетаскиваемые хендлы с обновлением в реальном времени
5. Resize сверху/снизу
6. Добавление/удаление точек через контекстное меню
7. Hover-подсветка границ
8. draw_boundaries=False для экспорта
9. Сериализация в TextBlock