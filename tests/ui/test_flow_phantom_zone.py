"""
Regression test: FlowShapeControl's body must not steal body presses
(the "phantom zone" bug, error23.txt #2).

FlowShapeControl is pinned at the parent origin (0,0) — updateHandlePositions
resets pos to (0,0) so its handles stay in parent coordinates. When
boundingRect() returned the owned block's LOCAL rect, the control's hit zone
was a phantom rectangle at the page's top-left, sized to the (possibly
point-inflated) rect of the last-hovered block. A press on another block
that fell inside that zone selected and dragged the WRONG block:

  * "dragging a block with modified sides sometimes grabs the neighbour" —
    modified sides inflate the block's boundingRect and thus the phantom zone;
  * "not always" — only when the press point lands inside the zone of the
    last-hovered block;
  * "selecting the neighbour first, then the target, makes it work" —
    hover re-assigns control ownership (setBlkItem on hover-enter), moving
    the phantom zone to a different place.

After the fix the control body is mouse-transparent in steady state
(empty boundingRect), exactly like the legacy TextBlkShapeControl body:
presses fall through to the block under the cursor, which handles
selection/move natively (ItemIsMovable | ItemIsSelectable). Child handles
are hit-tested independently and keep working.

Run with:
    myenv\\Scripts\\python -m pytest tests/ui/test_flow_phantom_zone.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView,
                            QGraphicsRectItem)
from qtpy.QtCore import QPointF, Qt, QRectF
from qtpy.QtGui import QTransform, QMouseEvent
from qtpy.QtCore import QEvent
from types import SimpleNamespace

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.flow_shapecontrol import FlowShapeControl


def _make_flow_item(scene: QGraphicsScene, idx: int, xyxy, text: str = "Test block") -> FlowTextBlkItem:
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = 24.0
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    blk.is_flow_mode = True
    item = FlowTextBlkItem(blk, idx=idx, show_rect=False)
    scene.addItem(item)
    item.setPos(x1, y1)
    return item


@pytest.fixture
def canvas_like(qapp: QApplication) -> SimpleNamespace:
    """Real canvas hierarchy: baseLayer -> textLayer -> flow blocks;
    FlowShapeControl is a direct child of baseLayer with z=1 (above the
    whole textLayer group), exactly like ui/canvas.py sets up."""
    scene = QGraphicsScene()
    view = QGraphicsView(scene)
    view.resize(1000, 600)
    view.setSceneRect(QRectF(0, 0, 1000, 600))
    view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    view.show()
    qapp.processEvents()

    base = QGraphicsRectItem()
    base.setRect(0, 0, 1000, 600)
    scene.addItem(base)
    text_layer = QGraphicsRectItem()
    text_layer.setRect(0, 0, 1000, 600)
    text_layer.setParentItem(base)

    # M: the block the user actually presses; N: a neighbour with modified
    # sides (boundary points dragged far out -> inflated boundingRect).
    m = _make_flow_item(scene, 0, (400, 200, 600, 280), "M")
    n = _make_flow_item(scene, 1, (800, 200, 1000, 280), "N")
    m.setParentItem(text_layer)
    n.setParentItem(text_layer)

    # "modified sides" on N: bottom-right boundary point dragged far out,
    # so N's local boundingRect spans [0,0 .. 520x260] — the phantom zone
    # at the page origin covers M's centre (500, 240).
    n._right_points[-1] = QPointF(520, 260)

    ctrl = FlowShapeControl(None)
    ctrl.setParentItem(base)
    ctrl.updateScale(1.0)
    # The user last hovered N -> control ownership = N (real path:
    # SceneTextManager.onTextBlkItemHoverEnter -> setBlkItem).
    ctrl.setBlkItem(n)

    def press_release(view: QGraphicsView, scene_pos: QPointF,
                      delta: QPointF = QPointF(0, 0)) -> None:
        """Press at scene_pos, drag by delta, release — via the viewport,
        the same event path as real mouse input."""
        def send(etype: QEvent.Type, sp: QPointF, buttons: Qt.MouseButton) -> None:
            wp = view.mapFromScene(sp)
            g = view.viewport().mapToGlobal(wp)
            ev = QMouseEvent(etype, QPointF(wp), QPointF(g),
                             Qt.MouseButton.LeftButton, buttons,
                             Qt.KeyboardModifier.NoModifier)
            QApplication.instance().sendEvent(view.viewport(), ev)

        send(QEvent.Type.MouseButtonPress, scene_pos, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, scene_pos + delta, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, scene_pos + delta, Qt.MouseButton.NoButton)
        qapp.processEvents()

    return SimpleNamespace(scene=scene, view=view, base=base,
                           text_layer=text_layer, m=m, n=n, ctrl=ctrl,
                           press_release=press_release)


class TestPhantomZone:
    """Body presses must reach the block under the cursor, not the control."""

    def test_control_body_hit_zone_is_empty(self, canvas_like) -> None:
        # Steady state: the control's local boundingRect is empty, so its
        # scene hit zone cannot cover any block anywhere on the page.
        assert canvas_like.ctrl.boundingRect().isNull()

    def test_hit_at_block_centre_is_the_block(self, canvas_like) -> None:
        # M's centre lies inside N's OLD phantom zone (N's inflated local
        # rect mapped to the page origin). The topmost hit there must be M.
        p = QPointF(500, 240)
        top = canvas_like.scene.itemAt(p, QTransform())
        assert top is canvas_like.m, (
            f"expected M to be topmost at {p}, got {type(top).__name__}")

    def test_press_on_m_moves_m_not_n(self, canvas_like) -> None:
        m, n = canvas_like.m, canvas_like.n
        canvas_like.press_release(canvas_like.view, QPointF(500, 240),
                                  QPointF(60, 30))
        assert m.pos() == QPointF(460, 230), f"M should move: {m.pos()}"
        assert n.pos() == QPointF(800, 200), f"N must NOT move: {n.pos()}"
        assert [i.idx for i in canvas_like.scene.selectedItems()] == [0], (
            "the pressed block M must be the selected one")

    def test_handles_still_hit_testable(self, canvas_like) -> None:
        # Child handles keep their own hit testing even though the control
        # body is now mouse-transparent.
        hp = canvas_like.n.mapToScene(canvas_like.n._left_points[0])
        top = canvas_like.scene.itemAt(hp, QTransform())
        assert type(top).__name__ == "FlowControlHandle", (
            f"expected FlowControlHandle at handle pos {hp}, got {type(top).__name__}")
