# Bug: Flow Text Block Font Sizing — Root Cause Analysis

## Symptoms

- Cyrillic text ("БЫСТРЕЕ---", "60 МИЛЬ В ЧАС") rendered with font ~5x too small
- Text overflows block boundaries in some cases
- Font oscillates between sizes on repeated layout passes
- Logs show infinite shrink/grow cycles: text_extent drops 18524→333→5080→1531→492→191→98→63→38→36
- `_auto_font_adjust=True` logged but shrink/grow never runs (Bug 5)
- `reLayout() expanding available_height` but "no overflow, NO SHRINK" (Bug 6)
- Font becomes enormous on empty blocks (Bug 7)

## Root Causes (8 independent bugs)

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

### Bug 5: `_auto_font_adjust` stuck at False after first layout

**File**: `flow_textitem.py` → `setFontSize()` override, `_auto_shrink_font()`, `_auto_grow_font()`

**Problem**: `FlowTextBlkItem.setFontSize()` unconditionally set `_auto_font_adjust = False`. When `_auto_shrink_font()` or `_auto_grow_font()` called `setRelFontSize()` → `setFontSize()`, the flag was reset to False. This permanently disabled auto-adjust after the first layout — shrink/grow never ran on subsequent handle drags or resizes.

**Call chain**:
1. `layout_textblk` restores `_auto_font_adjust = True`
2. `_update_flow_layout()` calls `_auto_shrink_font()`
3. Shrink calls `setRelFontSize(factor)` → `setFontSize()` → flag reset to False
4. All subsequent `_update_flow_layout()` calls see False → skip shrink/grow

**Fix**: Added `_internal_font_change` guard flag:
```python
# In __init__:
self._internal_font_change = False

# In setFontSize override:
if not self._internal_font_adjust:
    self._auto_font_adjust = False

# In _auto_shrink_font and _auto_grow_font:
self._internal_font_change = True
try:
    self.setRelFontSize(factor)
finally:
    self._internal_font_change = False
```

**How to spot**: `_auto_font_adjust=True` logged but no shrink/grow activity follows.

### Bug 6: Height overflow not checked as shrink trigger

**File**: `flow_textitem.py` → `_auto_shrink_font()`

**Problem**: `height_overflow = text_extent > target_height` was computed but never checked in the shrink trigger condition. The trigger only checked `width_overflow`, `char_level_breaks`, and `close_to_width`. When text overflowed vertically (text_extent > target_height), shrink didn't trigger.

**Fix**: Added `height_overflow` to the trigger check:
```python
if not height_overflow and not width_overflow and not char_level_breaks and not close_to_width:
    return False
```

**How to spot**: `reLayout() expanding available_height: 104 → 165` but `_auto_shrink_font` says "no overflow, NO SHRINK".

### Bug 7: `_auto_grow_font` runs on empty blocks

**File**: `flow_textitem.py` → `_auto_grow_font()`, `_auto_shrink_font()`

**Problem**: `_auto_grow_font()` ran on blocks with no text (`text_w=0.0`, `text_extent=17.9` from empty layout). Empty text has tiny extent, so `text_extent < target_height * 0.70` was true, and grow inflated the font to 108% per iteration — making the font enormous.

**Fix**: Skip grow/shrink on empty blocks:
```python
if not self.document().toPlainText().strip():
    return False
```

**How to spot**: Font becomes huge after creating empty blocks or clearing text.

### Bug 8: Ctrl+Z doesn't restore font size after resize

**File**: `textedit_commands.py` → `ReshapeItemCommand`

**Problem**: `ReshapeItemCommand` saved/restored flow points but not the font size. When undo happened, `_update_flow_layout()` triggered shrink/grow, which changed the font again. The original font size was lost.

**Fix**: Save `old_font_size` in `__init__`, restore in `undo()`, track `new_font_size` in `mergeWith()`:
```python
self.old_font_size = item.fontformat.size
# In undo:
self.item.fontformat.size = self.old_font_size
```

### Bug 9: Manual font change permanently blocks auto-adjust

**File**: `flow_textitem.py` → `_update_flow_layout()`

**Problem**: `FlowTextBlkItem.setFontSize()` set `_auto_font_adjust = False` when user changed font manually. This flag stayed False forever — resizing the block after a manual font change never triggered shrink/grow.

**Fix**: Reset `_auto_font_adjust = True` at the END of `_update_flow_layout()` after shrink/grow completes:
```python
self._auto_font_adjust = True
```

**How to spot**: User sets font via toolbar, then drags block handle — font doesn't auto-adjust.

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
- **Guarded** when internal code (shrink/grow) calls methods that reset them — use `_internal_font_change` pattern

### 4. Test with the actual text that caused the bug

Unit tests with "Hello world" don't catch flow layout bugs. Test with:
- Long Cyrillic text that wraps heavily ("БЫСТРЕЕ---" repeated)
- Short text that should fill the block ("60 МИЛЬ В ЧАС")
- Verify both `shrink_height` and `shrink_width` are correct

## Files Modified

