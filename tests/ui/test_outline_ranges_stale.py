"""
Invalidation of stale per-selection outline ranges after block text edits.

Bug: when the user edits a block's text, blk.outline_ranges was NOT
invalidated. _stroke_groups() clamped the stale range to the new document
length (e.g. a stale [0, 50] in an 8-char document became (0, 8)), so the
WHOLE remaining text got the foreign outline (old color/width), and
get_selection_outline() kept returning the stale values to the panel.

Fix under test:
1. set_selection_outline() snapshots the clean document text after every
   successful mutation (SET / REMOVE width<0 / COLOR branches).
2. Read-time validation: _stroke_groups()/get_selection_outline() treat
   blk.outline_ranges as EMPTY when the clean text no longer matches the
   snapshot (fall back to the block-level stroke). The snapshot lives in
   memory only, so after a project reload (snapshot None) the persisted
   ranges are accepted — safe, because hyphenation is deterministic for
   unchanged text.
3. Text-change hook: setPlainText()/setHtml() overrides in TextBlkItem
   (FlowTextBlkItem calls super(), so the flow path is covered too) clear
   blk.outline_ranges and the snapshot when the clean text differs. The
   initial load in __init__ is NOT affected (snapshot None → ranges
   accepted).

Run with:
    set QT_QPA_PLATFORM=offscreen
    myenv\\Scripts\\python -m pytest tests/ui/test_outline_ranges_stale.py -v
"""

import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

# Qt imports — must happen AFTER setting the platform (conftest.py does the
# same; kept here so the module also works standalone).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtGui import QTextCursor

from utils.textblock import TextBlock
from ui.textitem import TextBlkItem
from ui.flow_textitem import FlowTextBlkItem


# ── Helpers (qapp/scene fixtures — tests/ui/conftest.py) ───────

def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world", font_size=24.0) -> TextBlock:
    """Helper: create a TextBlock with sensible defaults."""
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    # Set _bounding_rect to avoid going through min_rect (needs lines)
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_flow_item(scene, text: str = "Hello world") -> FlowTextBlkItem:
    """Helper: FlowTextBlkItem (document contains soft hyphens)."""
    blk = _make_blk(text=text)
    item = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _make_plain_item(scene, text: str = "Hello world") -> TextBlkItem:
    """Helper: plain TextBlkItem (no soft hyphens in the document)."""
    blk = _make_blk(text=text)
    item = TextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _select(item, s: int, e: int) -> None:
    cur = item.textCursor()
    cur.setPosition(s)
    cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
    item.setTextCursor(cur)


def _clean(item) -> str:
    """Item document text without soft hyphens."""
    return item.document().toPlainText().replace('\u00ad', '')


# ── Tests ─────────────────────────────────────────────────────

class TestTextChangeHook:
    """setPlainText/setHtml overrides clear stale outline ranges."""

    def test_stale_ranges_cleared_on_set_plain_text(self, scene):
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        assert item.set_selection_outline(width=0.5, srgb=[255, 0, 0])
        assert item.blk.outline_ranges == [[0, 5, 0.5, [255, 0, 0]]]
        assert item._outline_clean_text == "Hello world"

        item.setPlainText('brand new text')

        # data model cleaned up
        assert item.blk.outline_ranges == []
        assert item._outline_clean_text is None
        # rendering: no range group at all (block stroke is 0)
        assert item._stroke_groups() == {}
        # panel: a selection on the NEW text has no outline
        _select(item, 0, 5)
        assert item.get_selection_outline() is None

    def test_new_range_after_edit_works(self, scene):
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])
        item.setPlainText('brand new text')
        assert item.blk.outline_ranges == []

        # a new range on the new text must work as usual
        _select(item, 0, 5)
        assert item.set_selection_outline(width=0.4, srgb=[1, 2, 3])
        s, e, w, c = item.blk.outline_ranges[0]
        assert (w, c) == (0.4, [1, 2, 3])
        assert _clean(item)[s:e] == 'brand'
        assert item._outline_clean_text == 'brand new text'

        groups = item._stroke_groups()
        assert len(groups) == 1
        key = list(groups)[0]
        assert key[1] == (1, 2, 3)  # per-range color
        assert groups[key] == [(s, e)]
        assert item.get_selection_outline() == (0.4, [1, 2, 3])

    def test_unchanged_text_keeps_ranges(self, scene):
        """No false invalidation: re-setting the SAME text (deterministic
        hyphenation) must keep the ranges applied."""
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])
        before = copy.deepcopy(item.blk.outline_ranges)
        snapshot = item._outline_clean_text

        item.setPlainText("Hello world")

        assert item.blk.outline_ranges == before
        assert item._outline_clean_text == snapshot
        groups = item._stroke_groups()
        assert len(groups) == 1
        assert list(groups.values())[0] == [(0, 5)]
        _select(item, 0, 5)
        assert item.get_selection_outline() == (0.5, [255, 0, 0])

    def test_plain_textitem_cleared_on_set_plain_text(self, scene):
        item = _make_plain_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])
        assert item.blk.outline_ranges == [[0, 5, 0.5, [255, 0, 0]]]

        item.setPlainText('brand new text')

        assert item.blk.outline_ranges == []
        assert item._outline_clean_text is None
        assert item._stroke_groups() == {}
        _select(item, 0, 5)
        assert item.get_selection_outline() is None

    def test_set_html_cleared_on_text_change(self, scene):
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])

        item.setHtml('<html><body>brand new text</body></html>')

        assert item.blk.outline_ranges == []
        assert item._outline_clean_text is None
        assert item._stroke_groups() == {}

    def test_color_branch_snapshot(self, scene):
        """COLOR branch (width=None, srgb set) also saves the snapshot, so a
        later text edit invalidates the color-changed range."""
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])  # SET
        assert item.set_selection_outline(srgb=[9, 9, 9])        # COLOR
        assert item.blk.outline_ranges == [[0, 5, 0.5, [9, 9, 9]]]
        assert item._outline_clean_text == "Hello world"
        # text untouched → ranges still applied
        assert list(item._stroke_groups().values())[0] == [(0, 5)]

        item.setPlainText('brand new text')
        assert item.blk.outline_ranges == []

    def test_remove_branch_snapshot(self, scene):
        """REMOVE branch (width<0) also saves the snapshot; a later text
        edit is then a clean no-op."""
        item = _make_flow_item(scene, text="Hello world")
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])
        assert item.set_selection_outline(width=-1.0)  # REMOVE sentinel
        assert item.blk.outline_ranges == []
        assert item._outline_clean_text == "Hello world"

        item.setPlainText('brand new text')
        assert item.blk.outline_ranges == []
        assert item._outline_clean_text is None


