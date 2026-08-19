"""
End-to-end tests for the panel formatting command path applied to a text
selection (bug #2 — per-range outline for flow blocks).

Run with:
    set QT_QPA_PLATFORM=offscreen
    myenv\Scripts\python.exe -m pytest tests/ui/test_selection_stroke_command.py -v
"""

import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock

from qtpy.QtGui import QTextCursor, QUndoStack

from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from ui import shared_widget as SW
from ui.flow_textitem import FlowTextBlkItem
from ui import fontformat_commands as F


def _make_blk(text="Hello world"):
    blk = TextBlock([0, 0, 400, 200])
    blk.lines = [[[0, 0], [400, 0], [400, 200], [0, 200]]]
    blk.translation = text
    blk._bounding_rect = [0, 0, 400, 200]
    return blk


@pytest.fixture
def item(scene):
    blk = _make_blk()
    it = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(it)
    return it


@pytest.fixture(autouse=True)
def mock_canvas(monkeypatch):
    """font_formating pushes to SW.canvas.push_undo_command."""
    canvas = MagicMock()
    canvas.undo_stack = QUndoStack()
    canvas.push_undo_command.side_effect = lambda cmd: canvas.undo_stack.push(cmd)
    monkeypatch.setattr(SW, "canvas", canvas)
    return canvas


class TestSelectionStrokeCommand:
    def test_stroke_width_command_on_selection(self, item, mock_canvas):
        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)

        act = FontFormat()
        F.ffmt_change_stroke_width('stroke_width', 0.4, act, False, [item])

        # Block scalar untouched — per-range only
        assert item.fontformat.stroke_width == 0
        assert act.stroke_width == 0
        assert len(item.blk.outline_ranges) == 1
        s, e, w, c = item.blk.outline_ranges[0]
        assert w == 0.4 and c == [0, 0, 0]
        assert (s, e) == (0, 5)  # item-cursor selection, doc coordinates

        # One undo command on the stack
        assert mock_canvas.undo_stack.count() == 1
        # Undo: sentinel removes the range (selection falls back to the
        # block-level outline — here block stroke is 0, so no groups at all)
        mock_canvas.undo_stack.undo()
        assert item.blk.outline_ranges == []
        assert item._stroke_groups() == {}
        # Redo: width back to 0.4
        mock_canvas.undo_stack.redo()
        assert item.blk.outline_ranges[0][2] == 0.4

    def test_stroke_color_command_on_selection(self, item, mock_canvas):
        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)
        F.ffmt_change_stroke_width('stroke_width', 0.4, FontFormat(), False, [item])
        n_cmds = mock_canvas.undo_stack.count()

        F.ffmt_change_srgb('srgb', (1, 2, 3), FontFormat(), False, [item])
        assert mock_canvas.undo_stack.count() == n_cmds + 1
        assert item.blk.outline_ranges[0][3] == [1, 2, 3]
        assert list(item.fontformat.srgb) == [0, 0, 0]

        mock_canvas.undo_stack.undo()
        assert item.blk.outline_ranges[0][3] == [0, 0, 0]

    def test_stroke_width_whole_block_without_selection(self, item, mock_canvas):
        # No selection anywhere -> block scalar path
        act = FontFormat()
        F.ffmt_change_stroke_width('stroke_width', 0.25, act, False, [item])
        assert item.fontformat.stroke_width == 0.25
        assert act.stroke_width == 0.25
        assert item.blk.outline_ranges == []


class TestSelectionStrokeUndoWithoutSelection:
    """Undo/redo must restore the exact outline_ranges state even when the
    effective selection is gone (selection cleared, _last_selection reset);
    the block-level scalar must stay untouched."""

    @staticmethod
    def _clear_selection(item):
        cur = item.textCursor()
        cur.clearSelection()
        item.setTextCursor(cur)
        item._last_selection = None

    def test_stroke_width_undo_without_selection(self, item, mock_canvas):
        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)

        scalar_before = item.fontformat.stroke_width
        before = copy.deepcopy(item.blk.outline_ranges)
        F.ffmt_change_stroke_width('stroke_width', 0.4, FontFormat(), False, [item])
        after = copy.deepcopy(item.blk.outline_ranges)
        assert after == [[0, 5, 0.4, [0, 0, 0]]]
        # selection path never touches the block scalar
        assert item.fontformat.stroke_width == scalar_before

        self._clear_selection(item)
        assert item._effective_selection() is None

        mock_canvas.undo_stack.undo()
        assert item.blk.outline_ranges == before
        assert item.fontformat.stroke_width == scalar_before

        mock_canvas.undo_stack.redo()
        assert item.blk.outline_ranges == after
        assert item.fontformat.stroke_width == scalar_before

    def test_stroke_color_undo_without_selection(self, item, mock_canvas):
        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)
        F.ffmt_change_stroke_width('stroke_width', 0.4, FontFormat(), False, [item])

        before = copy.deepcopy(item.blk.outline_ranges)
        assert before == [[0, 5, 0.4, [0, 0, 0]]]
        srgb_before = list(item.fontformat.srgb)

        F.ffmt_change_srgb('srgb', (1, 2, 3), FontFormat(), False, [item])
        after = copy.deepcopy(item.blk.outline_ranges)
        assert after == [[0, 5, 0.4, [1, 2, 3]]]
        # selection path never touches the block scalar
        assert list(item.fontformat.srgb) == srgb_before

        self._clear_selection(item)
        assert item._effective_selection() is None

        mock_canvas.undo_stack.undo()
        assert item.blk.outline_ranges == before
        assert list(item.fontformat.srgb) == srgb_before

        mock_canvas.undo_stack.redo()
        assert item.blk.outline_ranges == after
        assert list(item.fontformat.srgb) == srgb_before

    def test_negative_width_whole_block_path_is_noop(self, item):
        item.fontformat.stroke_width = 0.3
        item.setStrokeWidth(-1.0, set_selected=False)
        assert item.fontformat.stroke_width == 0.3  # блок-скаляр не тронут
        assert item.blk.outline_ranges == []


