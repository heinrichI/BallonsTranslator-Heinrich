# Implementation Plan — Syllable-Based Line Breaking with Visible Hyphen for FlowTextBlkItem (Russian)

## Overview

Add visible hyphenation for Russian text in FlowTextBlkItem: when a long word overflows the line width, split it at syllable boundaries and insert visible hyphen + newline (`-\n`). Only split when necessary — if word fits, no hyphen is shown. Falls back to font shrinking if even a single syllable doesn't fit remaining space.

## Approach

Current flow (`WrapAtWordBoundaryOrAnywhere`):
1. Qt breaks only at spaces or arbitrary character boundaries (no visible hyphen)
2. If long word doesn't fit, auto-shrink reduces font size → wasted space

New flow:
1. Qt layouts text normally (unchanged)
2. After layout + auto-shrink/grow, scan each line for overflow
3. For each overflowing line: find last word, split by syllables (pyphen), insert `-\n`
4. Relayout with modified text
5. If hyphenation alone doesn't fit → auto-shrink still handles it

## Types

No new types.

## Files

- **Modified**: `ui/flow_textitem.py`
  - Remove soft-hyphen injection from `setPlainText()` — revert `super().setPlainText(text)` 
  - Keep `_get_pyphen()` cache (already exists)
  - Add `_hyphenate_russian_word(word: str) -> List[str]` — splits word into syllable list
  - Add `_hyphenating` guard flag in `__init__`
  - Add `_hyphenate_overflow_lines() -> bool` — main hyphenation logic
  - Call it from `_update_flow_layout()` after auto-shrink/grow

- **Modified**: `tests/ui/test_flow_textitem.py`
  - Update tests for new syllable-list approach

## Functions

### New
1. `_hyphenate_russian_word(word: str) -> List[str]` in `ui/flow_textitem.py`
   - Returns list of syllable strings: "перенос" → ["пе", "ре", "нос"]
   - Non-cyrillic words return `[word]`
   - Short words (<5 chars) return `[word]`

2. `FlowTextBlkItem._hyphenate_overflow_lines() -> bool` in `ui/flow_textitem.py`
   - Guard: skip if `_hyphenating` is True (prevents recursion)
   - Walk all lines in the layout
   - For each line: check if `naturalTextWidth > line_width`
   - If overflowing:
     - Get last word (text after last space)
     - Split into syllables via `_hyphenate_russian_word()`
     - Try inserting first syllable + `-\n`; if first syllable overflows → skip (let shrink handle)
     - Insert remaining syllables as a new line
   - If any change: set modified text, reapply boundary functions, reLayout
   - Return True if changes made
   - Set `_hyphenating = True` during execution

### Modified
1. `FlowTextBlkItem.setPlainText(text: str)` in `ui/flow_textitem.py`
   - **Remove**: `text = _hyphenate_russian(text)` call
   - **Revert to**: `super().setPlainText(text)` (no hyphenation at setPlainText time)

2. `FlowTextBlkItem.__init__()` in `ui/flow_textitem.py`
   - Add: `self._hyphenating: bool = False`

3. `FlowTextBlkItem._update_flow_layout()` in `ui/flow_textitem.py`
   - After `_auto_shrink_font()` + `_auto_grow_font()` block, add call to `_hyphenate_overflow_lines()`

## Classes

No new or modified classes.

## Dependencies

- `pyphen>=0.14.0` (already in requirements.txt)

## Testing

- **Modified**: `tests/ui/test_flow_textitem.py`
  - Remove old `TestHyphenation` class (soft-hyphen tests)
  - Add new `TestHyphenation` class:
    - `test_word_syllables` — "перенос" → ["пе", "ре", "нос"]
    - `test_short_word` — "дом" → ["дом"]
    - `test_non_cyrillic` — "hello" → ["hello"]
    - `test_overflow_inserts_hyphen` — narrow block + long Russian word → text contains "-\n"
    - `test_no_change_when_fits` — wide block + long word → no change

## Implementation Order

1. Revert `setPlainText()` — remove soft-hyphen call, keep `super().setPlainText(text)`
2. Add `_hyphenating` flag in `__init__`
3. Add `_hyphenate_russian_word()` helper function
4. Add `_hyphenate_overflow_lines()` method
5. Wire into `_update_flow_layout()` after shrink/grow
6. Run existing tests (16) to verify no regression
7. Update hyphenation tests for new approach
8. Run all tests to verify