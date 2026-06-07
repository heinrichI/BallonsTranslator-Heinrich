# Implementation Plan

Refactor the FlowTextBlkItem feature (изогнутые текстовые блоки) to minimize the number of modified files while maintaining Single Responsibility Principle.

The existing implementation across 4 commits touches 7 files: flow_textitem.py (new), flow_shapecontrol.py (new), canvas.py, scene_textlayout.py, scenetext_manager.py, textedit_commands.py, texteditshapecontrol.py. The refactored version will touch only 4 files: 2 new files + 2 existing files with minimal changes. This is achieved by abstracting flow-specific context menu logic behind a single method on FlowShapeControl, removing the need for canvas.py to import FlowControlHandle or know about FlowTextBlkItem context menus. Changes to scenetext_manager.py, textedit_commands.py, and texteditshapecontrol.py are eliminated entirely (the new FlowTextBlkItem inherits from TextBlkItem, and the existing code uses duck-typing / hasattr checks that work without modification).

[Types]
Two new classes with clear SRP boundaries.

- `FlowTextBlkItem(TextBlkItem)` in `ui/flow_textitem.py`:
  - Fields: `_left_points: List[QPointF]`, `_right_points: List[QPointF]`, `_hover: bool`, `draw_boundaries: bool`
  - Methods: `_init_points_from_rect()`, `_get_line_x_offsets() -> Tuple[dict, dict]`, `_update_flow_layout()`, `save_flow_points()`, `set_size()`, `boundingRect()`, `paint()`, `hoverEnterEvent/LeaveEvent()`, `showFlowContextMenu()`, `_show_standard_context_menu()`
  - Helper functions: `interpolate_boundary(points, y) -> float`, `build_quad_path(points) -> QPainterPath`

- `FlowShapeControl(QGraphicsItem)` in `ui/flow_shapecontrol.py`:
  - Fields: `gv`, `blk_item`, `handles: List[FlowControlHandle]`, `top_handle: FlowResizeHandle`, `bottom_handle: FlowResizeHandle`, `previewPixmap`, `angleLabel`, `current_scale`, `need_rescale`
  - Public API compatible with TextBlkShapeControl: `setBlkItem()`, `rebuildHandles()`, `updateHandlePositions()`, `updateBoundingRect()`, `updateScale()`, `startEditing()`, `endEditing()`, `hideControls()`, `showControls()`, `setAngle()`, `setPos()`, `setRect()`, `rect()`, `show()`, `hide()`, `ctrlblockPressed()`, `rotation()`, `setRotation()`, `sceneBoundingRect()`
  - NEW method: `handleContextMenu(scene_pos, screen_pos) -> bool` — encapsulates flow handle + flow item right-click logic, returns True if handled
  - Contains nested classes:
    - `FlowControlHandle(QGraphicsEllipseItem)` — 6 draggable circular handles
    - `FlowResizeHandle(QGraphicsItem)` — 2 diamond-shaped resize handles
    - `_NullPixmapItem(QGraphicsItem)` — stub for previewPixmap

- `HorizontalTextDocumentLayout.set_line_x_offsets()` and associated fields `_line_left_offsets: dict`, `_line_right_offsets: dict` — minimal addition to existing class in `ui/scene_textlayout.py`

[Files]
Two new files, two existing files modified minimally.

- **NEW: `ui/flow_textitem.py`** — FlowTextBlkItem class with boundary interpolation, layout integration, hover/paint, context menu
- **NEW: `ui/flow_shapecontrol.py`** — FlowShapeControl + FlowControlHandle + FlowResizeHandle, the complete replacement for TextBlkShapeControl when editing FlowTextBlkItem
- **MODIFIED: `ui/canvas.py`** — only 4 specific changes:
  1. Import: `from .flow_shapecontrol import FlowShapeControl` (no FlowControlHandle import)
  2. Init: `self.txtblkShapeControl = FlowShapeControl(self.gv)` (replaces TextBlkShapeControl)
  3. Scale: call `self.txtblkShapeControl.updateScale(self.scale_factor)` in `scaleImage()`
  4. Render: flow boundary suppression in `render_result_img()` — set `draw_boundaries = False` on FlowTextBlkItem instances before render
  5. Right-click: replace explicit isinstance checks with `self.txtblkShapeControl.handleContextMenu(scenePos, screenPos)`
