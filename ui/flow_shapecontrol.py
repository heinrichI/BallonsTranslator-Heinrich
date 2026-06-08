"""
FlowShapeControl + FlowControlHandle — replace TextBlkShapeControl.

DEFAULT_POINTS_PER_SIDE*2 draggable circular handles (left + right) that
modify the flow boundary points of a FlowTextBlkItem.  Handles are only
visible on hover or when the item is under control.

2 diamond handles (top/bottom) for resizing the block height.
"""

import logging

from qtpy.QtWidgets import QGraphicsItem, QGraphicsEllipseItem, QGraphicsSceneMouseEvent, QWidget, QStyleOptionGraphicsItem, QLabel, QMenu
from qtpy.QtCore import Qt, QRectF, QPointF, QSizeF
from qtpy.QtGui import QPainter, QPen, QColor, QBrush, QPolygonF

from .flow_textitem import DEFAULT_POINTS_PER_SIDE, MIN_POINTS_PER_SIDE

logger = logging.getLogger('BallonTranslator')

def _fmt_pts(pts):
    return '[' + ', '.join(f'({p.x():.1f},{p.y():.1f})' for p in pts) + ']'

HANDLE_RADIUS = 6       # px at scale=1
RESIZE_HANDLE_SIZE = 8  # px at scale=1

class FlowControlHandle(QGraphicsEllipseItem):
    """Draggable circular handle for one boundary control point."""

    def __init__(self, parent: 'FlowShapeControl', side: str, point_idx: int):
        r = HANDLE_RADIUS
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self.ctrl: FlowShapeControl = parent
        self.side = side          # 'left' or 'right'
        self.point_idx = point_idx
        self._radius = r
        self._dragging = False
        self._drag_start_pos = QPointF()

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        fill = QColor(255, 255, 255, 200) if side == 'left' else QColor(30, 147, 229, 200)
        self.setBrush(QBrush(fill))
        self.setPen(QPen(QColor(30, 100, 200), 1.5))

    def setRadius(self, r: float):
        self._radius = r
        self.setRect(-r, -r, r * 2, r * 2)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.scenePos()
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging:
            return
        blk_item = self.ctrl.blk_item
        if blk_item is None:
            return
        new_pos = blk_item.mapFromScene(event.scenePos())
        if self.side == 'left':
            blk_item._left_points[self.point_idx] = new_pos
        else:
            blk_item._right_points[self.point_idx] = new_pos
        blk_item._update_flow_layout()
        self.ctrl.updateHandlePositions()

        item_pos = blk_item.pos()
        item_rect = blk_item.boundingRect()
        logger.debug(
            'DRAG side=%s idx=%d | item_pos=(%.1f,%.1f) bounding=(%.1f,%.1f,%.1f,%.1f) | '
            'left=%s | right=%s',
            self.side, self.point_idx,
            item_pos.x(), item_pos.y(),
            item_rect.x(), item_rect.y(), item_rect.width(), item_rect.height(),
            _fmt_pts(blk_item._left_points),
            _fmt_pts(blk_item._right_points),
        )
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        self._dragging = False
        event.accept()

    def showHandleContextMenu(self, screen_pos):
        """Called from Canvas.mouseReleaseEvent on right-click on this handle."""
        blk_item = self.ctrl.blk_item
        if blk_item is None:
            return
        pts = blk_item._left_points if self.side == 'left' else blk_item._right_points
        can_delete = len(pts) > MIN_POINTS_PER_SIDE
        menu = QMenu()
        del_action = menu.addAction("Удалить точку")
        del_action.setEnabled(can_delete)
        screen_pt = screen_pos.toPoint() if hasattr(screen_pos, 'toPoint') else screen_pos
        action = menu.exec(screen_pt)
        if action == del_action and can_delete:
            del pts[self.point_idx]
            blk_item._update_flow_layout()
            self.ctrl.rebuildHandles()


