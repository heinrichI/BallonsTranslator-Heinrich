# Implementation Plan

**Fix two bugs in FlowTextBlkItem: vertical-mode text alignment and auto-shrink font when text overflows.**

## Overview

Two bugs were reported in `FlowTextBlkItem`. First: when the item is in vertical text mode, all text is pushed to the right edge of the red bounding box regardless of control handle positions. Second: when the bounding box is made very small and there is no room for line breaks, text gets clipped instead of the font size being reduced. This plan describes the changes needed to fix both issues.

### Bug 1 — Vertical mode text pushed to right edge

**Root cause**: `_get_line_x_offsets()` and `_update_flow_layout()` only push offsets to `HorizontalTextDocumentLayout.set_line_x_offsets()`. The `VerticalTextDocumentLayout` knows nothing about `_line_left_offsets`/`_line_right_offsets` — it always uses its own per-line `line_width` derived from `block_ideal_width` (max character width), which fits between the doc margins and pushes all lines to the rightmost position.

**Solution**: When the item switches to vertical mode (`setVertical(True)`), reset the flow control points to a rectangle aligned with the item's bounding rect. This effectively disables flow-behaviour for vertical text. The control handles revert to standard TextBlkShapeControl-style rectangular behaviour (though still using FlowShapeControl, the points become a flat rectangle).

### Bug 2 — Text clipped instead of font shrinking

**Root cause**: `HorizontalTextDocumentLayout.reLayout()` expands `self.max_height` when `new_height > self.available_height`, emitting `size_enlarged`. But there is no mechanism to reduce font size when `new_height` exceeds available space. The text extends beyond the visual bounding box and gets clipped.

**Solution**: Add an iterative font-shrink loop in `FlowTextBlkItem._update_flow_layout()` (or a dedicated `_auto_shrink_font()` method). After the initial layout, if the text height exceeds available height, repeatedly scale down the font (factor ≈0.9 per iteration) until the text fits or min font size (5pt) is reached.

---

## Types

No new types or dataclasses are introduced. The `FlowTextBlkItem` class and `SceneTextLayout` / `VerticalTextDocumentLayout` / `HorizontalTextDocumentLayout` classes are modified.

### Constants

- `MIN_FONT_SIZE_PT: float = 5.0` — minimum font size in points (already exists as conceptual limit, added as constant in flow_textitem.py)
- `FONT_SHRINK_FACTOR: float = 0.9` — multiplicative factor per shrink iteration

---

## Files

### New files

None.

### Modified files

1. **`ui/flow_textitem.py`**
   - Add `MIN_FONT_SIZE_PT = 5.0` constant
   - Add `FONT_SHRINK_FACTOR = 0.9` constant
   - Modify `_update_flow_layout()` to call `_auto_shrink_font()` after layout update
   - Add `_auto_shrink_font()` method — iteratively reduces font size until text fits or reaches min limit
   - Override `setVertical()` in `FlowTextBlkItem` — when switching to vertical mode, reset flow control points to a rectangle and disable flow

2. **`ui/scene_textlayout.py`** (minimal change)
   - No structural changes needed for bug 1 (the fix is in flow_textitem.py, not in the layout engine)
   - For bug 2: the shrink logic lives entirely in flow_textitem.py (calls existing `setRelFontSize()` and checks minSize/shrink_height after relayout)

3. **`ui/flow_shapecontrol.py`**
   - When flow is disabled (vertical mode), handle visibility should match standard behaviour
   - Modify `setBlkItem()` to detect flow-disabled state and hide all flow handles
   - Modify `rebuildHandles()` to handle zero-points case

### Files NOT modified

- `ui/canvas.py` — no changes needed
- `ui/textitem.py` — no changes needed
- `ui/scenetext_manager.py` — duck-typing via hasattr continues to work
- `utils/textblock.py` — no structural changes

---

## Functions

### New functions

| Function | File | Signature | Purpose |
|----------|------|-----------|---------|
| `_auto_shrink_font()` | `ui/flow_textitem.py` | `def _auto_shrink_font(self) -> bool` | Iteratively reduces font size until text fits in available space or reaches min 5pt. Returns True if shrink was applied. |

### Modified functions

| Function | File | Change |
|----------|------|--------|
| `FlowTextBlkItem.__init__()` | `ui/flow_textitem.py` | No signature change. After `_init_points_from_rect()`, check if vertical mode and reset to rectangle. |
| `FlowTextBlkItem._update_flow_layout()` | `ui/flow_textitem.py` | Add a call to `self._auto_shrink_font()` after calling `self.layout.set_line_x_offsets()` and `self.repaint_background()`. |
| `FlowTextBlkItem.setVertical()` (new override) | `ui/flow_textitem.py` | Override `TextBlkItem.setVertical()` to reset flow points to rectangle when switching to vertical mode. |
| `FlowTextBlkItem._init_points_from_rect()` | `ui/flow_textitem.py` | No change. Used as-is by `setVertical()` to reset points. |

