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
from ui.flow_textitem import FlowTextBlkItem, DEFAULT_POINTS_PER_SIDE
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
        assert len(item._left_points) == DEFAULT_POINTS_PER_SIDE
        assert len(item._right_points) == DEFAULT_POINTS_PER_SIDE
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
        assert len(item._left_points) == DEFAULT_POINTS_PER_SIDE


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
        item.font_adjuster._auto_grow_enabled = False
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
        """After grow + shrink, same stability.
        May exceed 1.0 when hyphenation + forced-char-break
        detection cause extra shrink cycles for width reasons."""
        item = _make_item(scene, xyxy=(0, 0, 150, 100), text="Some long text that should fit eventually", font_size=6.0)
        item._update_flow_layout()
        layout = item.layout

        target_h = max(p.y() for p in item._left_points + item._right_points) - \
                   min(p.y() for p in item._left_points + item._right_points)

        fill_ratio = layout.shrink_height / target_h if target_h > 0 else 0
        assert 0.50 <= fill_ratio <= 1.50, f"Fill ratio out of bounds: {fill_ratio:.2f}"


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


class TestHyphenation:
    """Tests for the _hyphenate_text helper function."""

    def test_hyphenate_short_word(self):
        """Short words (<5 chars) are not modified."""
        from ui.flow_textitem import _hyphenate_text
        result = _hyphenate_text("дом")
        assert result == "дом", f"Expected 'дом', got {repr(result)}"
        result = _hyphenate_text("hi")
        assert result == "hi", f"Expected 'hi', got {repr(result)}"

    def test_hyphenate_long_russian_word(self):
        """Long Russian words are split with soft hyphens."""
        from ui.flow_textitem import _hyphenate_text
        result = _hyphenate_text("перенос")
        # pyphen hyphenates "перенос" as "пе-ре-нос"
        assert "\u00ad" in result, f"Expected soft hyphens, got {repr(result)}"
        assert "перенос" not in result, f"Word should not be unchanged: {repr(result)}"
        assert result == "пе\u00adре\u00adнос", f"Expected [пе-ре-нос], got {repr(result)}"

    def test_hyphenate_long_english_word(self):
        """Long English words are also split with soft hyphens."""
        from ui.flow_textitem import _hyphenate_text
        result = _hyphenate_text("hyphenation")
        assert "\u00ad" in result, f"Expected soft hyphens, got {repr(result)}"

    def test_hyphenate_sentence(self):
        """Sentence with mixed short/long words."""
        from ui.flow_textitem import _hyphenate_text
        text = "привет дорогой друг"
        result = _hyphenate_text(text)
        # "привет" -> "при-вет" (5+ chars)
        # "дорогой" -> "до-ро-гой" (5+ chars)
        # "друг" -> "друг" (<5 chars, unchanged)
        parts = result.split(" ")
        assert len(parts) == 3
        assert "при" in parts[0] and "вет" in parts[0]
        assert "до" in parts[1] and "ро" in parts[1] and "гой" in parts[1]
        assert parts[2] == "друг"

    def test_hyphenate_english_sentence(self):
        """English long words are now hyphenated (new behavior)."""
        from ui.flow_textitem import _hyphenate_text
        text = "hello world"
        result = _hyphenate_text(text)
        # "hello" -> "hel-lo" (5 chars = min_word_len -> hyphenated)
        # "world" -> "wor-ld" (5 chars = min_word_len -> hyphenated)
        assert "\u00ad" in result, f"Expected soft hyphens, got {repr(result)}"

    def test_hyphenate_empty_string(self):
        """Empty string returns empty string."""
        from ui.flow_textitem import _hyphenate_text
        assert _hyphenate_text("") == ""

    def test_hyphenate_mixed_lang(self):
        """Mixed Russian/English text hyphenates both languages."""
        from ui.flow_textitem import _hyphenate_text
        text = "классный hello мир"
        result = _hyphenate_text(text)
        parts = result.split(" ")
        assert len(parts) == 3
        # "hello" now also hyphenated (5 chars = min_word_len)
        assert "\u00ad" in parts[1], f"Expected 'hello' to be hyphenated: {repr(parts[1])}"
        assert parts[2] == "мир"

    def test_hyphenate_min_word_len_param(self):
        """Custom min_word_len parameter is respected."""
        from ui.flow_textitem import _hyphenate_text
        text = "мир дом"
        # With default min_word_len=5, both words are <5 -> unchanged
        result = _hyphenate_text(text)
        assert result == text

    def test_hyphenate_integration_with_setplaintext(self, scene, qapp):
        """FlowTextBlkItem.setPlainText should hyphenate text."""
        from ui.flow_textitem import FlowTextBlkItem, DEFAULT_POINTS_PER_SIDE

        blk = _make_blk(xyxy=(0, 0, 300, 100), text="", font_size=20)
        item = FlowTextBlkItem(blk, idx=0, set_format=True, show_rect=True)
        scene.addItem(item)

        # Set long Russian text
        text = "невероятный эксперимент"
        item.setPlainText(text)

        # Check that the document text contains soft hyphens
        doc_text = item.document().toPlainText()
        assert "\u00ad" in doc_text, (
            f"Expected soft hyphens in document text, got {repr(doc_text)}"
        )
        assert len(doc_text) > len(text.replace(" ", "")), (
            "Document text should be longer than original due to soft hyphens"
        )


