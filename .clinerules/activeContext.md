# Active Context

## Current Work Focus
FlowTextBlkItem is feature-complete. Hyphenation via pyphen (Cyrillic + Latin) added with `_has_char_level_breaks` detection to trigger font shrinking when words break at character boundaries even without vertical overflow.

## Recent Changes
- **Bug 1 — vertical mode text alignment**: Added `FlowTextBlkItem.setVertical()` override that resets flow control points to a rectangle from `absBoundingRect()` before switching layout engines. `FlowShapeControl._is_vertical()` / `_flow_handles_visible()` hide flow handles in vertical mode.
- **Bug 2 — text clipping instead of font shrinking**: Added `FlowTextBlkItem._auto_shrink_font()` — iterative font reduction loop called from `_update_flow_layout()`. Reduces font by `FONT_SHRINK_FACTOR` (0.9) per iteration until text fits or 5pt minimum. Max 20 iterations.
- **Bug 3 — red dashed border changes size with top rhombus**: Added `_draw_accessories()` override that suppresses border when `under_ctrl=True`. Flow boundary curves already indicate text area.
- **Bug 4 — auto-shrink didn't work**: Fixed by resetting `layout.available_height` and `layout.max_height` to target values after `setRelFontSize()`, then forcing `layout.reLayout()` before reading `shrink_height`. Root cause: `SceneTextLayout.reLayout()` expands `available_height` on overflow.
- **Feature — auto-grow font to fill block**: Added `_auto_grow_font()` — called after `_auto_shrink_font()` in `_update_flow_layout()`. If text fills <70% of block height, font is iteratively increased to ~90% fill.
- **Bug 5 — NameError in _draw_accessories**: Added `from .textitem import TEXTRECT_SHOW_COLOR, TEXTRECT_SELECTED_COLOR` to fix crash on paint.
- **Bug 6 — global font size disables grow**: Added `_auto_grow_enabled` flag, checked in `_update_flow_layout()`. Set False when global font size is used.
- **Tests — 25 unit tests**: `tests/ui/test_flow_textitem.py` — init, boundary layout, auto-shrink, auto-grow, symmetry, paint, hyphenation (25/25 passed).
- **Hyphenation + char-level break detection**: Added `_hyphenate_text()` using pyphen (ru_RU for Cyrillic, en_US for Latin) with soft hyphens. Added `_has_char_level_breaks` flag to `HorizontalTextDocumentLayout` — set when layout breaks a word at a character boundary (not soft-hyphen/space). `_auto_shrink_font()` now triggers on char-level breaks even without vertical overflow, shrinking font until words fit properly at hyphenation boundaries.
- **bug 8e01f1b5**: QAction parent fix for context menu (previous)
- **bug — handle positioning**: inv_scale compensation for baseLayer transform (previous)

## Critical Lesson — SceneTextLayout.reLayout() modifies available_height
This is the SINGLE most important thing to know when working with auto-sizing fonts:
- `SceneTextLayout.reLayout()` expands `self.available_height = new_height` when text overflows (line 943)
- After `setRelFontSize()` → `reLayoutEverything()` → `reLayout()`, the constraint is gone
- **Always reset** `layout.available_height` and `layout.max_height` to target values AFTER any font-size-change call, before reading `shrink_height`

## Next Steps
1. Production testing: verify FlowTextBlkItem with both horizontal (trapezoid) and vertical text modes
2. Verify hyphenation + shrink interaction: narrow boxes should syllable-break first, shrink only when necessary
3. Verify font auto-shrink/grow when dragging resize handles to make box very small or very large
4. Verify context menu works on all item types (FlowTextBlkItem, FlowControlHandle, TextBlkItem)

## Active Decisions
- `handleContextMenu()` в FlowShapeControl — единая точка входа для всех правых кликов в textEditMode.
- FlowShapeControl заменяет TextBlkShapeControl полностью, а не наследует его.
- Duck-typing через hasattr для совместимости с существующим кодом (scenetext_manager, textedit_commands).
- `_auto_shrink_font()` + `_auto_grow_font()` — симметричная пара: shrink при overflow, grow при пустом месте.
- `_draw_accessories()` — override для подавления пунктирной рамки при active flow handles.
- Дефисация через pyphen + `_has_char_level_breaks` — двухуровневая стратегия: сначала разбить слова по слогам, если не помогает — уменьшить шрифт.
- `setHtml()`, `setPlainText()`, `setPlainTextAndKeepUndoStack()` — все override'ы FlowTextBlkItem применяют дефисацию перед передачей текста в layout.

## Important Patterns
- Всегда создавать QAction с parent (обычно parent=menu) при использовании insertAction в PyQt6.
- `QAction(parent)` — parent обязателен для корректного рендеринга при insertAction/insertMenu.
- При установке позиции дочерних элементов FlowShapeControl через `mapToScene()` необходимо компенсировать масштаб baseLayer. Использовать `inv_scale = 1.0 / topLevelItem().scale()`.
- `_flow_handles_visible()` — централизованная проверка видимости flow-handles (учитывает вертикальный режим и редактирование).
- `SceneTextLayout.reLayout()` расширяет `available_height` при overflow — всегда компенсировать это в циклах авторазмера.
- `_has_char_level_breaks` — флаг в `HorizontalTextDocumentLayout`, устанавливается в `True` при посимвольном разрыве слова (не по пробелу и не по мягкому дефису). Используется в `_auto_shrink_font()` как триггер уменьшения шрифта даже при отсутствии вертикального overflow.
- `_hyphenate_text()` — утилита для вставки мягких дефисов между слогов. Поддерживает кириллицу (ru_RU) и латиницу (en_US). Минимальная длина слова для дефисации — 5 символов.