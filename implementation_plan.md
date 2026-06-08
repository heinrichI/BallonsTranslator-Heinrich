# Implementation Plan

## [Overview]

Restore the combined context menu for FlowTextBlkItem that was lost when flow control point actions were added in commit 8e01f1b5.

## Investigation

The right-click handler in `canvas.py` (commit 8e01f1b5) was rewritten to iterate `self.items(scenePos())` looking for `FlowControlHandle` and `FlowTextBlkItem` in z-order. This approach is unreliable because:

1. `self.items()` returns items in z-order, but `FlowControlHandle` is a child of `FlowShapeControl` (not `FlowTextBlkItem`), and children may not be returned consistently
2. If `FlowTextBlkItem` is not returned from `self.items()` (e.g., because another overlapping item is higher), the flow context menu is never shown
3. The old "standard" context-menu actions (Copy, Paste, Delete, Translate, etc.) that were provided by `self.context_menu_requested.emit(...)` were no longer shown for flow blocks

## Root Cause

The z-order scanning approach is brittle. We have a direct reference to the selected block via `self.txtblkShapeControl.blk_item` — this is always the block being edited. Using `isinstance(self.txtblkShapeControl.blk_item, FlowTextBlkItem)` is more reliable than scanning scene items.

## Solution

Replace the z-order scanning in `canvas.py` with a three-tier check:
1. **On handle?** → use `FlowShapeControl.handleContextMenu()` (for add/delete flow points)
2. **On selected FlowTextBlkItem?** → use `showFlowContextMenu()` (for combined flow+standard menu)
3. **Fallback** → use `FlowShapeControl.handleContextMenu()` then standard canvas menu

## Changes Made

### `flow_textitem.py`
Added `showFlowContextMenu()` method that creates a combined menu:
- Flow-specific actions at top (Add Midpoint Left/Right, Delete Left/Right control point)
- Horizontal separator
- Standard actions at bottom (Copy, Paste, Delete, Translate, etc.) via a call to `Canvas.build_context_menu()` and `Canvas.exec_context_menu()`

### `flow_shapecontrol.py`
Added `FLOW_CONTROL_POINT_COUNT = 6` constant and `_has_left_point(idx)`, `_has_right_point(idx)` methods for robust control point existence checking.

### `canvas.py`
Replaced z-order scanning with `self.txtblkShapeControl.blk_item` check. All necessary imports (`FlowControlHandle`, `FlowTextBlkItem`) are already at the top of the file.

## Files Modified

1. `ui/flow_textitem.py` — added `showFlowContextMenu()` (40 lines)
2. `ui/flow_shapecontrol.py` — added `FLOW_CONTROL_POINT_COUNT`, `_has_left_point()`, `_has_right_point()` (12 lines)
3. `ui/canvas.py` — simplified right-click handler (replaced z-order scan with `blk_item` check, removed local imports) (15 lines)