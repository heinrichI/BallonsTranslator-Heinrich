"""
Tests for task10: auto-placed blocks with a border (stroke) are switched to
the rectangular view and skip the overlap (intersection) check.

Run with:
    set QT_QPA_PLATFORM=offscreen
    cd j:\Comic translate\BallonsTranslator
    myenv/Scripts/python.exe -m pytest tests/ui/test_stroke_rect_on_autolayout.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

# Qt imports — must happen AFTER setting platform, so we force it here
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace, MethodType
from unittest.mock import MagicMock

from utils.textblock import TextBlock
from ui.textitem import TextBlkItem
from ui.flow_textitem import FlowTextBlkItem
from ui.scenetext_manager import SceneTextManager, apply_stroke_rect_override


# ── Helpers (qapp/scene fixtures — tests/ui/conftest.py) ───────

def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0,
              stroke_width=0.0, vertical=False):
    """Helper: create a TextBlock with sensible defaults (flow mode on)."""
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk.fontformat.vertical = vertical
    blk.fontformat.stroke_width = stroke_width
    blk.is_flow_mode = True
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


# ── apply_stroke_rect_override (model marking) ─────────────────

class TestApplyStrokeRectOverride:

    def test_stroked_block_becomes_rect(self):
        blk = _make_blk(stroke_width=0.1)
        apply_stroke_rect_override([blk])
        assert blk.is_flow_mode is False

    def test_stroked_vertical_block_becomes_rect(self):
        """Vertical blocks are converted too (border renders poorly in flow)."""
        blk = _make_blk(stroke_width=0.05, vertical=True)
        apply_stroke_rect_override([blk])
        assert blk.is_flow_mode is False

    def test_block_without_stroke_stays_flow(self):
        blk = _make_blk(stroke_width=0.0)
        apply_stroke_rect_override([blk])
        assert blk.is_flow_mode is True

    def test_none_stroke_treated_as_zero(self):
        blk = _make_blk()
        blk.stroke_width = None  # e.g. missing in an old project file
        apply_stroke_rect_override([blk])
        assert blk.is_flow_mode is True

    def test_flow_points_kept_on_model(self):
        """Rect conversion must not destroy saved flow control points —
        toggling back to flow later restores them."""
        blk = _make_blk(stroke_width=0.1)
        blk.left_points = [[0, 0], [0, 100], [0, 200]]
        blk.right_points = [[400, 0], [400, 100], [400, 200]]
        apply_stroke_rect_override([blk])
        assert blk.is_flow_mode is False
        assert blk.left_points == [[0, 0], [0, 100], [0, 200]]
        assert blk.right_points == [[400, 0], [400, 100], [400, 200]]

    def test_empty_list_is_noop(self):
        apply_stroke_rect_override([])  # must not raise


# ── _resolve_overlaps guard (skip intersection check) ──────────

class TestResolveOverlapsSkipsStroked:

    def test_stroked_block_skips_resolver(self, scene):
        blk = _make_blk(stroke_width=0.1)
        blk.is_flow_mode = False
        item = TextBlkItem(blk, idx=0, show_rect=False)
        scene.addItem(item)
        resolver = MagicMock()
        fake = SimpleNamespace(textblk_item_list=[item], overlap_resolver=resolver)
        SceneTextManager._resolve_overlaps(fake, item)
        resolver.resolve_overlaps.assert_not_called()

    def test_unstroked_flow_block_still_resolves(self, scene):
        blk = _make_blk(stroke_width=0.0)
        item = FlowTextBlkItem(blk, idx=0, show_rect=False)
        scene.addItem(item)
        resolver = MagicMock()
        fake = SimpleNamespace(textblk_item_list=[item], overlap_resolver=resolver)
        SceneTextManager._resolve_overlaps(fake, item)
        resolver.resolve_overlaps.assert_called_once_with(item, [item])


# ── addTextBlock integration (pipeline marking → rect item) ────

class TestAddTextBlockCreatesRectForStroked:
    """End-to-end: a model block marked by the pipeline override
    (is_flow_mode=False, stroke set) comes out of addTextBlock as a plain
    TextBlkItem, and no overlap resolution is requested for it."""

    def _fake_manager(self, auto_layout_flag):
        canvas = SimpleNamespace(
            textblock_mode=False,
            add_item_to_text_layer=MagicMock(),
        )
        fake = SimpleNamespace(
            auto_textlayout_flag=auto_layout_flag,
            canvas=canvas,
            textblk_item_list=[],
            layout_textblk=lambda item, text=None: True,
            pair_wiring=SimpleNamespace(wire_signals=MagicMock()),
            pairwidget_list=[],
            textEditList=SimpleNamespace(addPairWidget=MagicMock()),
            new_textblk=SimpleNamespace(emit=lambda *a, **k: None),
            overlap_resolver=MagicMock(),
        )
        for name in [
            "onTextBlkItemBeginEdit", "onTextBlkItemEndEdit", "onTextBlkItemHoverEnter",
            "onLeftbuttonPressed", "onTextBlkItemMoving", "onTextBlkItemMoved",
            "onTextBlkItemReshaped", "onTextBlkItemRotated", "on_push_textitem_undostack",
            "on_textedit_undo", "on_textedit_redo", "on_propagate_textitem_edit",
            "onTextBlkItemSizeChanged", "onBlkitemPaste", "toggle_block_flow_mode",
        ]:
            setattr(fake, name, MagicMock())
        fake.addTextBlkItem = MethodType(SceneTextManager.addTextBlkItem, fake)
        fake._resolve_overlaps = MethodType(SceneTextManager._resolve_overlaps, fake)
        fake.addTextBlock = MethodType(SceneTextManager.addTextBlock, fake)
        return fake

    def test_stroked_marked_block_creates_text_blk_item(self, scene):
        blk = _make_blk(stroke_width=0.1)
        apply_stroke_rect_override([blk])  # what on_pagtrans_finished does
        assert blk.is_flow_mode is False
        fake = self._fake_manager(auto_layout_flag=True)
        item = fake.addTextBlock(blk)
        scene.addItem(item)
        assert isinstance(item, TextBlkItem) and not isinstance(item, FlowTextBlkItem)
        fake.overlap_resolver.resolve_overlaps.assert_not_called()

    def test_unstroked_block_still_flow(self, scene):
        blk = _make_blk(stroke_width=0.0)
        fake = self._fake_manager(auto_layout_flag=True)
        item = fake.addTextBlock(blk)
        scene.addItem(item)
        assert isinstance(item, FlowTextBlkItem)

    def test_page_load_keeps_model_state(self, scene):
        """Page load (auto-layout flag off) does not convert anything by
        itself; a model mark made by a previous pipeline run still yields a
        rect item."""
        blk = _make_blk(stroke_width=0.1)
        blk.is_flow_mode = False  # marked by a previous pipeline run
        fake = self._fake_manager(auto_layout_flag=False)
        item = fake.addTextBlock(blk)
        scene.addItem(item)
        assert isinstance(item, TextBlkItem) and not isinstance(item, FlowTextBlkItem)