- `ui/flow_textitem.py` — `_internal_font_change` guard, height_overflow trigger, empty block guard, reset `_auto_font_adjust` after shrink/grow
- `ui/scenetext_manager.py` — `_find_best_font_size()` use `shrink_height`, reset layout dimensions; `layout_textblk()` restore auto-adjust and trigger final layout pass
- `ui/textedit_commands.py` — `ReshapeItemCommand` save/restore font size

## Test Coverage

`tests/ui/test_flow_textitem.py` — 48 tests across 10 classes:
- `TestAutoFontAdjustFlag` — flag survives shrink/grow cycles
- `TestBlockResizeShrinkGrow` — shrink/grow on handle drag
- `TestEmptyBlockNoGrow` — no font change on empty blocks

---

## Обновление (2026-08-17): нижняя строка обрезается после авторазмера

Полный разбор — в `PLAN_FLOW_BOTTOM_CLIP_FIX.md` (поглощает `PLAN_flowtext_bottom_clip.md`).
Коротко:

**Симптом**: детерминированно, зависит от шрифта/букв/размера: после авторазмера
нижняя часть последней строки вылезает за ограничивающую линию и клипится
boundingRect-ом (BOMGcomPsuedoSaudi + «г»: ink 270 vs br 266.8; sweep: 30/60 красных кейсов).

**Причины** (всё было подтверждено оффскрин-пробами до правки):
1. **Метрика**: `shrink_height` мерял tight-bottom базовой строки «木fg», а не реальный
   инк. В большинстве из 330 шрифтов base bottom = 2–8px, тогда как обычные глифы
   уходят ниже на 1–17px; компенсировались только 8 хардкод-букв (`_DESCENDER_CHARS`).
   После shrink/grow S ≤ target, но инк = S + дефицит > target → клип.
2. **Grow-переполнение**: `FontAutoAdjuster.grow()` мог остановиться на шрифте,
   который уже не влезает (shrink_height не монотонен по размеру из-за перефлоу).
3. **Geometry**: `_update_display_rect_from_control_points` не двигал `y` (всегда 0) —
   при `min_y < 0` (Qt уважает отрицательный documentMargin, показано пробом) базовый
   rect/пиксмап отставали от текста (клиппинг спасал union boundingRect с CP-rect).

**Правки**:
- `ui/scene_textlayout.py` — `layoutBlock`: `shrink_height` = максимум
  `line.naturalTextRect().bottom()` (что реально рисует Qt, включая fallback-глифы);
  удалены `_DESCENDER_BASE_STR`/`_DESCENDER_CHARS`/`_descender_gap()` (эвристика
  заменена честным измерением).
- `ui/font_auto_adjuster.py` — `grow()`: при переполнении после шага grow
  пропорциональное масштабирование к границе (`factor = target/extent · 0.999`)
  + подтверждающий shrink 0.95 (немоноотонный reflow). (v1 — откат к
  `last_good_size` — заменён: он оставлял шрифт на шаг 8% меньше влезшего.)
- `ui/flow_textitem.py` — `commit_flow_geometry()`: единая воронка
  `prepareGeometryChange()` → display-rect → `save_flow_points` → `sync_coordinates`
  (все мутаторы геометрии идут через неё, в т.ч. `_update_flow_layout` и
  `repaint_background` после коммита); `_update_display_rect_from_control_points`:
  `setY(doc_margin)` (width/height сохраняют конвенцию «display-rect содержит
  padding», её вычитают потребители, напр. `absBoundingRect`).

**Тесты**: `tests/ui/test_flow_resize_bottom_clip.py` (12 тестов: красные кейсы
A.C.M.E/г, BOMGcom004/д, BOMGcomPsuedoSaudi/г, v_Blambot Casual MOD/щ,
fallback-кейс, отрицательные CP). Фикстура регистрирует только 4 нужных шрифта
(addApplicationFont необратим — масса шрифтов смещает fallback у других тестов).
Толеранс осцилляции в `test_multiple_resizes_no_oscillation` 1.0→2.0pt
(конвергенция-грид сместился: shrink останавливается на S ≤ target, grow — на
S ≥ 0.9·target — по дизайну).

**Регрессия того же дня (поймана пользователем: «шрифт везде меньше, чем
должен»)**: промежуточная метрика была `y_offset + dy + naturalTextRect().bottom()`
— двойной учёт позиции строки (`naturalTextRect()` возвращается в АБСОЛЮТНЫХ
координатах лейаута: его `top() == line.position().y()`). `shrink_height`
раздувался ~в 2 раза на многострочных блоках → авторазмер давал шрифт вдвое
меньше. Исправлено: `ink_bottom = ntr.bottom()` без `y_offset + dy`. A/B с
HEAD-`FontAutoAdjuster` подтвердил: при честной метрике 5/6 кейсов дают
идентичные размеры, а в width-ограниченном старая `grow()` оставляла текст в
переполнении (S=125.4 > target=120) — т.е. исходный баг вылезания за линию.
Попутно поправлен контракт `test_layout_metric_covers_ink`: текст в flow-блоках
всегда центрируется (`VERTICAL_CENTER` + `_vertical_center_always`), сдвиг
`(max_height − S)/2 − dm` добавляется к ink ПОСЛЕ расчёта `shrink_height`;
test учитывает сдвиг (раньше проходил только благодаря раздутой метрике —
ложная позитивность).
