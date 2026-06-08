# Active Context

## Current Work Focus
Завершение реализации FlowTextBlkItem — изогнутые текстовые блоки с перетаскиваемыми контрольными точками границ.

## Recent Changes
- **bug 8e01f1b5**: При добавлении пунктов "Добавить точку к левой/правой стороне" в контекстное меню, стандартные пункты (Copy, Paste, Delete, etc.) пропадали.
- **Причина**: PyQt6 требует, чтобы QAction имел parent при вставке через `insertAction`. В `FlowTextBlkItem.showFlowContextMenu()` action'ы создавались без parent'а, и PyQt6 не отображал их при insertAction.
- **Исправление**: В `flow_textitem.py` — добавлен `parent=menu` для всех action'ов. В `canvas.py` — убрана прямая проверка `isinstance(FlowTextBlkItem)`, теперь `handleContextMenu()` сам определяет тип.

## Next Steps
1. Протестировать контекстное меню на FlowTextBlkItem — должны быть все 16 стандартных пунктов + "Добавить точку к левой стороне" + "Добавить точку к правой стороне"
2. Протестировать контекстное меню на FlowControlHandle — должно быть "Удалить точку"
3. Протестировать контекстное меню на обычном TextBlkItem — стандартное меню без изменений

## Active Decisions
- `handleContextMenu()` в FlowShapeControl — единая точка входа для всех правых кликов в textEditMode.
- FlowShapeControl заменяет TextBlkShapeControl полностью, а не наследует его.
- Duck-typing через hasattr для совместимости с существующим кодом (scenetext_manager, textedit_commands).

## Important Patterns
- Всегда создавать QAction с parent (обычно parent=menu) при использовании insertAction в PyQt6.
- `QAction(parent)` — parent обязателен для корректного рендеринга при insertAction/insertMenu.