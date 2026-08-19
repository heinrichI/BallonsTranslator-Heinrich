"""
Integration test: the REAL app path for flow block body move undo.

Unit test (test_flow_block_move_undo.py) wires item.moved -> command
manually. This test exercises the actual handler chain:

    FlowShapeControl release
      -> blk_item.moved.emit()
      -> SceneTextManager.onTextBlkItemMoved  (real, unbound)
      -> canvas.selected_text_items()
      -> push_undo_command(MoveBlkItemsCommand(...))
      -> UndoManager (real) -> draw stack
      -> UndoManager.undo()  (what global Ctrl+Z calls in 'smart' mode)

Run:
    myenv\Scripts\python -m pytest tests/ui/test_flow_block_move_undo_integration.py -v
"""
import os
import sys
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtCore import Qt, QPointF

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.flow_shapecontrol import FlowShapeControl
from ui.scenetext_manager import SceneTextManager
from ui.textitem import TextBlkItem
from ui.undo_manager import UndoManager
from ui.textedit_commands import MoveBlkItemsCommand


def _make_flow_item(scene, xyxy=(0, 0, 400, 200),
                    text: str = "Hello world test text", font_size: float = 24.0) -> FlowTextBlkItem:
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
    ev = MagicMock()
    ev.button.return_value = button
    ev.buttons.return_value = button
    ev.scenePos.return_value = scene_pos
    ev.pos.return_value = scene_pos
    ev.modifiers.return_value = modifiers
    return ev


class _FakeCanvas:
    """Minimal canvas: selected_text_items() + setProjSaveState()."""

    def __init__(self, scene):
        self._scene = scene

    def selected_text_items(self, sort: bool = True) -> List[FlowTextBlkItem]:
        items = [it for it in self._scene.selectedItems()
                 if isinstance(it, TextBlkItem)]
        if sort:
            items.sort(key=lambda x: x.idx)
        return items

    def setProjSaveState(self, flag: bool) -> None:
        pass


class TestFlowBlockMoveUndoIntegration:
    def test_real_handler_chain_pushes_and_undoes_move(self, scene):
        item = _make_flow_item(scene)
        ctrl = FlowShapeControl(parent_widget=None)
        scene.addItem(ctrl)
        ctrl.setBlkItem(item)

        undo_mgr = UndoManager()
        canvas = _FakeCanvas(scene)

        # Fake 'self' for the real (unbound) handler + push_undo_command proxy.
        mgr = SimpleNamespace(
            canvas=canvas,
            txtblkShapeControl=ctrl,
            _undo_mgr=undo_mgr,
        )
        mgr.push_undo_command = (
            lambda command, update_pushed_step=True, is_text=False:
            undo_mgr.push_command(command, update_step=True, is_text=is_text)
        )
        item.moved.connect(lambda: SceneTextManager.onTextBlkItemMoved(mgr))

        old_pos = item.pos()
        start = QPointF(200.0, 100.0)
        ctrl.mousePressEvent(_mouse_event(start))
        ctrl.mouseMoveEvent(_mouse_event(start + QPointF(60.0, -30.0)))
        ctrl.mouseReleaseEvent(_mouse_event(start + QPointF(60.0, -30.0)))

        assert item.pos() != old_pos, "drag should have moved the block"

        # The real handler must have found the selected flow item and pushed
        # a MoveBlkItemsCommand onto the DRAW stack (is_text=False).
        draw = undo_mgr.get_draw_stack()
        assert draw.canUndo(), "real onTextBlkItemMoved path must push the move command"
        assert undo_mgr._last_pushed == 'draw', "move command must route to the draw stack"
        assert undo_mgr.get_text_stack().index() == 0, "text stack must stay untouched"

        # Global Ctrl+Z in 'smart' mode:
        undo_mgr.undo()
        assert item.pos() == old_pos, f"undo must restore {old_pos}, got {item.pos()}"

        # Data model must be consistent with the restored position:
        assert item.blk._bounding_rect[0] == int(round(old_pos.x() + min(
            p.x() for p in item._left_points + item._right_points)))
        assert item.blk.xyxy[0] == item.blk._bounding_rect[0]

        # Ctrl+Y:
        undo_mgr.redo()
        assert item.pos() != old_pos, "redo must re-apply the move"
