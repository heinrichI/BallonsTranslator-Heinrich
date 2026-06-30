# Progress

## What Works
- FlowTextBlkItem creation from rectangular blocks
- 3+3 control points (left/right boundaries) with drag handles
- Quadratic Bezier curve rendering through all 3 points
- Per-line interpolation for text layout
- Real-time layout update when dragging handles
- Resize handles (top/bottom) that shift entire boundaries
- Boundary overlay suppression in exported images (draw_boundaries=False)
- Serialization of control points to TextBlock.left_points/right_points
- Hover highlight of boundary curves
- Context menu with combined flow items + standard items (fixed in commit 8e01f1b5)
- **Vertical mode**: flow control points reset to rectangle, flow handles hidden, text renders correctly (Bug 1 fixed)
- **Font auto-shrink**: iterative font reduction when bounding box is too small, down to 5pt minimum (Bug 2 fixed)
- **_display_rect guard clause**: prevents zero-width/height crash when control points form a degenerate rectangle (regression fix)
- **Font auto-grow**: iterative font increase when text fills <70% of block height, up to ~90% fill (Feature)
- **Border suppress**: red dashed border suppressed when active flow handles visible (Bug 3 fixed)
- **NameError fix**: TEXTRECT_SELECTED_COLOR/SHOW_COLOR imported in flow_textitem.py (Bug 5)
- **Global font size guard**: _auto_grow_enabled flag disables grow when global font size active (Bug 6)
- **Hyphenation**: long words split by syllables via pyphen (Cyrillic ru_RU + Latin en_US) with soft hyphens
- **Char-level break detection**: _has_char_level_breaks flag triggers font shrink when words break at character boundaries, even without vertical overflow
- **25 unit tests**: tests/ui/test_flow_textitem.py covering init, boundary, shrink, grow, symmetry, paint, hyphenation
- HF ogkalu detector integrated and auto-registered as `comic-text-and-bubble-detector`.
- CTD-based refinemask integration in detectors: `refine_mask(img, coarse_mask, blk_list)` returns per-character masks when blk_list aligns to text lines.
- Debug tooling: scripts to run detector and compare masks.
- Russian comments added to CTD detector and CTD basemodel/inference files for maintainability.

## What's Left
- Split large merged blocks into lines before calling `refine_mask` to obtain character-level masks instead of block masks.
- Unit tests to cover HF parsing helpers and large-block split logic.
- UI exposure: surface `box_padding` and `mask dilate size` more prominently and consider safer defaults (0/0) for new users.
- Documentation: update doc/modules and CHANGELOG with the detector changes.
## What's Left to Build
- [x] Initial FlowTextBlkItem implementation with control points
- [x] FlowShapeControl with drag handles
- [x] Integration with canvas (scale, render, right-click delegation)
- [x] Context menu merging (flow items + standard items)
- [x] Vertical mode text alignment (setVertical override + flow handle visibility)
- [x] Font auto-shrink on overflow (_auto_shrink_font in _update_flow_layout)
- [x] Font auto-grow to fill block (_auto_grow_font in _update_flow_layout)
- [x] _display_rect guard against zero width/height
- [x] Red dashed border not changing size with top rhombus (_draw_accessories override)
- [x] Hyphenation via pyphen (Cyrillic + Latin) with soft hyphens
- [x] Char-level break detection (_has_char_level_breaks flag)
- [x] Trigger font shrink on char-level breaks even without vertical overflow
- [ ] Production testing — verify context menu works correctly on all item types
- [ ] Potential edge case: very small blocks where control points overlap
- [ ] Potential edge case: re-initializing points from degenerate rectangles

## Current Status
All known issues (vertical mode alignment, text clipping, _display_rect regression, border resize, auto-grow) are fixed. Hyphenation + char-level break detection added. FlowTextBlkItem is feature-complete and ready for testing.

## Known Issues
- None currently open.
- Implemented defensive parsing, padding/clamping, merge protection.
- Added debug scripts and mask diagnostics.
- Added localised comments in CTD-related modules.

## Evolution of Project Decisions
1. Initially `showFlowContextMenu()` in FlowTextBlkItem was called directly from canvas via `isinstance()` check
2. Changed to `handleContextMenu()` in FlowShapeControl as single entry point
3. Fixed QAction parent issue — PyQt6 requires parent for insertAction to work
4. Removed direct isinstance check from canvas — handleContextMenu now routes internally
5. Added `_auto_shrink_font()` — one-directional font reduction (does not increase on box expand)
6. Added setVertical() override — resets flow points to rectangle on orientation change
7. Centralized flow handle visibility in `_flow_handles_visible()` — checks vertical mode + editing state
8. Added _display_rect guard clause — returns a small default rectangle when control points produce zero width or height
9. Changed `_auto_shrink_font()` to reset layout constraints after setRelFontSize (Bug 4 fix)
10. Added `_auto_grow_font()` — symmetric counterpart to _auto_shrink_font (Feature)
11. Added `_draw_accessories()` override — suppress border when under_ctrl (Bug 3 fix)
12. Added `_auto_grow_enabled` flag — disabled when global font size setting active (Bug 6)
13. Imported TEXTRECT_SHOW_COLOR/TEXTRECT_SELECTED_COLOR — fix NameError in _draw_accessories (Bug 5)
14. Added 16 pytest unit tests in tests/ui/test_flow_textitem.py
15. Added `_hyphenate_text()` using pyphen (ru_RU + en_US) with soft hyphens — words split by syllables before passing to layout engine
16. Added `_has_char_level_breaks` flag to `HorizontalTextDocumentLayout` — set when layout breaks a word at a character boundary (not soft-hyphen/space)
17. Updated `_auto_shrink_font()` to trigger on char-level breaks even without vertical overflow — two-stage strategy: hyphenation first, then shrink if needed
18. Expanded test suite to 25 tests — added 9 hyphenation tests
19. Overrode `setHtml()` and `setPlainTextAndKeepUndoStack()` to apply hyphenation before passing text to layout
## Next Milestones
- [ ] Implement splitting of oversized merged blocks into lines and re-run diagnostics.
- [ ] Add unit tests for `_safe_box_from_item` and split logic.
- [ ] Manual UI verification with multiple comic pages.
- [ ] Update doc/modules and CHANGELOG.