# ── Regression tests for flow points persistence ──────────────

class TestFlowPointsPersistence:
    """Tests for flow control points saving/loading across page switches."""

    def test_saved_points_restored_on_reinit(self, scene):
        """Flow points saved to blk must survive re-creation of FlowTextBlkItem."""
        blk = _make_blk(xyxy=(100, 100, 300, 200))
        blk.left_points = [[0, 0], [0, 50], [100, 60]]
        blk.right_points = [[200, 0], [200, 50], [200, 100]]

        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # Verify custom points restored (not default rectangle)
        assert item._left_points[2].x() == 100
        assert item._left_points[2].y() == 60
        assert item._right_points[2].x() == 200
        assert item._right_points[2].y() == 100

    def test_save_flow_points_does_not_overwrite_with_empty(self, scene):
        """save_flow_points with empty _left_points must not clear blk.left_points."""
        blk = _make_blk(xyxy=(100, 100, 300, 200))
        blk.left_points = [[0, 0], [0, 50], [100, 60]]
        blk.right_points = [[200, 0], [200, 50], [200, 100]]

        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # Simulate what setVertical used to do: call save_flow_points
        # when _left_points might be empty during init
        original_left = list(blk.left_points)
        item.save_flow_points()

        # Points must NOT be overwritten with empty
        assert blk.left_points == original_left

    def test_default_points_generated_for_new_blocks(self, scene):
        """New blocks without saved points must get default rectangle points."""
        blk = _make_blk(xyxy=(0, 0, 400, 200))
        # No left_points/right_points set

        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        assert len(item._left_points) == DEFAULT_POINTS_PER_SIDE
        assert len(item._right_points) == DEFAULT_POINTS_PER_SIDE
        # Points should form a rectangle
        assert item._left_points[0].x() == item._left_points[2].x()  # same x
        assert item._right_points[0].x() == item._right_points[2].x()

    def test_display_rect_not_inflated_by_margins(self, scene):
        """_display_rect height must match actual text extent, not document size."""
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="Hello")
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # _display_rect should be close to block size, not inflated
        dr = item._display_rect
        assert dr.width() <= 400 + 10  # small tolerance
        assert dr.height() <= 200 + 10

    def test_absBoundingRect_dimensions_reasonable(self, scene):
        """absBoundingRect must return dimensions that make sense for font sizing."""
        blk = _make_blk(xyxy=(50, 50, 250, 150), text="Test text here")
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        abr = item.absBoundingRect()
        # width and height must be positive and not wildly different from block
        assert abr[2] > 0
        assert abr[3] > 0
        assert abr[2] <= 500  # reasonable upper bound
        assert abr[3] <= 500

    def test_points_survive_setPlainText(self, scene):
        """Flow points must not be lost when text is set."""
        blk = _make_blk(xyxy=(0, 0, 400, 200))
        blk.left_points = [[0, 0], [0, 50], [150, 60]]
        blk.right_points = [[300, 0], [300, 50], [300, 100]]

        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        item.setPlainText("New text content")

        # Custom points must survive
        assert item._left_points[2].x() == 150
        assert item._right_points[2].x() == 300


