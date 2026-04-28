"""
FlowShapeControl + FlowControlHandle — replace TextBlkShapeControl.

6 draggable circular handles (3 left + 3 right) that modify the flow
boundary points of a FlowTextBlkItem.  Handles are only visible on hover
or when the item is under control.
"""

import logging

from qtpy.QtWidgets import QGraphicsItem, QGraphicsEllipseItem, QGraphicsSceneMouseEvent, QWidget, QStyleOptionGraphicsItem, QLabel
from qtpy.QtCore import Qt, QRectF, QPointF, QSizeF
from qtpy.QtGui import QPainter, QPen, QColor, QBrush

logger = logging.getLogger('BallonTranslator')

def _fmt_pts(pts):
    return '[' + ', '.join(f'({p.x():.1f},{p.y():.1f})' for p in pts) + ']'

HANDLE_RADIUS = 6  # px at scale=1


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
        # Map scene pos to item-local coords of blk_item
        new_pos = blk_item.mapFromScene(event.scenePos())
        if self.side == 'left':
            blk_item._left_points[self.point_idx] = new_pos
        else:
            blk_item._right_points[self.point_idx] = new_pos
        blk_item._update_flow_layout()
        self.ctrl.updateHandlePositions()

        # --- coordinate logging ---
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

        # 6 handles: left[0,1,2] then right[0,1,2]
        self.handles: list[FlowControlHandle] = []
        for idx in range(3):
            self.handles.append(FlowControlHandle(self, 'left', idx))
        for idx in range(3):
            self.handles.append(FlowControlHandle(self, 'right', idx))

        for h in self.handles:
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
        pass   # nothing to draw; handles are children

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
        # Only show flow handles for FlowTextBlkItem instances
        has_flow = hasattr(blk_item, '_left_points') and bool(blk_item._left_points)
        if has_flow:
            self.updateHandlePositions()
            for h in self.handles:
                h.setVisible(True)
        else:
            for h in self.handles:
                h.setVisible(False)
        self.show()

    def updateHandlePositions(self):
        """Sync handle positions from item's boundary points."""
        blk_item = self.blk_item
        if blk_item is None:
            return
        if not hasattr(blk_item, '_left_points') or not blk_item._left_points:
            return
        # Keep control at scene origin so handle.setPos(scene_pos) == ctrl_local
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

    def startEditing(self):
        for h in self.handles:
            h.hide()

    def endEditing(self):
        if self.isVisible():
            for h in self.handles:
                h.show()

    def hideControls(self):
        for h in self.handles:
            h.hide()

    def showControls(self):
        for h in self.handles:
            h.show()

    def setAngle(self, angle: float):
        # Flow items don't support rotation via this control, but keep compat
        pass

    def setPos(self, pos: QPointF):
        """Compatibility method for canvas drag-create positioning."""
        if self.blk_item is not None:
            self.blk_item.setPos(pos)
        # Do NOT move the control itself — it must always stay at scene origin (0,0)
        # so that handle.setPos(scene_pos) places handles correctly.

    def setRect(self, rect: QRectF):
        """Compatibility method for canvas drag-create rectangle."""
        if self.creating_textblock or self.blk_item is None:
            # In drag-create mode, just track rect internally
            self._drag_rect = rect
            return
        # Otherwise forward to block
        self.blk_item.setRect(rect)

    def rect(self) -> QRectF:
        """Compatibility method for canvas drag-create readback."""
        if hasattr(self, '_drag_rect') and self._drag_rect is not None:
            return self._drag_rect
        if self.blk_item is not None:
            return self.blk_item.absBoundingRect(qrect=True)
        return QRectF()

    def startEditing(self):
        """Hide flow handles when entering text edit mode."""
        for h in self.handles:
            h.setVisible(False)

    def endEditing(self):
        """Show flow handles again when exiting text edit mode."""
        has_flow = self.blk_item is not None and \
                   hasattr(self.blk_item, '_left_points') and \
                   bool(self.blk_item._left_points)
        for h in self.handles:
            h.setVisible(has_flow and not self.blk_item.isEditing())

    def show(self):
        super().show()
        if self.need_rescale:
            self.updateScale(self.current_scale)
            self.need_rescale = False
        # Only reveal handles when item supports flow points and not editing
        has_flow = self.blk_item is not None and \
                   hasattr(self.blk_item, '_left_points') and \
                   bool(self.blk_item._left_points) and \
                   not getattr(self.blk_item, '_editing', False)
        for h in self.handles:
            h.setVisible(has_flow)
        self.setZValue(1)

    def hide(self):
        super().hide()
        for h in self.handles:
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