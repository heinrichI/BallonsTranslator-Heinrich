r"""
Regression tests: selection hygiene (fix for "dragged one block, three moved").

Background: programmatic selection paths used to ADD to the current scene
selection instead of replacing it (paste, undo/redo of add, block
duplication, interface restore, keyboard navigation). A stale multi-selection
then survives into the next drag and makes several blocks move at once,
because MoveBlkItemsCommand is built from ALL selected items.

Also covers the diagnostics added to trace the origin of selection changes:
- SceneTextManager.onTextBlkItemMoved logs a WARNING (not just DEBUG) when a
  drag moves more than one block.
- Canvas.on_selection_changed logs the new selection state with context.

Run with:
    set QT_QPA_PLATFORM=offscreen
    myenv\Scripts\python -m pytest tests/ui/test_selection_hygiene.py -v
"""
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qtpy.QtCore import QPointF, Qt
from qtpy.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.flow_shapecontrol import FlowControlHandle, FlowShapeControl
from ui.scenetext_manager import (
    CreateItemCommand,
    PasteBlkItemsCommand,
    SceneTextManager,
)
from ui.canvas import Canvas

BALLON_LOGGER = "BallonTranslator"  # utils.logger logger name


def _make_item(scene, idx, xyxy=(0, 0, 400, 200)) -> FlowTextBlkItem:
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = f"text {idx}"
    blk.fontformat.size = 24.0
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    item = FlowTextBlkItem(blk, idx=idx, show_rect=False)
    item.setPos(QPointF(x1, y1))
    scene.addItem(item)
    return item


class _StubEvent:
    """Minimal QGraphicsSceneMouseEvent stub for handle press tests."""

    def __init__(self, button=Qt.MouseButton.LeftButton,
                 mods=Qt.KeyboardModifier.NoModifier):
        self._button = button
        self._mods = mods

    def button(self):
        return self._button

    def modifiers(self):
        return self._mods

    def scenePos(self):
        return QPointF(0, 0)

    def accept(self):
        pass


def _make_shape_control(scene, blk_item):
    """Real FlowShapeControl in the scene, attached to blk_item."""
    ctrl = FlowShapeControl(QWidget())
    scene.addItem(ctrl)
    ctrl.blk_item = blk_item
    return ctrl


class _StubCanvas:
    """Minimal stand-in for Canvas: a real scene + the selection guard flag.

    PasteBlkItemsCommand / select_single only touch these attributes, and a
    real QGraphicsScene does not allow arbitrary attribute assignment."""

    def __init__(self, scene):
        self.scene = scene
        self.block_selection_signal = False

    def clearSelection(self):
        self.scene.clearSelection()

    def selected_text_items(self, sort: bool = True):
        items = [i for i in self.scene.selectedItems() if hasattr(i, "idx")]
        if sort:
            items.sort(key=lambda i: i.idx)
        return items


@pytest.fixture
def ballon_caplog(caplog):
    """caplog for the 'BallonTranslator' logger (propagate=False by default)."""
    lg = logging.getLogger(BALLON_LOGGER)
    old = lg.propagate
    lg.propagate = True
    yield caplog
    lg.propagate = old


class TestSelectionHygiene:
    def test_select_single_replaces_selection(self, scene):
        """SceneTextManager.select_single: only the given block stays selected."""
        a = _make_item(scene, 0)
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        a.setSelected(True)
        b.setSelected(True)

        fake_self = SimpleNamespace(canvas=_StubCanvas(scene))
        SceneTextManager.select_single(fake_self, a)

        assert scene.selectedItems() == [a]

    def test_paste_command_replaces_previous_selection(self, scene):
        """Pasting must clear the pre-existing selection, not extend it."""
        a = _make_item(scene, 0)
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        c = _make_item(scene, 2, (1200, 0, 1600, 200))
        a.setSelected(True)
        c.setSelected(True)

        ctrl = SimpleNamespace(
            canvas=_StubCanvas(scene),
            on_incanvas_selection_changed=lambda: None,
        )
        PasteBlkItemsCommand([b], [MagicMock()], ctrl)

        assert scene.selectedItems() == [b]

    def test_paste_command_keeps_multi_paste(self, scene):
        """All pasted blocks are selected (multi-paste is a feature)."""
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        c = _make_item(scene, 2, (1200, 0, 1600, 200))
        old = _make_item(scene, 0)
        old.setSelected(True)

        ctrl = SimpleNamespace(
            canvas=_StubCanvas(scene),
            on_incanvas_selection_changed=lambda: None,
        )
        PasteBlkItemsCommand([b, c], [MagicMock(), MagicMock()], ctrl)

        assert set(scene.selectedItems()) == {b, c}

    def test_add_command_first_redo_uses_select_single(self, scene):
        """First redo (block restoration) delegates to ctrl.select_single."""
        item = _make_item(scene, 0)
        calls = []
        ctrl = SimpleNamespace(
            pairwidget_list=[MagicMock()],
            txtblkShapeControl=MagicMock(),
            addTextBlock=lambda item: None,
            select_single=lambda it: calls.append(it),
            recoverTextblkItemList=lambda *a, **kw: None,
        )
        cmd = CreateItemCommand(item, ctrl)
        cmd.redo()

        assert calls == [item]