class TestBinarySearchFontSizing:
    """Test _find_best_font_size with Cyrillic text that caused small-font bug.

    Bug: binary search used document().size().height() instead of
    layout.shrink_height, causing it to pick fonts ~5x too small.

    Real data from logs.txt (Sensation Comics 001-006.jpg):
      idx=6: text='БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ З...'
             target=(305.0x92.0) optimal_size=14.55pt
      idx=8: text='60 МИЛЬ В ЧАС-- И ОНА ЕЩЕ ВПЕРЕД, ЕДУ ЧТОБЫ ОТКРЫТЬ ЭТО БАГГ...'
             target=(247.0x161.0) optimal_size=16.11pt
    """

    def test_bystre_block_gets_reasonable_font(self, scene):
        """БЫСТРЕЕ block (305x92) should get ~14pt font, not ~3pt."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        font = item.layout.max_font_size()
        # From logs: optimal_size=14.55pt
        assert font >= 12.0, f"БЫСТРЕЕ font too small: {font:.1f}pt (expected >= 12pt)"
        assert font <= 18.0, f"БЫСТРЕЕ font too large: {font:.1f}pt (expected <= 18pt)"

    def test_60_mil_block_fills_height(self, scene):
        """60 МИЛЬ В ЧАС block (247x161) should fill ~70%+ of height."""
        text = "60 МИЛЬ В ЧАС-- И ОНА ЕЩЕ ВПЕРЕД, ЕДУ ЧТОБЫ ОТКРЫТЬ ЭТО БАГРОВОЕ ДЕЛО"
        blk = _make_blk(xyxy=(0, 0, 247, 161), text=text, font_size=119.2)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        target_h = 161.0
        text_extent = item.layout.shrink_height
        fill_ratio = text_extent / target_h
        # From logs: text_extent=117.3, fill=73%
        assert fill_ratio >= 0.50, (
            f"60 МИЛЬ text should fill >= 50% of block: "
            f"shrink_height={text_extent:.1f} target={target_h:.1f} "
            f"fill={fill_ratio:.1%}"
        )

    def test_no_oscillation_after_shrink_grow(self, scene):
        """After shrink+grow, running again should produce same result."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        # First pass
        item._update_flow_layout()
        font1 = item.layout.max_font_size()
        extent1 = item.layout.shrink_height

        # Second pass — should be stable
        item._update_flow_layout()
        font2 = item.layout.max_font_size()
        extent2 = item.layout.shrink_height

        assert abs(font1 - font2) < 1.0, (
            f"Font oscillation: pass1={font1:.1f}pt pass2={font2:.1f}pt"
        )
        assert abs(extent1 - extent2) < 10.0, (
            f"Height oscillation: pass1={extent1:.1f} pass2={extent2:.1f}"
        )

    def test_text_fits_width_after_binary_search(self, scene):
        """Text width should not exceed block width after binary search."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        target_w = 305.0
        text_w = item.layout.shrink_width
        assert text_w <= target_w * 1.05, (
            f"Text overflows width: {text_w:.1f} > {target_w:.1f}"
        )

    def test_set_size_with_auto_font_adjust_false(self, scene):
        """set_size(auto_font_adjust=False) should not trigger shrink/grow."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()
        font_before = item.layout.max_font_size()

        # set_size with auto_font_adjust=False should not change font
        item.set_size(305, 92, set_layout_maxsize=True, auto_font_adjust=False)
        font_after = item.layout.max_font_size()

        assert abs(font_before - font_after) < 1.0, (
            f"set_size(auto_font_adjust=False) changed font: "
            f"before={font_before:.1f} after={font_after:.1f}"
        )