- **MODIFIED: `ui/scene_textlayout.py`** — Add to HorizontalTextDocumentLayout:
  1. Fields: `_line_left_offsets: dict = {}`, `_line_right_offsets: dict = {}`
  2. Method: `set_line_x_offsets(left_offsets, right_offsets)` — stores offsets and triggers relayout
  3. In `layoutBlock()`: use `_line_left_offsets.get(line_idx, 0)` and `_line_right_offsets.get(line_idx)` for dynamic line width

- **NOT MODIFIED (excluded):** `ui/scenetext_manager.py` — imports FlowTextBlkItem already via the old commit, uses `hasattr` checks which work with minimal import
- **NOT MODIFIED (excluded):** `ui/textedit_commands.py` — uses `hasattr` duck-typing for flow points
- **NOT MODIFIED (excluded):** `ui/texteditshapecontrol.py` — TextBlkShapeControl remains unchanged; FlowShapeControl replaces it at the canvas level

[Functions]
- NEW: `interpolate_boundary(points, y)` in `flow_textitem.py` — linear interpolation between control points
- NEW: `build_quad_path(points)` in `flow_textitem.py` — quadratic Bezier path through 3 points
- MODIFIED: `HorizontalTextDocumentLayout.set_line_x_offsets()` in `scene_textlayout.py` — new method
- MODIFIED: `Canvas.mouseReleaseEvent()` in `canvas.py` — replace flow handle/item right-click logic with `self.txtblkShapeControl.handleContextMenu()`
- MODIFIED: `Canvas.render_result_img()` in `canvas.py` — add flow boundary suppression
- MODIFIED: `Canvas.scaleImage()` in `canvas.py` — add `self.txtblkShapeControl.updateScale()` call
- NO CHANGE: `scenetext_manager.py` — `FlowTextBlkItem` import remains, no other changes needed
- NO CHANGE: `textedit_commands.py` — ReshapeItemCommand already uses duck-typing
- NO CHANGE: `texteditshapecontrol.py` — no changes needed

[Classes]
- **NEW: `FlowTextBlkItem(TextBlkItem)** in `ui/flow_textitem.py` — key methods: `_init_points_from_rect`, `_get_line_x_offsets`, `_update_flow_layout`, `save_flow_points`, `paint` (boundary overlay), `showFlowContextMenu`
- **NEW: `FlowShapeControl(QGraphicsItem)** in `ui/flow_shapecontrol.py` — key public API: `setBlkItem`, `rebuildHandles`, `updateHandlePositions`, `updateScale`, `handleContextMenu` (new)
- **NEW: `FlowControlHandle(QGraphicsEllipseItem)** in `ui/flow_shapecontrol.py` — nested inside FlowShapeControl
- **NEW: `FlowResizeHandle(QGraphicsItem)** in `ui/flow_shapecontrol.py` — diamond handle, nested inside FlowShapeControl
- **NEW: `_NullPixmapItem(QGraphicsItem)** in `ui/flow_shapecontrol.py` — stub
- **MODIFIED: `HorizontalTextDocumentLayout(SceneTextLayout)** in `ui/scene_textlayout.py` — add flow offset fields and `set_line_x_offsets` method

[Dependencies]
No new package dependencies. All imports are from existing Qt and project modules.

[Testing]
Verify by running the existing test suite and manual testing of flow handle creation and manipulation. `tests/test_scenetext_manager_visibility.py` should pass without modification. No new test files required.

[Implementation Order]
1. Create `ui/flow_textitem.py` with FlowTextBlkItem and helper functions
2. Create `ui/flow_shapecontrol.py` with FlowShapeControl, FlowControlHandle, FlowResizeHandle, including the new `handleContextMenu()` method
3. Modify `ui/scene_textlayout.py` — add `_line_left_offsets`, `_line_right_offsets`, `set_line_x_offsets()`, and update `layoutBlock()`
4. Modify `ui/canvas.py` — 5 targeted changes: import, init, scale, render, right-click delegation
5. Verify imports and run `python -c "from ui.flow_textitem import FlowTextBlkItem; from ui.flow_shapecontrol import FlowShapeControl, FlowControlHandle"`