### Details of `_auto_shrink_font()` algorithm

```
1. Get available_height = self.layout.available_height
2. Get current min font size from self.layout.max_font_size()
3. If min_font_size_pt <= MIN_FONT_SIZE_PT → return False (already at minimum)
4. Loop (max 20 iterations):
   a. Compute max shrink factor needed: 
      - Get text extent = self.layout.shrink_height
      - If text_extent <= available_height → break (fits)
      - shrink = min(0.9, available_height / text_extent * 0.95)  # 5% safety margin
   b. Apply setRelFontSize(shrink) — this multiplies ALL font sizes by shrink
   c. Re-layout happens inside setRelFontSize
   d. Check new min font size → if < MIN_FONT_SIZE_PT → clamp and break
5. Return True if shrink was applied
```

**Important**: `setRelFontSize()` triggers `reLayoutEverything()` → `reLayout()`, which is expensive. But iterating up to ~5 times is acceptable since it happens only when the user drags a handle (not every frame).

---

## Classes

### Modified classes

| Class | File | Change |
|-------|------|--------|
| `FlowTextBlkItem` | `ui/flow_textitem.py` | Add `_auto_shrink_font()` method. Override `setVertical()`. Modify `_update_flow_layout()` to call shrink. |
| `FlowShapeControl` | `ui/flow_shapecontrol.py` | Handle zero-points state (flow disabled) gracefully. |

### FlowTextBlkItem.setVertical() override

```python
def setVertical(self, vertical: bool):
    """Reset flow points to rectangle when switching to vertical mode."""
    if vertical:
        # Get current abs bounding rect
        rect = self.absBoundingRect(qrect=True)
        # Reset flow points to rectangle aligned with item
        self._init_points_from_rect(rect)
        # Update layout with rectangle offsets (no per-line flow)
        self._update_flow_layout()
        # Save the rectangle points
        self.save_flow_points()
        # Hide flow handles (they're now redundant; FlowShapeControl will see
        # points form a rectangle and show only resize handles)
    super().setVertical(vertical)
```

After `super().setVertical(vertical)`, the layout engine is `VerticalTextDocumentLayout`, which handles vertical text in a rectangular box. The flow control points are still present but form a perfect rectangle, so `interpolate_boundary()` returns constant x values → no per-line offset variation.

### Flow shape control handle visibility in vertical mode

In `FlowShapeControl.setBlkItem()` and `rebuildHandles()`, if the blk_item is in vertical mode, flow handles should be hidden. Only resize handles (top/bottom) should be visible.

---

## Dependencies

No new external dependencies. Existing imports suffice.

---

## Testing

### Test scenarios (manual verification)

1. **Vertical mode alignment**:
   - Create a FlowTextBlkItem with horizontal text, drag middle handles to create a trapezoid
   - Switch to vertical mode
   - Verify: text is no longer pushed to right edge, it renders vertically in the bounding box
   - Verify: flow handles disappear from the control, only resize handles show
   - Switch back to horizontal mode
   - Verify: flow handles reappear, trapezoid shape is restored

2. **Font auto-shrink on overflow**:
   - Create a FlowTextBlkItem with long text
   - Drag top handle down to make the box very short
   - Verify: font size decreases until text fits (or reaches 5pt)
   - Verify: no text is clipped outside the bounding box
   - Expand the box again
   - Verify: font size does NOT increase (shrink is one-way; user can manually increase)
     * Actually, reconsider: should font restore on expand? Current design: shrink is one-way defensive. User can manually change font size in the text panel.

3. **Edge case — 5pt limit**:
   - Create text with very long content in a tiny bounding box
   - Verify: font shrinks iteratively until it reaches ~5pt, then stops
   - Text may still be clipped at 5pt if it's extremely long — this is acceptable

### Existing test suite
- `tests/test_scenetext_manager_visibility.py` — should still pass with flow changes
- No automated tests exist for flow items (manual testing)

---

## Implementation Order

1. Add constants `MIN_FONT_SIZE_PT` and `FONT_SHRINK_FACTOR` to `ui/flow_textitem.py`
2. Add `_auto_shrink_font()` method to `FlowTextBlkItem`
3. Modify `_update_flow_layout()` to call `_auto_shrink_font()`
4. Override `setVertical()` in `FlowTextBlkItem` to reset flow points to rectangle
5. Update `FlowShapeControl` to handle flow-disabled/vertical state
6. Build and test: run the application, verify both bugs are fixed