class TestReadTimeValidation:
    """_stroke_groups/get_selection_outline treat stale ranges as empty
    even when the text change bypassed the setPlainText/setHtml hook
    (typing, undo/redo, direct document edits)."""

    def test_stale_large_range_does_not_paint_whole_text(self, scene):
        """The reported bug: a stale [0, 50] in an 8-char document used to
        be clamped to (0, 8) — the whole remaining text got the foreign
        outline. With a mismatching snapshot it must be ignored."""
        item = _make_plain_item(scene, text="12345678")
        item.fontformat.stroke_width = 0.3
        item.blk.outline_ranges = [[0, 50, 0.5, [255, 0, 0]]]
        # snapshot says the ranges were set against a longer text
        item._outline_clean_text = "a much longer original text"

        n = item.document().rootFrame().lastPosition()
        groups = item._stroke_groups()
        # no stale range group (color 255,0,0)
        assert all(c != (255, 0, 0) for (_w, c) in groups)
        # block-level stroke covers the whole (new) document
        assert [(0, n)] in groups.values()

    def test_get_selection_outline_stale(self, scene):
        item = _make_plain_item(scene, text="12345678")
        item.blk.outline_ranges = [[0, 5, 0.5, [255, 0, 0]]]
        item._outline_clean_text = "a much longer original text"
        _select(item, 0, 5)
        # stale → panel gets nothing (not the stale value)
        assert item.get_selection_outline() is None
        # snapshot matches → the range is reported again
        item._outline_clean_text = "12345678"
        assert item.get_selection_outline() == (0.5, [255, 0, 0])

    def test_typed_text_change_falls_back_to_block_stroke(self, scene):
        item = _make_flow_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.3
        _select(item, 0, 5)
        item.set_selection_outline(width=0.5, srgb=[255, 0, 0])

        # simulate typing: direct document edit (bypasses setPlainText)
        cur = QTextCursor(item.document())
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText('typed replacement text')

        # the hook did not run — ranges persist in the model but must be
        # treated as empty at read time
        assert item.blk.outline_ranges == [[0, 5, 0.5, [255, 0, 0]]]
        n = item.document().rootFrame().lastPosition()
        groups = item._stroke_groups()
        assert all(c != (255, 0, 0) for (_w, c) in groups)
        assert [(0, n)] in groups.values()
        _select(item, 0, 5)
        assert item.get_selection_outline() is None

        # a subsequent setPlainText (same clean text) clears the stale
        # ranges for good
        item.setPlainText(_clean(item))
        assert item.blk.outline_ranges == []
        assert item._outline_clean_text is None


class TestReloadAcceptsPersistedRanges:
    """The snapshot lives in memory only: after a project reload (new item,
    snapshot None) the persisted ranges are accepted — safe, because
    hyphenation is deterministic for unchanged text."""

    def test_flow_item_persisted_ranges_accepted(self, scene):
        blk = _make_blk(text="Hello world")
        blk.outline_ranges = [[0, 5, 0.5, [255, 0, 0]]]
        item = FlowTextBlkItem(blk, idx=0, show_rect=False)
        scene.addItem(item)
        assert item._outline_clean_text is None
        groups = item._stroke_groups()
        assert len(groups) == 1
        assert list(groups.values())[0] == [(0, 5)]

    def test_plain_item_persisted_ranges_accepted(self, scene):
        item = _make_plain_item(scene, text="Hello world")
        item.blk.outline_ranges = [[0, 5, 0.5, [255, 0, 0]]]
        assert item._outline_clean_text is None
        groups = item._stroke_groups()
        assert len(groups) == 1
        assert list(groups.values())[0] == [(0, 5)]
