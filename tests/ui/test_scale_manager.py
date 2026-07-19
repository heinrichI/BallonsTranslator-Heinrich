"""Tests for ScaleManager."""
import pytest
from ui.scale_manager import ScaleManager


class TestScaleManager:
    def setup_method(self):
        self.scale_mgr = ScaleManager()

    def test_get_scale_initial(self):
        assert self.scale_mgr.get_scale() == 1.0

    def test_get_scale_percentage(self):
        assert self.scale_mgr.get_scale_percentage() == 100

    def test_zoom_in(self):
        initial = self.scale_mgr.get_scale()
        self.scale_mgr.zoom_in()
        assert self.scale_mgr.get_scale() > initial

    def test_zoom_out(self):
        initial = self.scale_mgr.get_scale()
        self.scale_mgr.zoom_out()
        assert self.scale_mgr.get_scale() < initial

    def test_reset_scale(self):
        self.scale_mgr.set_scale(2.0)
        self.scale_mgr.reset_scale()
        assert self.scale_mgr.get_scale() == 1.0

    def test_min_scale_limit(self):
        self.scale_mgr.set_scale(0.001)
        assert self.scale_mgr.get_scale() >= ScaleManager.MIN_SCALE

    def test_max_scale_limit(self):
        self.scale_mgr.set_scale(100.0)
        assert self.scale_mgr.get_scale() <= ScaleManager.MAX_SCALE

    def test_set_view(self):
        mock_view = object()
        self.scale_mgr.set_view(mock_view)
        assert self.scale_mgr._view is mock_view
