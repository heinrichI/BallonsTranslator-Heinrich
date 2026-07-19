"""Tests for MainPresenter."""
import pytest
from unittest.mock import MagicMock
from ui.main_presenter import MainPresenter
from ui.event_bus import EventBus, Events


@pytest.fixture(autouse=True)
def reset_event_bus():
    """Reset EventBus singleton before each test."""
    EventBus.reset_instance()
    yield
    EventBus.reset_instance()


class TestMainPresenter:
    def setup_method(self):
        self.model = MagicMock()
        self.view = MagicMock()
        self.event_bus = EventBus.get_instance()
        self.presenter = MainPresenter(self.model, self.view, self.event_bus)

    def test_subscribe_to_events(self):
        assert self.event_bus.has_subscribers(Events.UNDO)
        assert self.event_bus.has_subscribers(Events.REDO)

    def test_open_project_calls_model_load(self):
        self.presenter.open_project('/test/dir')
        self.model.load.assert_called_once_with('/test/dir')

    def test_open_project_publishes_event(self):
        received = []
        self.event_bus.subscribe(Events.PROJECT_OPENED, lambda d: received.append(d))

        self.presenter.open_project('/test/dir')
        assert '/test/dir' in received

    def test_manual_save_delegates_to_view(self):
        self.view.leftBar.imgTransChecker.isChecked.return_value = True
        self.model.directory = '/test/dir'

        self.presenter.manual_save()
        self.view.saveCurrentPage.assert_called_once()

    def test_on_undo_calls_canvas_undo(self):
        self.presenter._on_undo()
        self.view.canvas.undo.assert_called_once()

    def test_on_redo_calls_canvas_redo(self):
        self.presenter._on_redo()
        self.view.canvas.redo.assert_called_once()
