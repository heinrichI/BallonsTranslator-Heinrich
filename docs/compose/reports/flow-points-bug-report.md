# Bug Report: Flow Control Points Not Persisting on Page Switch

## Summary

Flow control points (circles) on FlowTextBlkItem were lost when switching pages. The block position and size also became incorrect after reload. Fixing this required ~15 iterations across multiple files because the issue was a cascade of interconnected bugs, not a single root cause.

## Root Causes (3 separate bugs)

### Bug 1: `save_flow_points()` called with empty lists during init

**File**: `flow_textitem.py`, `setVertical()` method

`setVertical()` was called during `super().__init__()` → `initTextBlock()` → `setVertical()`. At that point `_left_points` was `[]` (set on line 172). `save_flow_points()` was called unconditionally, writing `[]` to `blk.left_points` — **destroying saved points before they could be restored** at line 190.

**Fix**: Guard `save_flow_points()` with `if self._left_points and self._right_points:`.

### Bug 2: `_init_points_from_rect` called with wrong `_display_rect`

**File**: `flow_textitem.py`, `setVertical()` method

`_init_points_from_rect` was called during `setVertical()` (inside `super().__init__()`). At that point `_display_rect` was `QRectF(0, 0, 1, 1)` (default from `TextBlkItem.__init__`), which is too small (`width < 10`). The method returned early without generating points.

For blocks WITHOUT saved points, `_left_points` remained `[]` — no flow controls appeared.

**Fix**: Move point generation from `setVertical()` to `__init__()` AFTER `super().__init__()`, when `_display_rect` has correct dimensions from `setRect()`.

### Bug 3: `_display_rect` inflated by document margins

**Files**: `flow_textitem.py`, `on_document_enlarged()`, `docSizeChanged()`, `_update_flow_layout()`

`_display_rect` was set from `documentSize()` which includes document margins. But `absBoundingRect()` subtracts `2 * padding()` from `_display_rect`. This created wrong dimensions:
- `_display_rect.width()` = text_width + 2*margin
- `absBoundingRect width` = text_width + 2*margin - 2*margin = text_width (OK for width)
- But `_display_rect.height()` = text_height + 2*margin (inflated)
- `absBoundingRect height` = text_height + 2*margin - 2*margin = text_height (OK)

The problem was that `_display_rect` didn't match the actual text extent, causing font size calculations to produce wrong results.

**Fix**: Compute `_display_rect` from `shrink_height` (layout's actual text height) and control point x-range (actual text width), not from `documentSize()`.

## Why It Was So Complex

1. **Cascade effect**: Bug 1 destroyed saved points → Bug 2 prevented default point generation → Bug 3 caused wrong font sizes. All three had to be fixed together.

2. **Initialization order sensitivity**: `super().__init__()` calls `initTextBlock()` → `setVertical()` which triggers point generation. The order of operations during init is critical and non-obvious.

3. **`_display_rect` dual meaning**: Used both for Qt layout sizing AND for saving block dimensions. When one use case changed (flow layout), the other broke.

4. **Signal/timing issues**: `on_document_enlarged` and `docSizeChanged` are signals that fire during layout. Guarded by `_updating_flow` but could fire at unexpected times.

5. **Multiple coordinate systems**: Item-local coords (control points), scene coords (block position), document coords (layout). Mixing them up causes invisible bugs.

## How to Prevent Similar Issues

### 1. Always guard `save_*` methods during init

```python
# BAD: saves empty/default state during init
def setVertical(self, vertical):
    super().setVertical(vertical)
    self.save_flow_points()  # ← overwrites blk data with empty []

# GOOD: only save when there's something to save
def setVertical(self, vertical):
    super().setVertical(vertical)
    if self._left_points and self._right_points:
        self.save_flow_points()
```

### 2. Don't generate state during `super().__init__()`

```python
# BAD: _display_rect is wrong during super().__init__()
def __init__(self, blk):
    self._points = []
    super().__init__(blk)  # ← calls setVertical → _init_points_from_rect (wrong _display_rect)
    # Too late to fix — points already generated with wrong data

# GOOD: generate AFTER super().__init__() when state is valid
def __init__(self, blk):
    self._points = []
    super().__init__(blk)  # ← _display_rect now correct from setRect()
    if not self._points:
        self._generate_default_points()  # ← correct _display_rect
```

### 3. Don't use `documentSize()` for `_display_rect`

```python
# BAD: documentSize() includes margins
self._display_rect.setHeight(self.documentSize().height())

# GOOD: use actual text extent
self._display_rect.setHeight(self.layout.shrink_height + 2 * doc_margin)
```

### 4. Write tests for save/load round-trip

```python
def test_flow_points_persist_across_reinit():
    """Flow points saved to blk must survive re-creation of FlowTextBlkItem."""
    blk = TextBlock([100, 100, 300, 200])
    blk.left_points = [[0, 0], [0, 50], [100, 60]]
    blk.right_points = [[200, 0], [200, 50], [200, 100]]

    # Create, then re-create from same blk
    item1 = FlowTextBlkItem(blk, 0)
    item2 = FlowTextBlkItem(blk, 0)

    assert item2._left_points[2].x() == 100  # custom point preserved
    assert item2._right_points[2].y() == 100

def test_absBoundingRect_uses_display_rect():
    """absBoundingRect must not be inflated by document margins."""
    item = FlowTextBlkItem(...)
    item._display_rect = QRectF(0, 0, 200, 100)
    abr = item.absBoundingRect()
    # Must be <= display_rect dimensions (after padding subtraction)
    assert abr[2] <= 200  # width
    assert abr[3] <= 100  # height

def test_default_points_generated_for_new_blocks():
    """New blocks without saved points must get default rectangle points."""
    blk = TextBlock([100, 100, 300, 200])  # no left_points
    item = FlowTextBlkItem(blk, 0)
    assert len(item._left_points) == 3  # DEFAULT_POINTS_PER_SIDE
    assert len(item._right_points) == 3
```

### 5. Add logging at critical save/load points

```python
def save_flow_points(self):
    if self.blk is None:
        return
    self.blk.left_points = [[p.x(), p.y()] for p in self._left_points]
    self.blk.right_points = [[p.x(), p.y()] for p in self._right_points]
    # Log to catch silent overwrites during init
    if not self._left_points:
        LOGGER.warning("save_flow_points: saving EMPTY points to blk!")
```

## Files Modified

- `ui/flow_textitem.py` — `__init__`, `_init_points_from_rect`, `setVertical`, `on_document_enlarged`, `docSizeChanged`, `_update_flow_layout`, `absBoundingRect`
- `ui/flow_shapecontrol.py` — `FlowControlHandle` (removed `ItemIsMovable`), `FlowShapeControl` (added mouse handlers, fixed `boundingRect`)
- `ui/scenetext_manager.py` — `clearSceneTextitems` (save points before clear), `updateSceneTextitems` (always call `updateTextBlkList`)