class FlowResizeHandle(QGraphicsItem):
    """Diamond-shaped handle for top/bottom boundary resizing."""

    def __init__(self, parent: 'FlowShapeControl', edge: str):
        super().__init__(parent)
        self.ctrl: FlowShapeControl = parent
        self.edge = edge  # 'top' or 'bottom'
        self._size = RESIZE_HANDLE_SIZE
        self._dragging = False
        self._last_scene_y = 0.0

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def setSize(self, s: float):
        self._size = s
        self.prepareGeometryChange()

    def boundingRect(self) -> QRectF:
        s = self._size
        return QRectF(-s, -s, s * 2, s * 2)

    def paint(self, painter: QPainter, option, widget=None):
        s = self._size * 0.8
        diamond = QPolygonF([
            QPointF(0, -s),
            QPointF(s, 0),
            QPointF(0, s),
            QPointF(-s, 0),
        ])
        painter.setBrush(QBrush(QColor(255, 165, 0, 220)))
        painter.setPen(QPen(QColor(180, 100, 0), 1.5))
        painter.drawPolygon(diamond)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_scene_y = event.scenePos().y()
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging:
            return
        blk_item = self.ctrl.blk_item
        if blk_item is None:
            return

        scene_y = event.scenePos().y()
        dy_scene = scene_y - self._last_scene_y
        self._last_scene_y = scene_y

        p0 = blk_item.mapFromScene(QPointF(0, 0))
        p1 = blk_item.mapFromScene(QPointF(0, dy_scene))
        dy_local = p1.y() - p0.y()

        left_pts = blk_item._left_points
        right_pts = blk_item._right_points

        if self.edge == 'top':
            left_pts[0] = QPointF(left_pts[0].x(), left_pts[0].y() + dy_local)
            right_pts[0] = QPointF(right_pts[0].x(), right_pts[0].y() + dy_local)
            left_pts[1] = QPointF(left_pts[1].x(), left_pts[1].y() + dy_local * 0.5)
            right_pts[1] = QPointF(right_pts[1].x(), right_pts[1].y() + dy_local * 0.5)
        else:  # bottom
            left_pts[-1] = QPointF(left_pts[-1].x(), left_pts[-1].y() + dy_local)
            right_pts[-1] = QPointF(right_pts[-1].x(), right_pts[-1].y() + dy_local)
            mid = len(left_pts) // 2
            left_pts[mid] = QPointF(left_pts[mid].x(), left_pts[mid].y() + dy_local * 0.5)
            right_pts[mid] = QPointF(right_pts[mid].x(), right_pts[mid].y() + dy_local * 0.5)

        blk_item._update_flow_layout()
        self.ctrl.updateHandlePositions()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        self._dragging = False
        event.accept()


