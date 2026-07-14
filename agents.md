# Agents

## Available Agents

### build (default)
Full tool access. Runs code changes, edits files, executes commands. This is the default agent.

### plan
Read-only design mode. Only writes to `.mimocode/plans/*.md`. Use for architecture decisions and planning before implementation.

### explore
Fast, read-only codebase explorer. Use for searching code, finding definitions, understanding patterns. Only has read/grep/glob/bash tools.

### general
General-purpose worker for multi-step tasks. Inherits parent's working directory.

## Rules

### Run tests after changes

**Always run tests after modifying code:**

```bash
# Flow text item tests (60+ tests)
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py -v

# All UI tests
myenv\Scripts\python -m pytest tests/ui/ -v

# Full test suite
myenv\Scripts\python -m pytest -v
```

**When to run tests:**
- After any code change in `ui/`, `modules/`, `utils/`
- After fixing a bug
- After adding new functionality
- Before committing changes

**Test conventions:**
- Tests use `QT_QPA_PLATFORM=offscreen` (set automatically in conftest)
- Virtual env: `myenv\Scripts\python`
- Windows/PowerShell: use `;` not `&&`

### One change at a time

Make one change, run tests, verify, then proceed to next change. Do not batch multiple unrelated changes.

### Commit before git operations

User prefers to commit uncommitted changes rather than stash before git operations.

### FontFormat attribute names

`FontFormat` uses `font_size` (in pixels), NOT `size`. Convert with `pt2px()` from `utils.fontformat`. The `size_pt` property returns points. Never use `fontformat.size` — it doesn't exist as a defined attribute.

### QUIET_UI flag

Each UI file (`flow_textitem.py`, `flow_shapecontrol.py`, `scenetext_manager.py`, `scene_textlayout.py`) has `QUIET_UI = True` at the top. Set to `False` for verbose debug logging. All `LOGGER.debug` calls go through `_debug()` wrapper that checks this flag.

### Log filtering

When debugging shrink/grow issues, filter logs by block text prefix:
```python
_LOG_PREFIXES = ("БЫСТРЕЕ", "60 МИЛЬ В ЧАС")
```

### Type annotations

Use type annotations wherever possible — function signatures, return types, variables with non-obvious types. Prefer `typing` module types (`List`, `Dict`, `Optional`, `Tuple`, `Union`) for compatibility with Python 3.10. Every new function MUST have type hints on parameters and return value.

## Architecture Notes

### Pipeline Architecture
BallonsTranslator uses a modular pipeline with 4 stages:
1. **Text Detection** → finds text regions on page images
2. **OCR** → recognizes text in detected regions
3. **Translation** → translates recognized text
4. **Inpainting** → erases original text from image

Each stage is a pluggable module registered via `Registry` pattern (`utils/registry.py`).

### Flow Text Layout

- `ui/flow_textitem.py` — FlowTextBlkItem with auto-shrink/grow
- `ui/scene_textlayout.py` — HorizontalTextDocumentLayout with boundary functions
- `ui/textitem.py` — Base TextBlkItem class
- `ui/scenetext_manager.py` — layout_textblk, _find_best_font_size
- **Полный справочник**: `.claude/skills/flow-blocks/SKILL.md` — все вызовы `_update_flow_layout()`, known bugs, паттерны

### Key Metrics

- `layout.shrink_height` — actual text extent within boundaries (USE THIS)
- `layout.shrink_width` — actual text width within boundaries
- `document().size().height()` — Qt document height (DO NOT USE for flow layout)

### Auto-adjust Flag

- `_auto_font_adjust = True` — shrink/grow runs on resize
- `_auto_font_adjust = False` — shrink/grow suppressed (during binary search)
- `set_size(auto_font_adjust=False)` — temporarily overrides without permanent change

### Critical: reLayout() modifies available_height

**This is the #1 source of bugs:**
- `SceneTextLayout.reLayout()` expands `self.available_height = new_height` when text overflows
- After `setRelFontSize()` → `reLayoutEverything()` → `reLayout()`, the constraint is gone
- **Always reset** `layout.available_height` and `layout.max_height` to target values AFTER any font-size-change call, before reading `shrink_height`

### Data Flow: TextBlock as Single Source of Truth

- `TextBlock` (data model) → single source for translation/source text
- `TextBlkItem` (canvas) and `TransPairWidget` (right panel) are views
- Sync via `_sync_translation_to_ui()` and `_sync_source_to_ui()` in `scenetext_manager.py`
- Undo/redo via widget undo stacks, not direct state manipulation

### Module Auto-Discovery

Files named `detector_<name>.py`, `ocr_<name>.py`, `translator_<name>.py`, `inpaint_<name>.py` are auto-imported and registered.

## Known Bugs and Fixes

See `BUGS_FLOW_TEXT_SIZING.md` for flow text font sizing issues.
See `BUGS_ANALYSIS.md` (main-Refactor branch) for canvas UI bugs.

### _auto_font_adjust stuck at False (fixed)

**Root cause:** `FlowTextBlkItem.setFontSize()` unconditionally set `_auto_font_adjust = False`, even when called internally by `_auto_shrink_font()`/`_auto_grow_font()` via `setRelFontSize()`. This permanently disabled auto-adjust after the first layout — shrink/grow never ran on subsequent handle drags or resizes.

**Fix:** Added `_internal_font_change` guard flag. `setFontSize()` only resets `_auto_font_adjust` when NOT an internal change. Shrink/grow wrap their `setRelFontSize()` calls with this guard.

**Lesson:** When adding override methods that modify flags, consider whether internal callers (shrink/grow) should trigger the same behavior as external callers (toolbar).

### Tips for debugging shrink/grow

- Filter logs by block text prefix (`_LOG_PREFIXES`) to isolate target blocks
- Use `layout.shrink_height` (actual text extent), NOT `document().size().height()` (Qt doc height is wrong for flow layout)
- After any `setRelFontSize()` call, `reLayout()` expands `available_height` — reset it before reading metrics
- `_has_char_level_breaks` is set inside `layoutBlock()` per layout pass — check it inside the shrink/grow loop, not before

## Testing Commands

```bash
# Run specific test file
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py -v

# Run with output capture disabled
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py -v -s

# Run specific test class
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py::TestAutoShrink -v

# Run specific test
myenv\Scripts\python -m pytest tests/ui/test_flow_textitem.py::TestBinarySearchFontSizing::test_bystre_block_gets_reasonable_font -v
```
