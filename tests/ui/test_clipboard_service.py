"""Tests for ClipboardService."""
import pytest
from qtpy.QtCore import QPointF
from ui.clipboard_service import ClipboardService


class TestClipboardService:
    def setup_method(self):
        self.clipboard = ClipboardService()

    def test_has_blocks_empty(self):
        assert not self.clipboard.has_blocks()

    def test_get_block_count_empty(self):
        assert self.clipboard.get_block_count() == 0

    def test_clear(self):
        self.clipboard.clear()
        assert not self.clipboard.has_blocks()
        assert self.clipboard.get_block_count() == 0

    def test_set_get_text(self):
        self.clipboard.set_text("hello")
        assert self.clipboard.get_text() == "hello"

    def test_clear_text(self):
        self.clipboard.set_text("hello")
        self.clipboard.clear()
        assert self.clipboard.get_text() == ""
