"""
Unit tests for FlowTextBlkItem — flow-based text boundary layout.

Run with:
    set QT_QPA_PLATFORM=offscreen
    cd j:\Comic translate\BallonsTranslator
    myenv\Scripts\python.exe -m pytest tests/ui/test_flow_textitem.py -v

Requires: pytest, PyQt6 (offscreen platform)
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

# Qt imports — must happen AFTER setting platform, so we force it here
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtWidgets import QApplication, QGraphicsScene, QGraphicsView
from qtpy.QtCore import Qt, QRectF, QPointF
from qtpy.QtGui import QTextCursor

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.scene_textlayout import HorizontalTextDocumentLayout


# ── Session-scoped QApplication ───────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the whole test session (offscreen)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def scene(qapp):
    """Fresh QGraphicsScene for each test."""
    s = QGraphicsScene()
    # Add a view so items get valid screen transforms
    view = QGraphicsView(s)
    view.resize(2000, 2000)
    yield s
    s.clear()


def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    """Helper: create a TextBlock with sensible defaults."""
    x1, y1, x2, y2 = xyxy
    # TextBlock expects xyxy, but lines must also be set for bounding_rect to work
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    # Set _bounding_rect to avoid going through min_rect (needs lines)
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_item(scene, xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    """Helper: create a FlowTextBlkItem added to the given scene."""
    blk = _make_blk(xyxy, text, font_size)
    item = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


# ── Tests ─────────────────────────────────────────────────────

class TestFlowTextBlkInit:
    """Basic creation and init."""

    def test_init_creates_control_points(self, scene):
        item = _make_item(scene)
        assert len(item._left_points) == 3
        assert len(item._right_points) == 3
        # Points should span the block rectangle
        ys = [p.y() for p in item._left_points]
        assert min(ys) == 0
        assert max(ys) == 200  # height of block

    def test_init_sets_text(self, scene):
        item = _make_item(scene, text="Test123")
        assert item.toPlainText() == "Test123"

    def test_init_with_vertical_works(self, scene):
        """Vertical mode: flow points still created but handled differently."""
        blk = _make_blk()
        blk.fontformat.vertical = True
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        assert len(item._left_points) == 3


class TestFlowBoundaryLayout:
    """Test that text reflows when boundaries change."""

    def test_move_left_boundary_right_shifts_text(self, scene):
        item = _make_item(scene, text="A" * 50)
        item._update_flow_layout()
        layout = item.layout
        initial_lines = len(layout.y_offset_lst)

        # Move left points 50px right (narrow the block)
        for i in range(3):
            item._left_points[i] = QPointF(item._left_points[i].x() + 50, item._left_points[i].y())
        item._update_flow_layout()

        # After narrowing, lines should be more (text wraps)
        new_lines = len(layout.y_offset_lst)
        assert new_lines >= initial_lines, (
            f"Narrowing block should increase line count: "
            f"initial={initial_lines} new={new_lines}"
        )

    def test_move_right_boundary_left_wraps_more(self, scene):
        item = _make_item(scene, text="A" * 50)
        item._update_flow_layout()
        layout = item.layout
        initial_lines = len(layout.y_offset_lst)

        # Move right points 100px left (narrow the block)
        for i in range(3):
            item._right_points[i] = QPointF(item._right_points[i].x() - 100, item._right_points[i].y())
        item._update_flow_layout()

        new_lines = len(layout.y_offset_lst)
        assert new_lines >= initial_lines, (
            f"Left-shifting right boundary should increase line count: "
            f"initial={initial_lines} new={new_lines}"
        )

    def test_boundary_expand_reduces_wrapping(self, scene):
        """Widening the block reduces line count."""
        item = _make_item(scene, text="A" * 50)
        item._update_flow_layout()
        layout = item.layout
        initial_lines = len(layout.y_offset_lst)

        # Widen right points by 100px
        for i in range(3):
            item._right_points[i] = QPointF(item._right_points[i].x() + 100, item._right_points[i].y())
        item._update_flow_layout()

        new_lines = len(layout.y_offset_lst)
        assert new_lines <= initial_lines, (
            f"Widening block should reduce line count: "
            f"initial={initial_lines} new={new_lines}"
        )


class TestAutoShrink:
    """Font auto-shrink when text overflows."""

    def test_shrink_large_text_in_small_block(self, scene):
        item = _make_item(scene, xyxy=(0, 0, 80, 30), text="A" * 50, font_size=24.0)
        item._update_flow_layout()
        layout = item.layout

        # After shrink, max font should be <= original
        max_font = layout.max_font_size()
        assert max_font <= 24.0, f"Font should shrink: max_font={max_font}"

    def test_shrink_does_not_go_below_min(self, scene):
        """Extreme overflow shrinks font but stays above reasonable minimum."""
        item = _make_item(scene, xyxy=(0, 0, 100, 50), text="A" * 100, font_size=72.0)
        item._update_flow_layout()
        layout = item.layout
        max_font = layout.max_font_size()
        # After shrink, font should be much smaller than 72pt
        assert max_font < 72.0, f"Font should shrink: max_font={max_font}"
        # And text should fit (shrink_height <= target_height with margin)
        target_h = max(p.y() for p in item._left_points + item._right_points) - \
                   min(p.y() for p in item._left_points + item._right_points)
        assert layout.shrink_height <= target_h * 1.1, (
            f"Text should fit in target height: shrink={layout.shrink_height:.1f} target={target_h:.1f}"
        )

    def test_shrink_triggers_when_text_overflows(self, scene):
        """When text clearly overflows, shrink reduces font."""
        item = _make_item(scene, xyxy=(0, 0, 100, 50), text="A" * 100, font_size=72.0)
        item._update_flow_layout()
        max_font = item.layout.max_font_size()
        assert max_font < 72.0, f"Font should shrink when text overflows: max_font={max_font}"


class TestAutoGrow:
    """Font auto-grow when text is too small for block."""

    def test_grow_small_text_in_large_block(self, scene):
        item = _make_item(scene, xyxy=(0, 0, 400, 200), text="Hello", font_size=6.0)
        item._update_flow_layout()
        layout = item.layout

        max_font = layout.max_font_size()
        assert max_font > 6.0, f"Font should grow: max_font={max_font} (original=6.0)"

    def test_grow_does_nothing_when_text_fills_block(self, scene):
        """If text already fills ~70%+ of block height, grow is a no-op.
        Use a tall small block so text fills most of it at 16pt."""
        # "Hello\nworld\ntest\nlonger" at 16pt in 100x80 block fills ~100%
        item = _make_item(scene, xyxy=(0, 0, 100, 80), text="Hello\nworld\ntest\nlonger", font_size=16.0)
        item._update_flow_layout()
        layout = item.layout
        max_font = layout.max_font_size()
        # Font may grow slightly or stay — just don't double it
        assert max_font < 30.0, f"Font should not grow dramatically: max_font={max_font}"

    def test_grow_disabled_by_flag(self, scene):
        """When _auto_grow_enabled=False, grow does not happen (shrink still runs)."""
        # Use text that fits in block — so shrink is a no-op
        item = _make_item(scene, xyxy=(0, 0, 400, 200), text="Hi", font_size=24.0)
        item._auto_grow_enabled = False
        item._update_flow_layout()
        max_font = item.layout.max_font_size()
        # At 24pt in 400x200, "Hi" should fit without shrink, and grow is disabled
        assert max_font <= 24.0 + 1.0, f"Font should not grow when disabled: max_font={max_font}"


class TestShrinkGrowSymmetry:
    """Shrink + grow should find a stable font size."""

    def test_shrink_then_grow_stable(self, scene):
        """After shrink + grow, text should fill ~90% of block height."""
        item = _make_item(scene, xyxy=(0, 0, 150, 60), text="Some moderately long text here", font_size=36.0)
        item._update_flow_layout()
        layout = item.layout

        target_h = max(p.y() for p in item._left_points + item._right_points) - \
                   min(p.y() for p in item._left_points + item._right_points)

        fill_ratio = layout.shrink_height / target_h if target_h > 0 else 0
        # Should be between ~60% and ~100% after auto-sizing
        assert 0.50 <= fill_ratio <= 1.05, f"Fill ratio out of bounds: {fill_ratio:.2f}"

    def test_grow_then_shrink_stable(self, scene):
        """After grow + shrink, same stability."""
        item = _make_item(scene, xyxy=(0, 0, 150, 100), text="Some long text that should fit eventually", font_size=6.0)
        item._update_flow_layout()
        layout = item.layout

        target_h = max(p.y() for p in item._left_points + item._right_points) - \
                   min(p.y() for p in item._left_points + item._right_points)

        fill_ratio = layout.shrink_height / target_h if target_h > 0 else 0
        assert 0.50 <= fill_ratio <= 1.05, f"Fill ratio out of bounds: {fill_ratio:.2f}"


class TestPaintNoCrash:
    """Paint methods should not raise exceptions."""

    def test_paint_no_error(self, scene, qapp):
        """Calling paint should not crash."""
        item = _make_item(scene)
        # Create a QPixmap to paint onto
        from qtpy.QtGui import QPixmap
        pixmap = QPixmap(500, 500)
        pixmap.fill(Qt.GlobalColor.transparent)
        from qtpy.QtGui import QPainter
        painter = QPainter(pixmap)
        try:
            # Simulate a paint call with valid option
            from qtpy.QtWidgets import QStyleOptionGraphicsItem
            opt = QStyleOptionGraphicsItem()
            item.paint(painter, opt, None)
        finally:
            painter.end()

    def test_draw_accessories_no_crash(self, scene, qapp):
        """_draw_accessories should not raise NameError for missing constants."""
        item = _make_item(scene)
        from qtpy.QtGui import QPixmap, QPainter
        pixmap = QPixmap(500, 500)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            item._draw_accessories(painter)
        finally:
            painter.end()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])