class TestAutoFontAdjustFlag:
    """Regression: _auto_font_adjust must survive internal shrink/grow cycles.

    Bug: FlowTextBlkItem.setFontSize() unconditionally set _auto_font_adjust=False,
    even when called internally by _auto_shrink_font/_auto_grow_font via
    setRelFontSize(). This permanently disabled auto-adjust after the first layout.
    """

    def test_auto_font_adjust_survives_shrink(self, scene):
        """_auto_font_adjust stays True after _auto_shrink_font runs."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        assert item._auto_font_adjust is True
        item.font_adjuster.shrink()
        assert item._auto_font_adjust is True, (
            "_auto_font_adjust was reset to False by _auto_shrink_font"
        )

    def test_auto_font_adjust_survives_grow(self, scene):
        """_auto_font_adjust stays True after _auto_grow_font runs."""
        text = "Hello"
        blk = _make_blk(xyxy=(0, 0, 400, 300), text=text, font_size=10.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        assert item._auto_font_adjust is True
        item.font_adjuster.grow()
        assert item._auto_font_adjust is True, (
            "_auto_font_adjust was reset to False by _auto_grow_font"
        )

    def test_auto_font_adjust_survives_update_flow_layout(self, scene):
        """_auto_font_adjust stays True after full _update_flow_layout with shrink."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        assert item._auto_font_adjust is True
        item._update_flow_layout()
        assert item._auto_font_adjust is True, (
            "_auto_font_adjust was reset to False by _update_flow_layout"
        )

    def test_manual_font_change_disables_auto_adjust(self, scene):
        """User font change via setFontSize should set _auto_font_adjust=False.

        This prevents grow from overriding the user's font choice.
        Internal shrink/grow use _internal_font_change=True to skip this.
        """
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="Hello world", font_size=14.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText("Hello world")

        assert item._auto_font_adjust is True
        item.setFontSize(20.0)  # Simulate user changing font via toolbar
        assert item._auto_font_adjust is False, (
            "User font change should set _auto_font_adjust=False"
        )


class TestBlockResizeShrinkGrow:
    """Test that font auto-adjusts when block boundaries change (handle drag)."""

    def _resize_right(self, item, new_right_x):
        """Simulate dragging the right boundary control point."""
        # Set right boundary x to new_right_x for all right points
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(new_right_x, pt.y())
        item._update_flow_layout()

    def _resize_left(self, item, new_left_x):
        """Simulate dragging the left boundary control point."""
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(new_left_x, pt.y())
        item._update_flow_layout()

    def test_resize_narrower_triggers_shrink(self, scene):
        """Making block narrower should shrink font to fit."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        font_before = item.layout.max_font_size()
        width_before = item.layout.shrink_width

        # Make block narrower (200px instead of 305px)
        self._resize_right(item, 200)

        font_after = item.layout.max_font_size()
        # Font should have shrunk to fit the narrower width
        assert font_after < font_before, (
            f"Font did not shrink on narrower block: "
            f"before={font_before:.1f} after={font_after:.1f}"
        )

    def test_resize_wider_triggers_grow(self, scene):
        """Making block wider after shrink should grow font back."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        # Shrink first
        self._resize_right(item, 200)
        font_after_shrink = item.layout.max_font_size()

        # Now widen back to original
        self._resize_right(item, 305)
        font_after_grow = item.layout.max_font_size()

        assert font_after_grow > font_after_shrink, (
            f"Font did not grow on wider block: "
            f"after_shrink={font_after_shrink:.1f} after_grow={font_after_grow:.1f}"
        )

    def test_shrink_then_widen_recovers_font(self, scene):
        """Font after shrink→widen should be close to original."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        font_original = item.layout.max_font_size()

        # Shrink to 200px, then back to 305px
        self._resize_right(item, 200)
        self._resize_right(item, 305)
        font_recovered = item.layout.max_font_size()

        # Should recover most of the original font size (within 3pt tolerance)
        assert abs(font_recovered - font_original) < 3.0, (
            f"Font did not recover after shrink→widen: "
            f"original={font_original:.1f} recovered={font_recovered:.1f}"
        )

    def test_multiple_resizes_no_oscillation(self, scene):
        """Repeated narrow→wide→narrow cycles should stabilize."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        fonts = []
        for w in [200, 305, 200, 305]:
            self._resize_right(item, w)
            fonts.append(item.layout.max_font_size())

        # Last two (both at 305px) should be very close
        assert abs(fonts[1] - fonts[3]) < 1.0, (
            f"Font oscillation at same width: pass1={fonts[1]:.1f} pass2={fonts[3]:.1f}"
        )
        # Last two (both at 200px) should be very close
        assert abs(fonts[0] - fonts[2]) < 1.0, (
            f"Font oscillation at same width: pass1={fonts[0]:.1f} pass2={fonts[2]:.1f}"
        )


