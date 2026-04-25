# Implementation Plan

[Overview]
Replace rectangular TextBlkItem with FlowTextBlkItem that uses 3 editable control points per side to define curved/trapezoidal text boundaries, with auto font-size fitting, hover-only controls, and clean result image export.

This implementation introduces a new `FlowTextBlkItem` class that inherits from `QGraphicsTextItem` (same as the current `TextBlkItem`) to preserve all existing text editing, undo/redo, and signal infrastructure. The left and right boundary of each block is defined by 3 `QPointF` control points (top, middle, bottom). The existing `HorizontalTextDocumentLayout` is reused, but a new per-row x-offset mechanism clamps each text line to stay within the curved boundaries. The 8-handle `TextBlkShapeControl` is replaced by a `FlowShapeControl` that only shows 6 circular drag handles (3 left + 3 right) on hover. The `TextBlock` data model gains two new optional fields `left_points` and `right_points` for serialization. On result image export (`render_result_img`), boundary overlays are suppressed via a `draw_boundaries` flag on each item. Per-word bold/italic editing works automatically because `QGraphicsTextItem` + `QTextCursor` already support it.

**Serialization flow:**
- `TextBlock.to_dict()` uses `vars(self)` — new fields are included automatically.
- `TextBlkEncoder.default()` in `utils/proj_imgtrans.py` calls `obj.to_dict()` → no changes needed there.
- Loading: `TextBlock(**blk_dict)` in `load_from_dict` — new fields deserialize naturally if present; missing = empty list = fallback to rect.

[Types]
Add `left_points` and `right_points` to `TextBlock`; define boundary interpolation helpers.

New fields in `TextBlock` (`utils/textblock.py`):
```python
left_points: List = field(default_factory=lambda: [])   # [[x,y],[x,y],[x,y]] item-local coords
right_points: List = field(default_factory=lambda: [])  # same
```

Helper functions in `ui/flow_textitem.py`:
```python
def interpolate_boundary(points: List[QPointF], y: float) -> float:
    """Linear interpolation between 3 sorted-by-y control points, returns x at height y."""

def build_quad_path(points: List[QPointF]) -> QPainterPath:
    """Quadratic bezier through 3 points for visual boundary curve."""
```

[Files]
Create two new files and modify eight existing files.

**New files:**
- `ui/flow_textitem.py` — `FlowTextBlkItem` class
- `ui/flow_shapecontrol.py` — `FlowShapeControl` + `FlowControlHandle` classes

**Modified files:**
- `utils/textblock.py` — add `left_points`, `right_points` fields
- `ui/scene_textlayout.py` — add per-line x-offset support to `HorizontalTextDocumentLayout`
- `ui/textitem.py` — replace class body with import alias: `from .flow_textitem import FlowTextBlkItem as TextBlkItem`
- `ui/texteditshapecontrol.py` — add alias: `from .flow_shapecontrol import FlowShapeControl as TextBlkShapeControl`
- `ui/canvas.py` — import `FlowShapeControl`; instantiate it; hide `draw_boundaries` in `render_result_img`
- `ui/scenetext_manager.py` — init flow points in `onEndCreateTextBlock`; update `updateTextBlkList` to save flow points; update `layout_textblk`
- `ui/textedit_commands.py` — update `ReshapeItemCommand` to save/restore flow points
- `ui/drawing_commands.py` — no structural change needed (uses `TextBlkItem` type only, covered by alias)

**No changes needed** (covered by `TextBlkItem` alias):
- `ui/fontformat_commands.py`
- `ui/global_search_widget.py`
- `ui/page_search_widget.py`
- `ui/text_panel.py`
- `ui/mainwindow.py` — uses only `textblk_item_list`, `squeezeBoundingRect()` — all covered
- `utils/proj_imgtrans.py` — `TextBlkEncoder` calls `to_dict()` which uses `vars()` automatically

[Functions]
Create new functions for boundary interpolation, per-line x-clamping, and font-size fitting within flow shape.

**New functions in `ui/flow_textitem.py`:**
- `interpolate_boundary(points, y)` — linear interp for left/right x at row y
- `build_quad_path(points)` — QPainterPath quadratic bezier for 3 control points
- `FlowTextBlkItem._init_points_from_rect(rect)` — initialize 3+3 points from a plain rectangle
- `FlowTextBlkItem._get_line_x_offsets()` — compute left_x per text-line from boundary + layout
- `FlowTextBlkItem._update_flow_layout()` — call layout's `set_line_x_offsets()` and `reLayout()`
- `FlowTextBlkItem._fit_font_size(text)` — binary search max font size fitting within flow shape
- `FlowTextBlkItem.save_flow_points()` — write `_left_points`/`_right_points` back to `blk`

**New functions in `ui/flow_shapecontrol.py`:**
- `FlowShapeControl.setBlkItem(item)` — attach to item, position handles
- `FlowShapeControl.updateHandlePositions()` — sync handle positions from item points
- `FlowShapeControl.updateBoundingRect()` — compat shim (calls updateHandlePositions)
- `FlowShapeControl.updateScale(scale)` — scale handle sizes
- `FlowShapeControl.startEditing()` / `endEditing()` — hide/show handles during text edit
- `FlowShapeControl.hideControls()` / `showControls()` — compat with canvas creation flow