class TestMoveDiagnostics:
    def test_moved_logs_warning_when_multi(self, scene, ballon_caplog):
        """A multi-move (n>1) must be logged at WARNING, not just DEBUG."""
        b1 = _make_item(scene, 1)
        b2 = _make_item(scene, 2, (600, 0, 1000, 200))
        b1.setSelected(True)
        b2.setSelected(True)
        for b in (b1, b2):
            b.oldPos = b.pos()

        fake_self = SimpleNamespace(
            canvas=_StubCanvas(scene),
            txtblkShapeControl=MagicMock(),
            push_undo_command=lambda cmd: None,
        )
        with ballon_caplog.at_level(logging.WARNING, logger=BALLON_LOGGER):
            SceneTextManager.onTextBlkItemMoved(fake_self)

        warnings = [r for r in ballon_caplog.records if r.levelno >= logging.WARNING]
        assert any("[FLOWDRAG]" in r.message and "multi-move" in r.message for r in warnings)

    def test_moved_no_warning_for_single(self, scene, ballon_caplog):
        """A single-block move stays at DEBUG level (no false alarms)."""
        b1 = _make_item(scene, 1)
        b1.setSelected(True)
        b1.oldPos = b1.pos()

        fake_self = SimpleNamespace(
            canvas=_StubCanvas(scene),
            txtblkShapeControl=MagicMock(),
            push_undo_command=lambda cmd: None,
        )
        with ballon_caplog.at_level(logging.DEBUG, logger=BALLON_LOGGER):
            SceneTextManager.onTextBlkItemMoved(fake_self)

        warnings = [r for r in ballon_caplog.records if r.levelno >= logging.WARNING]
        assert not any("multi-move" in r.message for r in warnings)

    def test_selection_changed_logs_state(self, ballon_caplog):
        """Canvas.on_selection_changed logs the new selection with context."""
        mock_self = MagicMock()
        mock_self.rubber_band.isVisible.return_value = False
        mock_self.hasFocus.return_value = False
        mock_self.block_selection_signal = False
        item = MagicMock()
        item.idx = 5
        mock_self.selected_text_items.return_value = [item]

        with ballon_caplog.at_level(logging.DEBUG, logger=BALLON_LOGGER):
            Canvas.on_selection_changed(mock_self)

        assert any(
            "[SEL] selection -> [5]" in r.message for r in ballon_caplog.records
        )


class TestFlowHandleSelection:
    """Handle presses must use standard Qt selection semantics.

    Regression: a bare setSelected(True) in the handle press handlers used to
    ADD the handled block to whatever else was selected. Shaping one block's
    flow handles therefore silently grew the scene selection, and a later
    drag of an already-selected block moved all of them at once (the
    "dragged one block, several moved" bug, confirmed in logs)."""

    def test_handle_press_selects_only_that_block(self, scene, qapp):
        a = _make_item(scene, 0)
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        a.setSelected(True)  # pre-existing selection

        ctrl = _make_shape_control(scene, b)
        FlowControlHandle.mousePressEvent(ctrl.handles[0], _StubEvent())

        assert scene.selectedItems() == [b]

    def test_handle_press_ctrl_is_additive(self, scene, qapp):
        a = _make_item(scene, 0)
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        a.setSelected(True)

        ctrl = _make_shape_control(scene, b)
        FlowControlHandle.mousePressEvent(
            ctrl.handles[0], _StubEvent(mods=Qt.KeyboardModifier.ControlModifier))

        assert set(scene.selectedItems()) == {a, b}

    def test_handle_press_on_selected_block_keeps_selection(self, scene, qapp):
        """Pressing an already-selected block keeps the multi-selection
        (standard Qt: pressing a selected item does not clear the rest)."""
        a = _make_item(scene, 0)
        b = _make_item(scene, 1, (600, 0, 1000, 200))
        a.setSelected(True)
        b.setSelected(True)

        ctrl = _make_shape_control(scene, b)
        FlowControlHandle.mousePressEvent(ctrl.handles[0], _StubEvent())

        assert set(scene.selectedItems()) == {a, b}
