"""
Regression test: moving a flow block body must be undoable (Ctrl+Z).

FlowShapeControl covers the flow block and intercepts all mouse events —
the underlying TextBlkItem never receives press/move/release (see the
comment in FlowShapeControl.mousePressEvent). SceneTextManager pushes the
undoable MoveBlkItemsCommand only on the item's `moved` signal
(onTextBlkItemMoved), so FlowShapeControl must emit `moved` itself on
mouse release — otherwise dragging a flow block produces NO undo command
and Ctrl+Z does nothing for the move.

Run with:
    set QT_QPA_PLATFORM=offscreen
    cd j:\Comic translate\BallonsTranslator
    myenv\Scripts\python -m pytest tests/ui/test_flow_block_move_undo.py -v
"""
import os
import sys
from typing import List
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtCore import Qt, QPointF

from types import SimpleNamespace

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.flow_shapecontrol import FlowShapeControl
from ui.undo_manager import UndoManager
from ui.textedit_commands import MoveBlkItemsCommand
from utils.logger import logger as LOGGER


def _make_flow_item(scene, xyxy=(0, 0, 400, 200),
                    text: str = "Hello world test text", font_size: float = 24.0) -> FlowTextBlkItem:
    """Helper: create a FlowTextBlkItem with control points, added to scene."""
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    item = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _mouse_event(scene_pos: QPointF,
                 button: Qt.MouseButton = Qt.MouseButton.LeftButton,
                 modifiers=Qt.KeyboardModifier.NoModifier) -> MagicMock:
    """Stub QGraphicsSceneMouseEvent with the methods the handlers use."""
    ev = MagicMock()
    ev.button.return_value = button
    ev.buttons.return_value = button
    ev.scenePos.return_value = scene_pos
    ev.pos.return_value = scene_pos
    ev.modifiers.return_value = modifiers
    return ev


class TestFlowBlockMoveUndo:
    """Body drag of a flow block must be an undoable command on the draw stack."""

    def test_body_drag_emits_moved_on_release(self, scene):
        """FlowShapeControl.mouseReleaseEvent must emit blk_item.moved when
        the block position changed during the drag (mirrors
        TextBlkItem.mouseReleaseEvent)."""
        item = _make_flow_item(scene)
        ctrl = FlowShapeControl(parent_widget=None)
        scene.addItem(ctrl)
        ctrl.setBlkItem(item)

        emitted: List[bool] = []
        item.moved.connect(lambda: emitted.append(True))

        start = QPointF(200.0, 100.0)
        ctrl.mousePressEvent(_mouse_event(start))
        ctrl.mouseMoveEvent(_mouse_event(start + QPointF(50.0, 50.0)))
        ctrl.mouseReleaseEvent(_mouse_event(start + QPointF(50.0, 50.0)))

        assert item.pos() != QPointF(0.0, 0.0), "drag should have moved the block"
        assert emitted == [True], (
            "FlowShapeControl must emit blk_item.moved on release after a body drag — "
            "without it SceneTextManager.onTextBlkItemMoved never pushes "
            "MoveBlkItemsCommand and the move cannot be undone"
        )

    def test_body_drag_without_move_does_not_emit_moved(self, scene):
        """A plain click (no displacement) must not push an undo step."""
        item = _make_flow_item(scene)
        ctrl = FlowShapeControl(parent_widget=None)
        scene.addItem(ctrl)
        ctrl.setBlkItem(item)

        emitted: List[bool] = []
        item.moved.connect(lambda: emitted.append(True))

        start = QPointF(200.0, 100.0)
        ctrl.mousePressEvent(_mouse_event(start))
        ctrl.mouseReleaseEvent(_mouse_event(start))

        assert emitted == [], "click without displacement must not emit moved"

    def test_ctrl_z_restores_flow_block_position(self, scene):
        """End-to-end at the stack level: drag body -> command pushed to the
        draw stack -> UndoManager.undo() restores the pre-drag position,
        redo() applies it again (what Ctrl+Z / Ctrl+Y do in 'smart' mode)."""
        item = _make_flow_item(scene)
        ctrl = FlowShapeControl(parent_widget=None)
        scene.addItem(ctrl)
        ctrl.setBlkItem(item)

        mgr = UndoManager()

        # Wire exactly like SceneTextManager: moved -> MoveBlkItemsCommand
        # pushed via push_draw_command() -> draw stack.
        def on_moved() -> None:
            mgr.push_draw_command(MoveBlkItemsCommand([item], ctrl))

        item.moved.connect(on_moved)

        old_pos = item.pos()
        start = QPointF(200.0, 100.0)
        ctrl.mousePressEvent(_mouse_event(start))
        ctrl.mouseMoveEvent(_mouse_event(start + QPointF(50.0, 50.0)))
        ctrl.mouseReleaseEvent(_mouse_event(start + QPointF(50.0, 50.0)))

        assert item.pos() != old_pos, "drag should have moved the block"
        assert mgr.get_draw_stack().canUndo(), (
            "draw stack must contain the move command after dragging the flow block body"
        )

        # Ctrl+Z
        mgr.undo()
        assert item.pos() == old_pos, (
            f"undo must restore the pre-drag position, got {item.pos()} expected {old_pos}"
        )
        # block rect must be re-synced with the restored position
        assert item.blk.xyxy[0] == int(round(old_pos.x() + min(
            p.x() for p in item._left_points + item._right_points))), "blk.xyxy not re-synced"

        # Ctrl+Y
        mgr.redo()
        assert item.pos() != old_pos, "redo must re-apply the move"


class TestMoveLoggingDoesNotBreakMovePath:
    """error25 regression: a %-format mismatch in the FLOWDRAG log of
    onTextBlkItemMoved raised TypeError out of LOGGER.debug during
    mouseReleaseEvent. Logging must never break the move path: the
    MoveBlkItemsCommand must still be pushed, and mismatched log calls
    must not propagate at all."""

    def test_onTextBlkItemMoved_pushes_command_with_selection(self, scene):
        """Multiple selected blocks moved: the FLOWDRAG log (multi-block
        join string) must not raise, and MoveBlkItemsCommand must be pushed."""
        import ui.scenetext_manager as stm_mod

        item1 = _make_flow_item(scene, xyxy=(0, 0, 200, 100))
        item2 = _make_flow_item(scene, xyxy=(300, 0, 500, 100))
        item2.idx = 1

        fake = SimpleNamespace(
            canvas=SimpleNamespace(selected_text_items=lambda: [item1, item2]),
            txtblkShapeControl=MagicMock(),
            push_undo_command=MagicMock(),
            textblk_item_list=[item1, item2],
        )
        stm_mod.SceneTextManager.onTextBlkItemMoved(fake)  # must not raise

        fake.push_undo_command.assert_called_once()
        cmd = fake.push_undo_command.call_args[0][0]
        assert isinstance(cmd, MoveBlkItemsCommand)
        assert list(cmd.items) == [item1, item2]

    def test_mismatched_log_format_does_not_propagate(self):
        """A log call with more %-specs than args must be swallowed by the
        logger (sanitized), never raise to the caller."""
        LOGGER.debug("n=%d blocks=[idx=%s oldPos=%s]", 1)  # must not raise
        LOGGER.debug("a=%s b=%s c=%s", "x", "y")  # must not raise
