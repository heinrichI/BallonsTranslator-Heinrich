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
- **16 unit tests**: tests/ui/test_flow_textitem.py covering init, boundary, shrink, grow, symmetry, paint

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
- [ ] Production testing — verify context menu works correctly on all item types
- [ ] Potential edge case: very small blocks where control points overlap
- [ ] Potential edge case: re-initializing points from degenerate rectangles

## Current Status
All known issues (vertical mode alignment, text clipping, _display_rect regression, border resize, auto-grow) are fixed. FlowTextBlkItem is feature-complete and ready for testing.

## Known Issues
- None currently open.

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
