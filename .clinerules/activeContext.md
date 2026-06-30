# Active Context

## Current Work Focus
FlowTextBlkItem is feature-complete. Hyphenation via pyphen (Cyrillic + Latin) added with `_has_char_level_breaks` detection to trigger font shrinking when words break at character boundaries even without vertical overflow.
Integrating and hardening the ogkalu/comic-text-and-bubble-detector HF object-detection detector and improving CTD-based pixel-level text segmentation pipeline.

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
- Implemented `modules/textdetector/detector_comic-text-and-bubble-detector.py` improvements:
  - Defensive parsing helpers: `_validate_detection_item(item)` and `_safe_box_from_item(item, img_w, img_h)`.
  - Safe box expansion: `_expand_blocks` now caps per-block padding to 15% of block height.
  - Merge protection: `_merge_overlapping_blocks` accepts `max_area` and skips merges that would exceed 20% of page area.
  - Default parameter adjustments: `"box_padding"` default reduced to 1, `"mask dilate size"` default reduced to 1.
  - Debug dump support added (hf_results_{ts}.json, mask_pre_refine_{ts}.png, mask_post_refine_{ts}.png).
- Added helper/debug scripts:
  - `scripts/debug_run_detector_params.py` — run detector with pad/dilate/no_merge options and save dumps.
  - `scripts/count_debug_masks.py` — compute nonzero pixels for mask_*.png files.
  - `scripts/debug_run_detector.py` — single-image debug runner.
- CTD-related files commented in Russian for clarity:
  - `modules/textdetector/detector_ctd.py` — russian comments added.
  - `modules/textdetector/ctd/basemodel.py` — russian comments added.
  - `modules/textdetector/ctd/inference.py` — russian comments added.
- Small unit helper added: `tests/smoke_detector_hf_helpers.py` (sanity for box parsing).

## Next Steps
1. Production testing: verify FlowTextBlkItem with both horizontal (trapezoid) and vertical text modes
2. Verify hyphenation + shrink interaction: narrow boxes should syllable-break first, shrink only when necessary
3. Verify font auto-shrink/grow when dragging resize handles to make box very small or very large
4. Verify context menu works on all item types (FlowTextBlkItem, FlowControlHandle, TextBlkItem)
- Finalize splitting large merged blocks into text-lines before calling `refine_mask` (to get per-character masks instead of block masks).
- Run manual UI verification across multiple comic pages.
- Consider lowering defaults to pad=0 / dilate=0 in release or expose clearly in UI.
- Update docs (doc/modules or CHANGELOG) describing new detector behavior and required HF model.

## Active Decisions
- `handleContextMenu()` в FlowShapeControl — единая точка входа для всех правых кликов в textEditMode.
- FlowShapeControl заменяет TextBlkShapeControl полностью, а не наследует его.
- Duck-typing через hasattr для совместимости с существующим кодом (scenetext_manager, textedit_commands).
- `_auto_shrink_font()` + `_auto_grow_font()` — симметричная пара: shrink при overflow, grow при пустом месте.
- `_draw_accessories()` — override для подавления пунктирной рамки при active flow handles.
- Дефисация через pyphen + `_has_char_level_breaks` — двухуровневая стратегия: сначала разбить слова по слогам, если не помогает — уменьшить шрифт.
- `setHtml()`, `setPlainText()`, `setPlainTextAndKeepUndoStack()` — все override'ы FlowTextBlkItem применяют дефисацию перед передачей текста в layout.
## Active Decisions and Considerations
- Use HF `pipeline("object-detection")` for ogkalu model; skip detections labeled `bubble`.
- Treat `text_bubble` and `text_free` as text regions.
- Apply CTD.pixel-level `refine_mask(img, mask, blk_list)` after drawing coarse polygon masks.
- Avoid producing huge merged boxes — cap merge by page-area threshold (0.2).
- Limit per-block padding to a fraction of block height (0.15) to avoid background inclusion.

## Important Patterns
- Всегда создавать QAction с parent (обычно parent=menu) при использовании insertAction в PyQt6.
- `QAction(parent)` — parent обязателен для корректного рендеринга при insertAction/insertMenu.
- При установке позиции дочерних элементов FlowShapeControl через `mapToScene()` необходимо компенсировать масштаб baseLayer. Использовать `inv_scale = 1.0 / topLevelItem().scale()`.
- `_flow_handles_visible()` — централизованная проверка видимости flow-handles (учитывает вертикальный режим и редактирование).
- `SceneTextLayout.reLayout()` расширяет `available_height` при overflow — всегда компенсировать это в циклах авторазмера.
- `_has_char_level_breaks` — флаг в `HorizontalTextDocumentLayout`, устанавливается в `True` при посимвольном разрыве слова (не по пробелу и не по мягкому дефису). Используется в `_auto_shrink_font()` как триггер уменьшения шрифта даже при отсутствии вертикального overflow.
- `_hyphenate_text()` — утилита для вставки мягких дефисов между слогов. Поддерживает кириллицу (ru_RU) и латиницу (en_US). Минимальная длина слова для дефисации — 5 символов.
## How to run (examples)
- Launch app (recommended venv):
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py
- Debug detector on single image:
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" scripts/debug_run_detector_params.py "path\to\img.jpg" debug_dump 0 0
- Count debug masks:
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" scripts/count_debug_masks.py