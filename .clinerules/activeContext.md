# Active Context

## Current Work Focus
Завершение реализации FlowTextBlkItem — изогнутые текстовые блоки с перетаскиваемыми контрольными точками границ.

## Recent Changes
- **bug 8e01f1b5**: При добавлении пунктов "Добавить точку к левой/правой стороне" в контекстное меню, стандартные пункты (Copy, Paste, Delete, etc.) пропадали.
- **Причина**: PyQt6 требует, чтобы QAction имел parent при вставке через `insertAction`. В `FlowTextBlkItem.showFlowContextMenu()` action'ы создавались без parent'а, и PyQt6 не отображал их при insertAction.
- **Исправление**: В `flow_textitem.py` — добавлен `parent=menu` для всех action'ов. В `canvas.py` — убрана прямая проверка `isinstance(FlowTextBlkItem)`, теперь `handleContextMenu()` сам определяет тип.
- **bug — handle'ы в левом верхнем углу после нового распознавания**: При клике на текстовый блок после пересоздания сцены handle'ы управления отображались в левом верхнем углу страницы, вместо позиции блока.
- **Причина**: `FlowShapeControl` — дочерний элемент `baseLayer`, у которого может быть `scale != 1.0`. `updateHandlePositions()` вызывал `blk_item.mapToScene(pt)`, возвращавший координаты в scene-пространстве, уже включающие масштаб baseLayer. Затем `handle.setPos(scene_pos)` устанавливал позицию handle в родительских координатах FlowShapeControl, который сам находится под baseLayer, — происходило двойное масштабирование.
- **Исправление**: В `updateHandlePositions()` добавлен расчёт `inv_scale = 1.0 / baseLayer.scale()`. `handle.setPos()` теперь использует `parent_pos = scene_pos * inv_scale`, компенсируя двойное масштабирование. Исправлены также `top_handle` и `bottom_handle`.

## Next Steps
1. Проверить, что handle'ы отображаются на правильных позициях при любом zoom-уровне (scale factor).
2. Протестировать контекстное меню на FlowTextBlkItem — должны быть все 16 стандартных пунктов + "Добавить точку к левой стороне" + "Добавить точку к правой стороне"
3. Протестировать контекстное меню на FlowControlHandle — должно быть "Удалить точку"
4. Протестировать контекстное меню на обычном TextBlkItem — стандартное меню без изменений

## Active Decisions
- `handleContextMenu()` в FlowShapeControl — единая точка входа для всех правых кликов в textEditMode.
- FlowShapeControl заменяет TextBlkShapeControl полностью, а не наследует его.
- Duck-typing через hasattr для совместимости с существующим кодом (scenetext_manager, textedit_commands).

## Important Patterns
- Всегда создавать QAction с parent (обычно parent=menu) при использовании insertAction в PyQt6.
- `QAction(parent)` — parent обязателен для корректного рендеринга при insertAction/insertMenu.
- При установке позиции дочерних элементов FlowShapeControl через `mapToScene()` необходимо компенсировать масштаб baseLayer, так как FlowShapeControl находится под baseLayer. Использовать `inv_scale = 1.0 / topLevelItem().scale()`.