class TestSelectionStrokeZero:
    """Обводка 0 только для выделенного текста: блок-обводка у остального
    текста должна остаться, у выделения — исчезнуть (и не вернуться после
    потери фокуса/репейнта)."""

    def _block_stroked_item(self, item):
        item.fontformat.stroke_width = 0.5
        item.blk.fontformat.stroke_width = 0.5
        item.setStrokeWidth(0.5, repaint_background=False)

    def _spans(self, groups, w_px):
        out = []
        for (wp, _c), spans in groups.items():
            if wp == w_px:
                out.extend(spans)
        return out

    def test_zero_blocks_block_outline_for_selection(self, item, mock_canvas):
        from utils.fontformat import pt2px
        self._block_stroked_item(item)
        base = pt2px(item.fontformat.font_size)
        w_px = max(1, int(round(base * 0.5)))

        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)
        F.ffmt_change_stroke_width('stroke_width', 0.0, FontFormat(), False, [item])

        assert item.fontformat.stroke_width == 0.5  # блок-обводка на месте
        s, e, w, _c = item.blk.outline_ranges[0]
        assert (s, e, w) == (0, 5, 0.0)

        groups = item._stroke_groups()
        # Ни одна группа не закрывает [0, 5)
        assert not any(s < 5 and e > 0 for (s, e) in self._spans(groups, w_px))
        # Остальной текст блок-обводкой закрыт
        n = item.document().rootFrame().lastPosition()
        assert (5, n) in self._spans(groups, w_px)

        # «Потеря фокуса»: полный репейнт — обводка у выделения не возвращается
        item.repaint_background()
        groups2 = item._stroke_groups()
        assert not any(s < 5 and e > 0 for (s, e) in self._spans(groups2, w_px))

    def test_undo_of_zero_restores_block_outline(self, item, mock_canvas):
        from utils.fontformat import pt2px
        self._block_stroked_item(item)
        base = pt2px(item.fontformat.font_size)
        w_px = max(1, int(round(base * 0.5)))

        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)
        F.ffmt_change_stroke_width('stroke_width', 0.0, FontFormat(), False, [item])
        assert not any(s < 5 and e > 0 for (s, e) in self._spans(item._stroke_groups(), w_px))

        # Ctrl+Z: диапазон удаляется — выделение снова наследует блок-обводку
        mock_canvas.undo_stack.undo()
        assert item.blk.outline_ranges == []
        assert (0, 5) in self._spans(item._stroke_groups(), w_px) or \
               any(s <= 0 and e >= 5 for (s, e) in self._spans(item._stroke_groups(), w_px))

        # Ctrl+Y: обводка у выделения снова исчезает
        mock_canvas.undo_stack.redo()
        assert item.blk.outline_ranges[0][2] == 0.0
        assert not any(s < 5 and e > 0 for (s, e) in self._spans(item._stroke_groups(), w_px))

    def test_get_selection_outline_returns_zero(self, item):
        item.blk.outline_ranges = [[0, 5, 0.0, [1, 2, 3]]]
        cur = item.textCursor()
        cur.setPosition(0)
        cur.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        item.setTextCursor(cur)
        assert item.get_selection_outline() == (0.0, [1, 2, 3])

    def test_negative_width_without_selection_is_noop(self, item):
        item.fontformat.stroke_width = 0.3
        item.setStrokeWidth(-1.0, set_selected=True)
        assert item.fontformat.stroke_width == 0.3  # блок-скаляр не тронут
        assert item.blk.outline_ranges == []
