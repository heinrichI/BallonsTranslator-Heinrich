# Implementation Plan

[Overview]
Fix FlowShapeControl handles drifting away from the text item when the item is moved or edited.

The bug is that `FlowShapeControl` is an independent `QGraphicsItem` on the scene with its own `pos()`. When `updateHandlePositions()` calls `self.mapFromScene(scene_pos)`, the result depends on the control's own `pos()`. Since `FlowShapeControl.setPos()` forwards to `blk_item.setPos()` AND calls `super().setPos(pos)`, it keeps them in sync only during drag-create. During normal item move (e.g. TextBlkItem being dragged), the `FlowShapeControl` pos is **not updated**, causing the `ctrl_local` coordinates to drift.

The correct fix: ensure handles always use scene coordinates directly by keeping `FlowShapeControl` permanently at scene origin `(0, 0)`. Then `ctrl_local == scene_pos` always, and `handle.setPos(scene_pos)` is correct. Alternatively, after each item move, call `super().setPos(QPointF(0, 0))` to reset the control's own position.

[Types]
No type changes needed.

No new types, interfaces, or data structures are required for this fix.

[Files]
Only `ui/flow_shapecontrol.py` needs to be modified.

- **Modified:** `ui/flow_shapecontrol.py`
  - `updateHandlePositions()`: set `self.setPos(QPointF(0,0))` at the start (or use scene coords directly), then call `handle.setPos(scene_pos)` instead of `handle.setPos(self.mapFromScene(scene_pos))`
  - `setPos()`: remove the `super().setPos(pos)` call so the control always stays at `(0,0)` on scene
  - `__init__()`: ensure control is added at `(0,0)` on scene

[Functions]
Two methods in `FlowShapeControl` need to be changed.

- **Modified:** `updateHandlePositions` in `ui/flow_shapecontrol.py`
  - Add `super().setPos(QPointF(0, 0))` at top to ensure ctrl is always at origin
  - Change `handle.setPos(self.mapFromScene(scene_pos))` → `handle.setPos(scene_pos)` (since ctrl is at origin, scene == local)

- **Modified:** `setPos` in `ui/flow_shapecontrol.py`  
  - Remove `super().setPos(pos)` — control should never move from `(0,0)`
  - Keep only `self.blk_item.setPos(pos)` forwarding

[Classes]
`FlowShapeControl` class in `ui/flow_shapecontrol.py` needs targeted changes.

- **Modified:** `FlowShapeControl`
  - `updateHandlePositions`: reset own pos to `(0,0)`, use scene coords for handles
  - `setPos`: only forward to blk_item, don't move control itself

[Dependencies]
No dependency changes required.

No new packages or version changes needed.

[Testing]
Manual testing: drag a FlowTextBlkItem around the canvas, verify handles stay attached.

- Move item → handles follow correctly
- Drag handle → handle and boundary curve stay in sync
- Open/close editing mode → handles reappear in correct positions
- Zoom in/out → handles remain correctly positioned

[Implementation Order]
Apply two targeted changes to `ui/flow_shapecontrol.py` in sequence.

1. In `updateHandlePositions()`: add `super().setPos(QPointF(0, 0))` at start, change `handle.setPos(self.mapFromScene(scene_pos))` to `handle.setPos(scene_pos)`
2. In `setPos()`: remove `super().setPos(pos)` to prevent control from ever drifting from scene origin