**Modified functions:**
- `HorizontalTextDocumentLayout.doLayout()` — apply `_line_x_offsets[i]` as line x-position
- `HorizontalTextDocumentLayout.set_line_x_offsets(offsets: dict)` — store and trigger relayout
- `SceneTextManager.onEndCreateTextBlock()` — call `blk_item._init_points_from_rect()`
- `SceneTextManager.updateTextBlkList()` — add `blk_item.save_flow_points()` call
- `SceneTextManager.layout_textblk()` — call `blk_item._update_flow_layout()` after font-size fit
- `Canvas.render_result_img()` — set `blk_item.draw_boundaries = False` before render, restore after
- `ReshapeItemCommand.__init__/redo/undo` — save/restore `left_points`/`right_points` lists

[Classes]
Replace TextBlkItem with FlowTextBlkItem; replace TextBlkShapeControl with FlowShapeControl.

**New class `FlowTextBlkItem(QGraphicsTextItem)` in `ui/flow_textitem.py`:**
- All same signals as original `TextBlkItem`: `begin_edit`, `end_edit`, `hover_enter`, `hover_move`, `moved`, `moving`, `rotated`, `reshaped`, `leftbutton_pressed`, `doc_size_changed`, `pasted`, `redo_signal`, `undo_signal`, `push_undo_stack`, `propagate_user_edited`
- Same attributes: `blk`, `fontformat`, `idx`, `under_ctrl`, `draw_rect`, `reshaping`, `oldPos`, `oldRect`, `repaint_on_changed`, `is_formatting`, `layout`, etc.
- New attributes: `_left_points: List[QPointF]`, `_right_points: List[QPointF]`, `_hover: bool`, `draw_boundaries: bool`
- `setAcceptHoverEvents(True)`
- `hoverEnterEvent` / `hoverLeaveEvent` → set `_hover`, call `update()`
- `paint()` — draws boundary bezier lines + control dots only when `_hover or under_ctrl` AND `draw_boundaries`; calls `super().paint()` for text
- Reuses `HorizontalTextDocumentLayout`; calls `set_line_x_offsets()` to flow text

**New class `FlowControlHandle(QGraphicsEllipseItem)` in `ui/flow_shapecontrol.py`:**
- Circle radius 5px (scaled with canvas zoom)
- `side: str` ('left'/'right'), `point_idx: int` (0/1/2)
- Draggable: `mouseMoveEvent` → updates parent item's `_left_points[idx]` or `_right_points[idx]`
- Calls `blk_item._update_flow_layout()` on every drag step

**New class `FlowShapeControl(QGraphicsItem)` in `ui/flow_shapecontrol.py`:**
- Replaces `TextBlkShapeControl` completely
- `blk_item: FlowTextBlkItem`
- `reshaping: bool` — kept for compat with `scenetext_manager.py`
- No bounding rect rectangle drawn (unlike `TextBlkShapeControl`)
- 6 `FlowControlHandle` children
- All same public methods: `setBlkItem()`, `updateBoundingRect()`, `updateScale()`, `startEditing()`, `endEditing()`, `hideControls()`, `showControls()`, `setAngle()`, `setPos()`, `show()`, `hide()`
- `previewPixmap` stub kept for compat (not used without rotation)
- `angleLabel` stub kept for compat

**Modified class `TextBlock` (`utils/textblock.py`):**
- Add `left_points: List = field(default_factory=lambda: [])` 
- Add `right_points: List = field(default_factory=lambda: [])`

**Modified class `HorizontalTextDocumentLayout` (`ui/scene_textlayout.py`):**
- Add `_line_x_offsets: dict = {}` in `__init__`
- Add `set_line_x_offsets(offsets: dict)` method
- In `doLayout()` (or equivalent line-positioning code): add `x_offset = self._line_x_offsets.get(line_idx, 0)` when setting each line's x position

[Dependencies]
No new external packages required.

All needed libraries (`qtpy`, `numpy`, `cv2`) are already in `requirements.txt`.

[Testing]
Manual testing via the BallonsTranslator UI; no automated test suite exists.

Key test scenarios:
1. Create text block by dragging → rectangular default shape, 6 handles on hover
2. Drag left/right handles → text reflows within new boundary
3. Auto-layout → font size adapts to flow shape
4. Save project → `left_points`/`right_points` appear in JSON
5. Reload project → boundaries restored correctly; old projects without these fields work via rect fallback
6. Export result image → no boundary lines or handles in output
7. Undo/redo reshape → flow points correctly restored
8. Per-word bold/italic via text panel → works as before

[Implementation Order]
Implement in strict dependency order to avoid import errors.

1. **`utils/textblock.py`** — add `left_points`, `right_points` fields to `TextBlock`
2. **`ui/scene_textlayout.py`** — add `_line_x_offsets` + `set_line_x_offsets()` + apply in `doLayout()` of `HorizontalTextDocumentLayout`
3. **`ui/flow_textitem.py`** (new) — full `FlowTextBlkItem` implementation with all signals, methods, boundary logic, paint
4. **`ui/flow_shapecontrol.py`** (new) — `FlowControlHandle` + `FlowShapeControl` implementation
5. **`ui/textitem.py`** — replace class with alias `from .flow_textitem import FlowTextBlkItem as TextBlkItem` (keep `TextBlock` re-export)
6. **`ui/texteditshapecontrol.py`** — add at bottom: `from .flow_shapecontrol import FlowShapeControl as TextBlkShapeControl` (keep existing class for potential fallback)
7. **`ui/canvas.py`** — import `FlowShapeControl`; instantiate as `txtblkShapeControl`; in `render_result_img` set `draw_boundaries=False` on all text items
8. **`ui/scenetext_manager.py`** — `onEndCreateTextBlock` init flow points; `updateTextBlkList` save flow points; `layout_textblk` call `_update_flow_layout`
9. **`ui/textedit_commands.py`** — update `ReshapeItemCommand` to copy/restore `left_points`/`right_points`