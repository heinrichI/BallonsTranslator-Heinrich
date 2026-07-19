"""Tests for UndoManager."""
import pytest
from unittest.mock import MagicMock
from ui.undo_manager import UndoManager


class TestUndoManager:
    def setup_method(self):
        self.undo_mgr = UndoManager()

    def test_init_creates_stacks(self):
        assert self.undo_mgr._text_undo_stack is not None
        assert self.undo_mgr._draw_undo_stack is not None

    def test_clear_resets_counters(self):
        self.undo_mgr._num_pushed_textstep = 5
        self.undo_mgr._num_pushed_drawstep = 3
        self.undo_mgr.clear()
        assert self.undo_mgr._num_pushed_textstep == 0
        assert self.undo_mgr._num_pushed_drawstep == 0

    def test_is_dirty_initially_false(self):
        assert not self.undo_mgr.is_dirty()

    def test_mark_clean_resets_state(self):
        self.undo_mgr._saved_text_step = 0
        self.undo_mgr._saved_draw_step = 0
        self.undo_mgr.mark_clean()
        assert not self.undo_mgr.is_dirty()

    def test_get_text_stack(self):
        stack = self.undo_mgr.get_text_stack()
        assert stack is not None

    def test_get_draw_stack(self):
        stack = self.undo_mgr.get_draw_stack()
        assert stack is not None

    def test_clear_text_stack(self):
        self.undo_mgr._num_pushed_textstep = 5
        self.undo_mgr.clear_text_stack()
        assert self.undo_mgr._num_pushed_textstep == 0

    def test_clear_draw_stack(self):
        self.undo_mgr._num_pushed_drawstep = 5
        self.undo_mgr.clear_draw_stack()
        assert self.undo_mgr._num_pushed_drawstep == 0
