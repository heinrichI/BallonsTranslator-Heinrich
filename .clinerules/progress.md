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

## What's Left to Build
- [x] Initial FlowTextBlkItem implementation with control points
- [x] FlowShapeControl with drag handles
- [x] Integration with canvas (scale, render, right-click delegation)
- [x] Context menu merging (flow items + standard items)
- [ ] Production testing — verify context menu works correctly on all item types
- [ ] Potential edge case: very small blocks where control points overlap
- [ ] Potential edge case: re-initializing points from degenerate rectangles

## Current Status
Context menu bug (8e01f1b5) is fixed. FlowTextBlkItem is feature-complete and ready for testing.

## Known Issues
- None currently open. Previous issue: standard context menu items disappeared when flow items were added (fixed).

## Evolution of Project Decisions
1. Initially `showFlowContextMenu()` in FlowTextBlkItem was called directly from canvas via `isinstance()` check
2. Changed to `handleContextMenu()` in FlowShapeControl as single entry point
3. Fixed QAction parent issue — PyQt6 requires parent for insertAction to work
4. Removed direct isinstance check from canvas — handleContextMenu now routes internally