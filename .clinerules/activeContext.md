# Active Context

## Current Work Focus
FlowTextBlkItem is feature-complete. All known issues fixed: vertical mode, text clipping, border resize, and font auto-grow.

## Recent Changes
- **Bug 1 — vertical mode text alignment**: Added `FlowTextBlkItem.setVertical()` override that resets flow control points to a rectangle from `absBoundingRect()` before switching layout engines. `FlowShapeControl._is_vertical()` / `_flow_handles_visible()` hide flow handles in vertical mode.
- **Bug 2 — text clipping instead of font shrinking**: Added `FlowTextBlkItem._auto_shrink_font()` — iterative font reduction loop called from `_update_flow_layout()`. Reduces font by `FONT_SHRINK_FACTOR` (0.9) per iteration until text fits or 5pt minimum. Max 20 iterations.
- **Bug 3 — red dashed border changes size with top rhombus**: Added `_draw_accessories()` override that suppresses border when `under_ctrl=True`. Flow boundary curves already indicate text area.
- **Bug 4 — auto-shrink didn't work**: Fixed by resetting `layout.available_height` and `layout.max_height` to target values after `setRelFontSize()`, then forcing `layout.reLayout()` before reading `shrink_height`. Root cause: `SceneTextLayout.reLayout()` expands `available_height` on overflow.
- **Feature — auto-grow font to fill block**: Added `_auto_grow_font()` — called after `_auto_shrink_font()` in `_update_flow_layout()`. If text fills <70% of block height, font is iteratively increased to ~90% fill.
- **bug 8e01f1b5**: QAction parent fix for context menu (previous)
- **bug — handle positioning**: inv_scale compensation for baseLayer transform (previous)

## Critical Lesson — SceneTextLayout.reLayout() modifies available_height
This is the SINGLE most important thing to know when working with auto-sizing fonts:
- `SceneTextLayout.reLayout()` expands `self.available_height = new_height` when text overflows (line 943)
- After `setRelFontSize()` → `reLayoutEverything()` → `reLayout()`, the constraint is gone
- **Always reset** `layout.available_height` and `layout.max_height` to target values AFTER any font-size-change call, before reading `shrink_height`

## Next Steps
1. Production testing: verify FlowTextBlkItem with both horizontal (trapezoid) and vertical text modes
2. Verify font auto-shrink/grow when dragging resize handles to make box very small or very large
3. Verify context menu works on all item types (FlowTextBlkItem, FlowControlHandle, TextBlkItem)

## Active Decisions
- `handleContextMenu()` в FlowShapeControl — единая точка входа для всех правых кликов в textEditMode.
- FlowShapeControl заменяет TextBlkShapeControl полностью, а не наследует его.
- Duck-typing через hasattr для совместимости с существующим кодом (scenetext_manager, textedit_commands).
- `_auto_shrink_font()` + `_auto_grow_font()` — симметричная пара: shrink при overflow, grow при пустом месте.
- `_draw_accessories()` — override для подавления пунктирной рамки при active flow handles.

## Important Patterns
- Всегда создавать QAction с parent (обычно parent=menu) при использовании insertAction в PyQt6.
- `QAction(parent)` — parent обязателен для корректного рендеринга при insertAction/insertMenu.
- При установке позиции дочерних элементов FlowShapeControl через `mapToScene()` необходимо компенсировать масштаб baseLayer. Использовать `inv_scale = 1.0 / topLevelItem().scale()`.
- `_flow_handles_visible()` — централизованная проверка видимости flow-handles (учитывает вертикальный режим и редактирование).
- `SceneTextLayout.reLayout()` расширяет `available_height` при overflow — всегда компенсировать это в циклах авторазмера.
