"""
Regression tests: the block re-layout contract (_update_block_layout) must
work for PLAIN rectangular TextBlkItem, not only for FlowTextBlkItem.

Historically the auto-layout paths called FlowTextBlkItem._update_flow_layout
unconditionally, which raised AttributeError on plain blocks
(error27.txt: 'TextBlkItem' object has no attribute '_update_flow_layout').

Run with:
    set QT_QPA_PLATFORM=offscreen
    cd j:/Comic translate/BallonsTranslator
    myenv/Scripts/python.exe -m pytest tests/ui/test_plain_block_layout.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Qt imports — must happen AFTER setting platform, so we force it here
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from unittest.mock import MagicMock

from utils.config import pcfg
from utils.textblock import TextBlock
from ui.textitem import TextBlkItem
from ui.flow_textitem import FlowTextBlkItem
from ui.text_layout_manager import TextLayoutManager


# ── Helpers (qapp/scene fixtures — tests/ui/conftest.py) ───────

def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world", font_size=24.0):
    """Helper: create a TextBlock with sensible defaults."""
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_plain_item(scene, xyxy=(0, 0, 400, 200), text="Hello world", font_size=24.0):
    """Helper: create a PLAIN TextBlkItem added to the given scene."""
    blk = _make_blk(xyxy, text, font_size)
    item = TextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


@pytest.fixture
def auto_layout_flags():
    """Force auto font-sizing mode (the mode that reaches _auto_layout)."""
    orig = (pcfg.let_fntsize_flag, pcfg.let_autolayout_flag)
    pcfg.let_fntsize_flag = 0
    pcfg.let_autolayout_flag = True
    yield
    pcfg.let_fntsize_flag, pcfg.let_autolayout_flag = orig


# ── Site 1: TextLayoutManager._auto_layout (error27 crash) ─────

class TestAutoLayoutPlainItem:
    """_auto_layout must not assume flow-only APIs (error27 regression)."""

    def test_layout_textblk_plain_block_no_attribute_error(self, scene, auto_layout_flags):
        # 3 lines at 120pt (~160px each) cannot fit a 200px-tall block —
        # forces the binary search + the final shrink pass.
        text = "Hello world\nsecond line\nthird line"
        item = _make_plain_item(scene, text=text, font_size=120.0)
        mgr = TextLayoutManager(pcfg)
        mgr.auto_textlayout_flag = True

        img = np.zeros((300, 500, 3), dtype=np.uint8)
        result = mgr.layout_textblk(item, text=text, img_array=img)

        assert result == text  # None would mean "layout failed"
        # The shrink pass must have actually run (not silently skipped):
        assert item.font().pointSizeF() < 120.0
        target_h = item.absBoundingRect(qrect=True).height()
        assert item.layout.shrink_height <= target_h * 1.1

    def test_layout_textblk_flow_block_still_works(self, scene, auto_layout_flags):
        """Flow path parity: same entry point, flow item."""
        text = "Hello world\nsecond line\nthird line"
        blk = _make_blk(text=text, font_size=120.0)
        item = FlowTextBlkItem(blk, idx=0, show_rect=False)
        scene.addItem(item)

        mgr = TextLayoutManager(pcfg)
        mgr.auto_textlayout_flag = True

        img = np.zeros((300, 500, 3), dtype=np.uint8)
        result = mgr.layout_textblk(item, text=text, img_array=img)

        assert result == text
        assert item.font().pointSizeF() < 120.0


# ── Site 2: RunBlkTransCommand.__init__ pre-layout ────────────

class TestRunBlkTransCommandPlainItem:
    """Command pre-layout (drawing_commands) must work for plain blocks."""

    def test_init_plain_block_no_attribute_error(self, scene, auto_layout_flags):
        from ui.drawing_commands import RunBlkTransCommand

        # 180pt (~240px) single line overflows the 200px block → shrink.
        item = _make_plain_item(scene, text="Source text", font_size=180.0)
        item.blk.translation = "Translated words"

        canvas = MagicMock()  # mode=1: never called, only stored
        st_manager = MagicMock()
        st_manager.layout_manager = TextLayoutManager(pcfg)
        st_manager.formatpanel.global_format.letter_spacing = 0.0
        st_manager.formatpanel.global_format.font_family = "Arial"
        transpairw = MagicMock()

        cmd = RunBlkTransCommand(canvas, [item], [transpairw], mode=1, st_manager=st_manager)

        # The needs_layout branch must have run and produced layout data
        # (None would mean the "target too small" fallback).
        assert len(cmd.layout_data) == 1
        ld = cmd.layout_data[0]
        assert ld is not None
        assert ld["new_font_size"] < 180.0
        # Post-layout validation: the text fits the block.
        assert item.layout.shrink_height <= ld["new_h"] * 1.1


# ── Contract: _update_block_layout semantics ──────────────────

class TestUpdateBlockLayoutContract:

    def test_plain_flag_reset_after_layout(self, scene):
        """Parity with flow: adjust_font=True re-arms _auto_font_adjust."""
        item = _make_plain_item(scene)
        item._auto_font_adjust = False
        item._update_block_layout()
        assert item._auto_font_adjust is True

    def test_plain_flag_reset_respects_global_flag(self, scene):
        """"Font Size: use global setting" (let_fntsize_flag=1) wins."""
        item = _make_plain_item(scene)
        orig = pcfg.let_fntsize_flag
        try:
            pcfg.let_fntsize_flag = 1
            item._auto_font_adjust = True
            item._update_block_layout()
            assert item._auto_font_adjust is False
        finally:
            pcfg.let_fntsize_flag = orig

    def test_plain_adjust_font_false_is_noop(self, scene):
        """adjust_font=False: no font pass, no flag re-arm (flow parity)."""
        item = _make_plain_item(scene)
        before = item.font().pointSizeF()
        item._auto_font_adjust = False
        item._update_block_layout(adjust_font=False)
        assert item.font().pointSizeF() == before
        assert item._auto_font_adjust is False

    def test_flow_delegates_to_update_flow_layout(self, scene):
        """Flow override delegates with the adjust_font argument."""
        blk = _make_blk()
        item = FlowTextBlkItem(blk, idx=0, show_rect=False)
        scene.addItem(item)

        calls = []
        item._update_flow_layout = lambda adjust_font=True: calls.append(adjust_font)
        item._update_block_layout(adjust_font=True)
        item._update_block_layout(adjust_font=False)
        assert calls == [True, False]