class FlowShapeControl(QGraphicsItem):
    """
    Replaces TextBlkShapeControl for FlowTextBlkItem.

    Public interface is kept compatible with the original TextBlkShapeControl
    so existing code in canvas.py / scenetext_manager.py works without changes.
    """

    reshaping: bool = False

    def __init__(self, parent_widget):
        super().__init__()
        self.gv = parent_widget
        self.blk_item = None
        self.current_scale: float = 1.0
        self.need_rescale: bool = False

        # DEFAULT_POINTS_PER_SIDE left handles then DEFAULT_POINTS_PER_SIDE right handles
        self.handles: list[FlowControlHandle] = []
        for idx in range(DEFAULT_POINTS_PER_SIDE):
            self.handles.append(FlowControlHandle(self, 'left', idx))
        for idx in range(DEFAULT_POINTS_PER_SIDE):
            self.handles.append(FlowControlHandle(self, 'right', idx))

        # 2 resize handles: top and bottom
        self.top_handle = FlowResizeHandle(self, 'top')
        self.bottom_handle = FlowResizeHandle(self, 'bottom')
        self._resize_handles = [self.top_handle, self.bottom_handle]

        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)

        # Compatibility stubs expected by canvas / textedit_commands
        self.previewPixmap = _NullPixmapItem(self)
        self.angleLabel = QLabel(parent_widget)
        self.angleLabel.setObjectName("angleLabel")
        self.angleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.angleLabel.setHidden(True)

        self.setVisible(False)

    # ── QGraphicsItem required overrides ──────────────────────

    def boundingRect(self) -> QRectF:
        return QRectF()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        pass

    # ── Public API (compatible with TextBlkShapeControl) ──────

    def setBlkItem(self, blk_item):
        if self.blk_item == blk_item and self.isVisible():
            return
        if self.blk_item is not None:
            self.blk_item.under_ctrl = False
            if hasattr(self.blk_item, 'isEditing') and self.blk_item.isEditing():
                self.blk_item.endEdit()
            self.blk_item.update()

        self.blk_item = blk_item
        if blk_item is None:
            self.hide()
            return
        blk_item.under_ctrl = True
        blk_item.update()
        has_flow = hasattr(blk_item, '_left_points') and bool(blk_item._left_points)
        if has_flow:
            self.rebuildHandles()
            for h in self._resize_handles:
                h.setVisible(True)
        else:
            for h in self.handles:
                h.setVisible(False)
            for h in self._resize_handles:
                h.setVisible(False)
        self.show()

    def rebuildHandles(self):
        """Recreate FlowControlHandle children to match current point counts."""
        blk_item = self.blk_item
        for h in self.handles:
            h.setParentItem(None)
            if h.scene():
                h.scene().removeItem(h)
        self.handles.clear()

        if blk_item is not None and hasattr(blk_item, '_left_points'):
            for idx in range(len(blk_item._left_points)):
                self.handles.append(FlowControlHandle(self, 'left', idx))
            for idx in range(len(blk_item._right_points)):
                self.handles.append(FlowControlHandle(self, 'right', idx))

        r = HANDLE_RADIUS / self.current_scale
        for h in self.handles:
            h.setRadius(r)
            pen = h.pen()
            pen.setWidthF(1.5 / self.current_scale)
            h.setPen(pen)
            h.setVisible(True)

        self.updateHandlePositions()

    def updateHandlePositions(self):
        """Sync handle positions from item's boundary points."""
        blk_item = self.blk_item
        if blk_item is None:
            return
        if not hasattr(blk_item, '_left_points') or not blk_item._left_points:
            return
        super().setPos(QPointF(0, 0))
        all_points = blk_item._left_points + blk_item._right_points
        for handle, pt in zip(self.handles, all_points):
            scene_pos = blk_item.mapToScene(pt)
            handle.setPos(scene_pos)
            logger.debug(
                'updateHandlePositions: side=%s idx=%d | item_local=(%.1f,%.1f) -> scene=(%.1f,%.1f)',
                handle.side, handle.point_idx,
                pt.x(), pt.y(),
                scene_pos.x(), scene_pos.y(),
            )

        # Top handle: midpoint of top-left and top-right
        tl = blk_item.mapToScene(blk_item._left_points[0])
        tr = blk_item.mapToScene(blk_item._right_points[0])
        self.top_handle.setPos(QPointF((tl.x() + tr.x()) / 2, (tl.y() + tr.y()) / 2))

        # Bottom handle: midpoint of bottom-left and bottom-right
        bl = blk_item.mapToScene(blk_item._left_points[-1])
        br = blk_item.mapToScene(blk_item._right_points[-1])
        self.bottom_handle.setPos(QPointF((bl.x() + br.x()) / 2, (bl.y() + br.y()) / 2))

    def updateBoundingRect(self):
        """Compat shim — just refresh handle positions."""
        self.updateHandlePositions()

    def updateScale(self, scale: float):
        if not self.isVisible():
            if scale != self.current_scale:
                self.need_rescale = True
                self.current_scale = scale
            return
        self.current_scale = scale
        r = HANDLE_RADIUS / scale
        for h in self.handles:
            h.setRadius(r)
            pen = h.pen()
            pen.setWidthF(1.5 / scale)
            h.setPen(pen)
        s = RESIZE_HANDLE_SIZE / scale
        for h in self._resize_handles:
            h.setSize(s)

    def startEditing(self):
        """Hide flow handles when entering text edit mode."""
        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)

    def endEditing(self):
        """Show flow handles again when exiting text edit mode."""
        has_flow = self.blk_item is not None and \
                   hasattr(self.blk_item, '_left_points') and \
                   bool(self.blk_item._left_points)
        visible = has_flow and not self.blk_item.isEditing()
        for h in self.handles:
            h.setVisible(visible)
        for h in self._resize_handles:
            h.setVisible(visible)

    def hideControls(self):
        for h in self.handles:
            h.hide()
        for h in self._resize_handles:
            h.hide()

    def showControls(self):
        for h in self.handles:
            h.show()
        for h in self._resize_handles:
            h.show()

    def setAngle(self, angle: float):
        pass

    def setPos(self, *args):
        """Compatibility method for canvas drag-create positioning (accepts QPointF or x, y)."""
        if len(args) == 2:
            pos = QPointF(args[0], args[1])
        else:
            pos = args[0]
        if self.blk_item is not None:
            self.blk_item.setPos(pos)

    def setRect(self, rect: QRectF):
        """Compatibility method for canvas drag-create rectangle."""
        if self.blk_item is None:
            self._drag_rect = rect
            return
        self.blk_item.setRect(rect)

    def rect(self) -> QRectF:
        """Compatibility method for canvas drag-create readback."""
        if hasattr(self, '_drag_rect') and self._drag_rect is not None:
            return self._drag_rect
        if self.blk_item is not None:
            return self.blk_item.absBoundingRect(qrect=True)
        return QRectF()

    def handleContextMenu(self, scene_pos: QPointF, screen_pos) -> bool:
        """
        Handle right-click on flow handles or FlowTextBlkItem.
        Returns True if a flow-specific item handled the event, False to fall
        through to the standard canvas context menu.
        """
        from .flow_textitem import FlowTextBlkItem

        for item in self.scene().items(scene_pos):
            if isinstance(item, FlowControlHandle):
                item.showHandleContextMenu(screen_pos)
                return True
            if isinstance(item, FlowTextBlkItem):
                item.showFlowContextMenu(scene_pos, screen_pos)
                return True
        return False

    def show(self):
        super().show()
        if self.need_rescale:
            self.updateScale(self.current_scale)
            self.need_rescale = False
        has_flow = self.blk_item is not None and \
                   hasattr(self.blk_item, '_left_points') and \
                   bool(self.blk_item._left_points) and \
                   not getattr(self.blk_item, '_editing', False)
        for h in self.handles:
            h.setVisible(has_flow)
        for h in self._resize_handles:
            h.setVisible(has_flow)
        self.setZValue(1)

    def hide(self):
        super().hide()
        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)

    def ctrlblockPressed(self):
        if self.scene() is not None:
            self.scene().clearSelection()
        if self.blk_item is not None:
            self.blk_item.endEdit()

    # ── Rotation compatibility ───────────────────────────────

    def rotation(self) -> float:
        if self.blk_item is not None:
            return self.blk_item.rotation()
        return 0.0

    def setRotation(self, angle: float):
        pass

    def sceneBoundingRect(self) -> QRectF:
        if self.blk_item is not None:
            return self.blk_item.sceneBoundingRect()
        return QRectF()


class _NullPixmapItem(QGraphicsItem):
    """Stub previewPixmap to satisfy code that calls setVisible / setOpacity."""

    def __init__(self, parent):
        super().__init__(parent)

    def boundingRect(self) -> QRectF:
        return QRectF()

    def paint(self, painter, option, widget=None):
        pass

    def setPixmap(self, pixmap):
        pass

    def setOpacity(self, v: float):
        pass

    def setVisible(self, visible: bool):
        pass