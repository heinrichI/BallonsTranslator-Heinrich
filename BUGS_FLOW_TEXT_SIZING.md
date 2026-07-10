# Bug: Flow Text Block Font Sizing — Root Cause Analysis

## Symptoms

- Cyrillic text ("БЫСТРЕЕ---", "60 МИЛЬ В ЧАС") rendered with font ~5x too small
- Text overflows block boundaries in some cases
- Font oscillates between sizes on repeated layout passes
- Logs show infinite shrink/grow cycles: text_extent drops 18524→333→5080→1531→492→191→98→63→38→36

## Root Causes (3 independent bugs)

### Bug 1: Binary search measured wrong height metric

**File**: `scenetext_manager.py` → `_find_best_font_size()`

**Problem**: Binary search used `document().size().height()` (Qt document height) to check if text fits. For flow layout with boundary functions, Qt document height does NOT account for trapezoidal boundaries — it returns the raw text extent as if the block were a rectangle. This caused the binary search to think text "fits" at a much smaller font than visually correct.

**Fix**: Use `layout.shrink_height` (actual text extent within boundaries) instead:
```python
doc_h = blkitem.layout.shrink_height if hasattr(blkitem.layout, 'shrink_height') 
        and blkitem.layout.shrink_height > 0 
        else blkitem.document().size().height()
```

**How to spot**: Binary search returns a font where `shrink_height` is 20-30% of block height, not 70-90%.

### Bug 2: `set_size()` permanently overwrites `_auto_font_adjust`

**File**: `flow_textitem.py` → `set_size()`

**Problem**: `set_size()` always set `self._auto_font_adjust = True` (or later `= auto_font_adjust`), permanently changing the flag. When `auto_font_adjust=False` was passed during layout, the flag stayed `False` forever — shrink/grow never ran again for that block.

**Fix**: Save/restore `_auto_font_adjust` around `_update_flow_layout()`:
```python
saved = self._auto_font_adjust
self._auto_font_adjust = auto_font_adjust
self._update_flow_layout()
self._auto_font_adjust = saved
```

**How to spot**: After layout, resize a block via handles — shrink/grow doesn't run.

### Bug 3: `available_height` accumulates across binary search iterations

**File**: `scenetext_manager.py` → `_find_best_font_size()`

**Problem**: Each `set_size()` call triggers `_update_flow_layout()` → `set_boundary_functions()` → `reLayout()`. When text overflows, `reLayout()` expands `available_height`. This expanded value persisted to the next binary search iteration, making the search see "less overflow" and shrink the font further.

**Fix**: Save original `available_height`/`max_height` before loop, restore at each iteration:
```python
orig_avail_h = blkitem.layout.available_height
orig_max_h = blkitem.layout.max_height
for iteration in range(...):
    blkitem.layout.available_height = orig_avail_h
    blkitem.layout.max_height = orig_max_h
    ...
```

**How to spot**: Binary search converges to a font that's progressively smaller across iterations.

### Bug 4: `setFontSize()` disables `_auto_font_adjust` during layout

**File**: `flow_textitem.py` → `setFontSize()` override

**Problem**: `FlowTextBlkItem.setFontSize()` always set `_auto_font_adjust = False` (intended for toolbar font changes). But `layout_textblk()` calls `setFontSize(optimal_size)` to set the binary search result — this permanently disabled shrink/grow.

**Fix**: Restore `_auto_font_adjust = True` and trigger one `_update_flow_layout()` pass at the end of `layout_textblk()`:
```python
blkitem._auto_font_adjust = True
blkitem._update_flow_layout()
```

**How to spot**: Text fits at binary search size but is visually too small (no grow pass).

## Prevention: How to Handle Similar Cases

### 1. Custom layout metrics ≠ Qt document metrics

When using custom `QTextDocumentLayout` subclasses (like `HorizontalTextDocumentLayout`), **never** use `document().size()` for layout measurements. The Qt document size doesn't know about custom boundaries, available_height, or shrink_height. Always use the layout's own metrics:
- `layout.shrink_height` — actual text extent within boundaries
- `layout.shrink_width` — actual text width
- `layout.available_height` — constrained height (may differ from block height)

### 2. Binary search for font size needs clean state

When binary-searching font size by repeatedly calling layout functions:
- Save and restore `available_height`/`max_height` before each iteration
- Use `blockSignals(True)` to prevent signal cascades
- Don't let `set_size()`/`_update_flow_layout()` change persistent flags

### 3. Auto-adjust flags must be scope-controlled

Flags like `_auto_font_adjust` should be:
- **Temporary**: save/restore around operations that shouldn't trigger auto-adjust
- **Not permanently set** by utility methods like `set_size()`
- **Restored** after layout operations complete

### 4. Test with the actual text that caused the bug

Unit tests with "Hello world" don't catch flow layout bugs. Test with:
- Long Cyrillic text that wraps heavily ("БЫСТРЕЕ---" repeated)
- Short text that should fill the block ("60 МИЛЬ В ЧАС")
- Verify both `shrink_height` and `shrink_width` are correct

## Files Modified

- `ui/flow_textitem.py` — `set_size()` save/restore `_auto_font_adjust`
- `ui/scenetext_manager.py` — `_find_best_font_size()` use `shrink_height`, reset layout dimensions; `layout_textblk()` restore auto-adjust and trigger final layout pass