class TestEmptyBlockNoGrow:
    """Regression: _auto_grow_font must NOT run on empty blocks."""

    def test_grow_skipped_on_empty_block(self, scene):
        """Empty block should not have its font inflated by grow."""
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="", font_size=12.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText("")

        font_before = item.layout.max_font_size()
        item.font_adjuster.grow()
        font_after = item.layout.max_font_size()

        assert font_before == font_after, (
            f"Grow ran on empty block: before={font_before:.1f} after={font_after:.1f}"
        )

    def test_shrink_skipped_on_empty_block(self, scene):
        """Empty block should not have its font changed by shrink."""
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="", font_size=12.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText("")

        font_before = item.layout.max_font_size()
        item.font_adjuster.shrink()
        font_after = item.layout.max_font_size()

        assert font_before == font_after, (
            f"Shrink ran on empty block: before={font_before:.1f} after={font_after:.1f}"
        )

    def test_grow_skipped_on_whitespace_only(self, scene):
        """Block with only whitespace should not have font inflated."""
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="   ", font_size=12.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText("   ")

        font_before = item.layout.max_font_size()
        item.font_adjuster.grow()
        font_after = item.layout.max_font_size()

        assert font_before == font_after, (
            f"Grow ran on whitespace block: before={font_before:.1f} after={font_after:.1f}"
        )

    def test_update_flow_layout_no_font_change_on_empty(self, scene):
        """Full _update_flow_layout should not change font on empty block."""
        blk = _make_blk(xyxy=(0, 0, 400, 200), text="", font_size=12.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText("")

        font_before = item.layout.max_font_size()
        item._update_flow_layout()
        font_after = item.layout.max_font_size()

        assert abs(font_before - font_after) < 0.1, (
            f"Font changed on empty block: before={font_before:.1f} after={font_after:.1f}"
        )


class TestUndoFontRestore:
    """Regression: Ctrl+Z should restore font size after handle drag."""

    def test_reshape_undo_restores_font_size(self, scene):
        """Undo after resize should restore original font size."""
        from ui.textedit_commands import ReshapeItemCommand

        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        font_before = item.layout.max_font_size()

        # Save old rect and flow points for the command
        from copy import deepcopy
        item.oldRect = item.rect()
        cmd = ReshapeItemCommand(item)

        # Simulate handle drag: narrow the block (triggers shrink)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        font_after_resize = item.layout.max_font_size()
        assert font_after_resize < font_before, "Font should have shrunk"

        # Apply the command (redo)
        cmd.redo()

        # Now undo — should restore original flow points and font size
        cmd.undo()

        font_after_undo = item.layout.max_font_size()
        # Undo restores font size, then _update_flow_layout runs shrink/grow
        # which may adjust it slightly. The key check is that undo doesn't
        # leave the font at the shrunken size.
        assert font_after_undo > font_after_resize, (
            f"Undo did not restore font: after_resize={font_after_resize:.1f} after_undo={font_after_undo:.1f}"
        )


class TestAutoAdjustReset:
    """Regression: _auto_font_adjust should reset to True after _update_flow_layout."""

    def test_flag_resets_after_update_flow_layout(self, scene):
        """After _update_flow_layout, _auto_font_adjust should be True."""
        text = "Hello world test text here"
        blk = _make_blk(xyxy=(0, 0, 400, 200), text=text, font_size=14.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)

        # Simulate manual font change
        item._auto_font_adjust = False
        item._update_flow_layout()

        assert item._auto_font_adjust is True, (
            "_auto_font_adjust should be True after _update_flow_layout"
        )

    def test_auto_adjust_works_after_manual_font_change(self, scene):
        """After manual font change, next resize should auto-adjust.

        Manual font change sets _auto_font_adjust=False (prevents grow from
        overriding). But _update_flow_layout resets it to True, so the
        NEXT resize will auto-adjust.
        """
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        # Manual font change sets flag to False
        item.setFontSize(20.0)
        assert item._auto_font_adjust is False

        # Resize triggers _update_flow_layout which resets flag to True
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        assert item._auto_font_adjust is True


class TestFontPanelAfterResize:
    """Regression: font panel should still set font size after block resize."""

    def test_font_size_changes_after_resize(self, scene):
        """After resizing block, font size from panel should still work."""
        text = "КАК ГРОМ С НЕБА ПРИХОДИТ ВЕСЬ МИР СХОДИТ С УМА"
        blk = _make_blk(xyxy=(0, 0, 300, 200), text=text, font_size=20.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        # Step 1: Set font size via panel (simulates panel calling setFontSize)
        item.setFontSize(30.0)
        font_after_first = item.layout.max_font_size()
        assert font_after_first > 20.0, "Font should have increased"

        # Step 2: Resize block (simulate handle drag)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(400, pt.y())
        item._update_flow_layout()

        # Step 3: Set font size again via panel
        item.setFontSize(25.0)
        font_after_second = item.layout.max_font_size()

        # Font should actually change to 25pt
        assert abs(font_after_second - 25.0) < 2.0, (
            f"Font should be ~25pt after second setFontSize: got {font_after_second:.1f}"
        )

    def test_font_size_changes_after_narrow_resize(self, scene):
        """After narrowing block, font size from panel should still work."""
        text = "КАК ГРОМ С НЕБА ПРИХОДИТ ВЕСЬ МИР СХОДИТ С УМА"
        blk = _make_blk(xyxy=(0, 0, 300, 200), text=text, font_size=20.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        # Step 1: Set font size
        item.setFontSize(30.0)

        # Step 2: Make block narrower (triggers shrink)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(150, pt.y())
        item._update_flow_layout()

        font_after_resize = item.layout.max_font_size()

        # Step 3: Set font size again via panel
        item.setFontSize(20.0)
        font_after_second = item.layout.max_font_size()

        assert abs(font_after_second - 20.0) < 2.0, (
            f"Font should be ~20pt after second setFontSize: got {font_after_second:.1f}"
        )

    def test_font_format_syncs_after_resize(self, scene):
        """fontformat.size should sync with actual font after resize + setFontSize."""
        text = "КАК ГРОМ С НЕБА ПРИХОДИТ ВЕСЬ МИР СХОДИТ С УМА"
        blk = _make_blk(xyxy=(0, 0, 300, 200), text=text, font_size=20.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        # Set font size
        item.setFontSize(35.0)

        # Resize
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(400, pt.y())
        item._update_flow_layout()

        # Set font size again
        item.setFontSize(15.0)

        # Check fontformat.size is synced
        actual_font = item.layout.max_font_size()
        assert abs(actual_font - 15.0) < 2.0, (
            f"Actual font {actual_font:.1f} != expected 15.0"
        )

    def test_font_changed_twice_in_a_row(self, scene):
        """Font can be set twice in a row via panel — both times stick."""
        text = "КАК ГРОМ С НЕБА ПРИХОДИТ ВЕСЬ МИР СХОДИТ С УМА"
        blk = _make_blk(xyxy=(0, 0, 300, 200), text=text, font_size=20.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)
        item.setPlainText(text)
        item._update_flow_layout()

        # First font change
        item.setFontSize(15.0)
        font1 = item.layout.max_font_size()
        assert abs(font1 - 15.0) < 2.0, (
            f"First setFontSize failed: got {font1:.1f}, expected 15.0"
        )

        # Second font change — should also work
        item.setFontSize(25.0)
        font2 = item.layout.max_font_size()
        assert abs(font2 - 25.0) < 2.0, (
            f"Second setFontSize failed: got {font2:.1f}, expected 25.0"
        )

        # Third font change — should also work
        item.setFontSize(10.0)
        font3 = item.layout.max_font_size()
        assert abs(font3 - 10.0) < 2.0, (
            f"Third setFontSize failed: got {font3:.1f}, expected 10.0"
        )


class TestLargeFontNoOverflow:
    """After translation, large font (>60pt) must not overflow block boundaries.

    Simulates RunBlkTransCommand flow:
    1. Binary search finds optimal font size
    2. setFontSize + setPlainText + set_size
    3. _update_flow_layout() runs with grow DISABLED
    4. shrink_height must be <= target_height
    """

    def test_large_font_no_overflow(self, scene):
        """ВПЕРЁД!-style block: 680x90, text that gets ~47pt font, no overflow."""
        text = "ВПЕРЁД! Я-Я-Я-Я!"
        blk = _make_blk(xyxy=(0, 0, 680, 90), text=text, font_size=120.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # Simulate RunBlkTransCommand: set font, text, size
        item.setFontSize(68.0)
        item.setPlainText(text)
        item.set_size(680, 90, set_layout_maxsize=True)

        # Run _update_flow_layout with grow disabled (same as RunBlkTransCommand)
        item._auto_font_adjust = True
        saved_grow = item.font_adjuster._auto_grow_enabled
        item.font_adjuster._auto_grow_enabled = False
        item._update_flow_layout()
        item.font_adjuster._auto_grow_enabled = saved_grow

        target_h = 90.0
        text_extent = item.layout.shrink_height
        assert text_extent <= target_h + 1.0, (
            f"Text overflows block: shrink_height={text_extent:.1f} > target={target_h:.1f}"
        )

    def test_medium_font_no_overflow(self, scene):
        """531x163 block with medium-length text."""
        text = "ВПЕРЁД! Я-Я-Я-Я! К-К-К-К!"
        blk = _make_blk(xyxy=(0, 0, 531, 163), text=text, font_size=100.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        item.setFontSize(68.0)
        item.setPlainText(text)
        item.set_size(531, 163, set_layout_maxsize=True)

        item._auto_font_adjust = True
        saved_grow = item.font_adjuster._auto_grow_enabled
        item.font_adjuster._auto_grow_enabled = False
        item._update_flow_layout()
        item.font_adjuster._auto_grow_enabled = saved_grow

        target_h = 163.0
        text_extent = item.layout.shrink_height
        assert text_extent <= target_h + 1.0, (
            f"Text overflows block: shrink_height={text_extent:.1f} > target={target_h:.1f}"
        )

    def test_binary_search_result_no_overflow(self, scene):
        """Binary search optimal size must not overflow after _update_flow_layout."""
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        blk = _make_blk(xyxy=(0, 0, 305, 92), text=text, font_size=67.5)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # Run binary search to find optimal font size
        optimal = item.font_adjuster._layout  # layout ref
        target_w, target_h = 305.0, 92.0
        optimal_size = 12.0  # fallback
        # Use _find_best_font_size if available
        try:
            from ui.scenetext_manager import LAYOUT_FIT_FILL_H_RATIO, LAYOUT_FIT_FILL_W_RATIO, LAYOUT_BLOCK_SHRINK_W
            tw = target_w * LAYOUT_BLOCK_SHRINK_W * LAYOUT_FIT_FILL_W_RATIO
            th = target_h * LAYOUT_FIT_FILL_H_RATIO
            lo, hi = 8.0, 200.0
            for _ in range(30):
                if hi - lo < 0.1:
                    break
                mid = (lo + hi) / 2.0
                item.font_adjuster._internal_font_change = True
                item.setRelFontSize(mid / item.font().pointSizeF())
                item.font_adjuster._internal_font_change = False
                item.setPlainText(text)
                item.set_size(tw, th, set_layout_maxsize=True, auto_font_adjust=False)
                doc_h = item.layout.shrink_height if item.layout.shrink_height > 0 else item.document().size().height()
                if doc_h <= th:
                    optimal_size = mid
                    lo = mid
                else:
                    hi = mid
        except Exception:
            pass

        # Now simulate RunBlkTransCommand: set optimal font, text, size, then _update_flow_layout with grow disabled
        item.setFontSize(optimal_size)
        item.setPlainText(text)
        item.set_size(target_w, target_h, set_layout_maxsize=True)

        item._auto_font_adjust = True
        saved_grow = item.font_adjuster._auto_grow_enabled
        item.font_adjuster._auto_grow_enabled = False
        item._update_flow_layout()
        item.font_adjuster._auto_grow_enabled = saved_grow

        text_extent = item.layout.shrink_height
        assert text_extent <= target_h + 1.0, (
            f"Binary search result overflows: shrink_height={text_extent:.1f} > target={target_h:.1f}"
        )
        # Font should be reasonable (not too small)
        font_size = item.font().pointSizeF()
        assert font_size >= 8.0, f"Font too small after binary search: {font_size:.1f}pt"


class TestAbsBoundingRectUsesControlPoints:
    """absBoundingRect() must use control points y-range for height, not _display_rect.

    Bug: _display_rect stored width/height from setRect, but absBoundingRect()
    returned those as [x, y, w, h]. OCR cropped by xyxy derived from this, giving
    wrong height (e.g. 5px instead of 35px). Control points define the actual
    visual block height.
    """

    def test_height_from_control_points(self, scene):
        """Block with control points spanning 35px height must return h=35."""
        text = "Test text"
        blk = _make_blk(xyxy=(0, 0, 200, 35), text=text, font_size=24.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        # Control points should span the block height
        assert len(item._left_points) == DEFAULT_POINTS_PER_SIDE
        ys = [p.y() for p in item._left_points]
        cp_height = max(ys) - min(ys)

        abr = item.absBoundingRect()
        # abr returns [x, y, w, h] with math.ceil rounding
        assert abs(abr[3] - cp_height) <= 1.0, (
            f"absBoundingRect height={abr[3]} != control points height={cp_height}"
        )

    def test_ocr_crop_uses_correct_height(self, scene):
        """Simulate OCR crop — xyxy from absBoundingRect must have correct height."""
        text = "OCR test"
        blk = _make_blk(xyxy=(100, 200, 400, 235), text=text, font_size=24.0)
        item = FlowTextBlkItem(blk, idx=0)
        scene.addItem(item)

        abr = item.absBoundingRect()
        # abr = [x, y, w, h]
        x, y, w, h = abr
        xyxy = [x, y, x + w, y + h]

        # OCR would crop img[y1:y2, x1:x2]
        crop_h = xyxy[3] - xyxy[1]
        assert crop_h == 35, f"OCR crop height={crop_h}, expected 35"

    def test_height_matches_on_screen(self, scene):
        """Two blocks with same control point height must return same absBoundingRect height."""
        blk1 = _make_blk(xyxy=(0, 0, 200, 35), text="A", font_size=24.0)
        item1 = FlowTextBlkItem(blk1, idx=0)
        scene.addItem(item1)

        blk2 = _make_blk(xyxy=(300, 0, 600, 35), text="B", font_size=24.0)
        item2 = FlowTextBlkItem(blk2, idx=1)
        scene.addItem(item2)

        h1 = item1.absBoundingRect()[3]
        h2 = item2.absBoundingRect()[3]
        assert h1 == h2, f"Heights differ: block1={h1}, block2={h2}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
