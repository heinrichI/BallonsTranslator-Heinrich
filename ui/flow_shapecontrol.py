"""
FlowShapeControl + FlowControlHandle — replace TextBlkShapeControl.

DEFAULT_POINTS_PER_SIDE*2 draggable circular handles (left + right) that
modify the flow boundary points of a FlowTextBlkItem.  Handles are only
visible on hover or when the item is under control.

2 diamond handles (top/bottom) for resizing the block height.
1 circular rotation handle above the block.
"""

import math
import logging

import numpy as np
from qtpy.QtWidgets import QGraphicsItem, QGraphicsEllipseItem, QGraphicsSceneMouseEvent, QWidget, QStyleOptionGraphicsItem, QLabel, QMenu
from qtpy.QtCore import Qt, QRectF, QPointF, QSizeF, QPoint
from qtpy.QtGui import QPainter, QPen, QColor, QBrush, QPolygonF

from .flow_textitem import DEFAULT_POINTS_PER_SIDE, MIN_POINTS_PER_SIDE
from .cursor import rotateCursorList

logger = logging.getLogger('BallonTranslator')

QUIET_UI = True  # Set to False for verbose UI debug logging

def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        logger.debug(msg, *args, **kwargs)

def _fmt_pts(pts):
    return '[' + ', '.join(f'({p.x():.1f},{p.y():.1f})' for p in pts) + ']'

HANDLE_RADIUS = 6       # px at scale=1
RESIZE_HANDLE_SIZE = 8  # px at scale=1
DIAMOND_OFFSET = 10     # px offset from control points for left/right diamond handles

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
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.startReshape()
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
        _debug(
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
        if self._dragging:
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.endReshape()
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


class FlowHResizeHandle(QGraphicsItem):
    """Diamond-shaped handle for left/right boundary resizing (used in vertical mode)."""

    def __init__(self, parent: 'FlowShapeControl', edge: str):
        super().__init__(parent)
        self.ctrl: FlowShapeControl = parent
        self.edge = edge  # 'left' or 'right'
        self._size = RESIZE_HANDLE_SIZE
        self._dragging = False
        self._last_scene_x = 0.0

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

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
        painter.setBrush(QBrush(QColor(100, 200, 255, 220)))
        painter.setPen(QPen(QColor(0, 100, 180), 1.5))
        painter.drawPolygon(diamond)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_scene_x = event.scenePos().x()
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.startReshape()
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging:
            return
        blk_item = self.ctrl.blk_item
        if blk_item is None:
            return

        scene_x = event.scenePos().x()
        dx_scene = scene_x - self._last_scene_x
        self._last_scene_x = scene_x

        p0 = blk_item.mapFromScene(QPointF(0, 0))
        p1 = blk_item.mapFromScene(QPointF(dx_scene, 0))
        dx_local = p1.x() - p0.x()

        left_pts = blk_item._left_points
        right_pts = blk_item._right_points

        if self.edge == 'left':
            # Move all left boundary points horizontally
            for i in range(len(left_pts)):
                left_pts[i] = QPointF(left_pts[i].x() + dx_local, left_pts[i].y())
        else:  # right
            # Move all right boundary points horizontally
            for i in range(len(right_pts)):
                right_pts[i] = QPointF(right_pts[i].x() + dx_local, right_pts[i].y())

        # _update_flow_layout() now handles both Horizontal and Vertical layouts
        blk_item._update_flow_layout()
        self.ctrl.updateHandlePositions()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._dragging:
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.endReshape()
        self._dragging = False
        event.accept()


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
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.startReshape()
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

        # _update_flow_layout() now handles both Horizontal and Vertical layouts
        blk_item._update_flow_layout()
        self.ctrl.updateHandlePositions()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._dragging:
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                blk_item.endReshape()
        self._dragging = False
        event.accept()


ROTATION_HANDLE_RADIUS = 6  # px at scale=1
ROTATION_HANDLE_OFFSET = 20  # px above top edge at scale=1


class FlowRotationHandle(QGraphicsEllipseItem):
    """Draggable circular handle for rotating the text block."""

    def __init__(self, parent: 'FlowShapeControl'):
        r = ROTATION_HANDLE_RADIUS
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self.ctrl: FlowShapeControl = parent
        self._radius = r
        self._dragging = False
        self._rotate_start = 0.0

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self.setBrush(QBrush(QColor(255, 140, 0, 220)))
        self.setPen(QPen(QColor(180, 90, 0), 1.5))

    def setRadius(self, r: float):
        self._radius = r
        self.setRect(-r, -r, r * 2, r * 2)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            blk_item = self.ctrl.blk_item
            if blk_item is not None:
                center = blk_item.mapToScene(blk_item.boundingRect().center())
                rotate_vec = event.scenePos() - center
                rotation = np.rad2deg(math.atan2(rotate_vec.y(), rotate_vec.x()))
                self._rotate_start = -rotation + self.ctrl.rotation()
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging:
            return
        blk_item = self.ctrl.blk_item
        if blk_item is None:
            return

        center = blk_item.mapToScene(blk_item.boundingRect().center())
        rotate_vec = event.scenePos() - center
        rotation = np.rad2deg(math.atan2(rotate_vec.y(), rotate_vec.x()))
        new_angle = rotation + self._rotate_start

        self.ctrl.setAngle(new_angle)

        angle_label = self.ctrl.angleLabel
        gv = self.ctrl.gv
        pos = gv.mapFromScene(event.scenePos())
        x = max(min(pos.x(), gv.width() - angle_label.width()), 0)
        y = max(min(pos.y(), gv.height() - angle_label.height()), 0)
        angle_label.move(QPoint(x, y))
        angle_label.setText("{:.1f}°".format(new_angle))
        if not angle_label.isVisible():
            angle_label.setVisible(True)
            angle_label.raise_()

        angle = self.ctrl.rotation() + 45 * self._get_angle_idx(new_angle)
        idx = self._get_angle_idx(angle)
        self.setCursor(rotateCursorList[idx])

        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            blk_item = self.ctrl.blk_item
            self.ctrl.angleLabel.setVisible(False)
            if blk_item is not None:
                blk_item.rotated.emit(self.ctrl.rotation())
                blk_item.update()
            self.ctrl.updateBoundingRect()
        event.accept()

    def _get_angle_idx(self, angle) -> int:
        return int((angle + 22.5) % 360 / 45)


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
        self._dragging = False
        self._drag_start_pos = QPointF()
        self._block_start_pos = QPointF()

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        # DEFAULT_POINTS_PER_SIDE left handles then DEFAULT_POINTS_PER_SIDE right handles
        self.handles: list[FlowControlHandle] = []
        for idx in range(DEFAULT_POINTS_PER_SIDE):
            self.handles.append(FlowControlHandle(self, 'left', idx))
        for idx in range(DEFAULT_POINTS_PER_SIDE):
            self.handles.append(FlowControlHandle(self, 'right', idx))

        # 2 resize handles: top and bottom (shown in horizontal mode)
        self.top_handle = FlowResizeHandle(self, 'top')
        self.bottom_handle = FlowResizeHandle(self, 'bottom')
        self._resize_handles = [self.top_handle, self.bottom_handle]

        # 2 horizontal resize handles: left and right (shown in vertical mode)
        self.left_handle = FlowHResizeHandle(self, 'left')
        self.right_handle = FlowHResizeHandle(self, 'right')
        self._h_resize_handles = [self.left_handle, self.right_handle]

        # Rotation handle above the block
        self.rotation_handle = FlowRotationHandle(self)
        self.rotation_handle.setVisible(False)

        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)
        for h in self._h_resize_handles:
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
        if self.blk_item is not None:
            return self.blk_item.boundingRect()
        if hasattr(self, '_drag_rect') and self._drag_rect is not None:
            return self._drag_rect
        return QRectF()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        if self.blk_item is None and hasattr(self, '_drag_rect') and self._drag_rect is not None:
            pen = QPen(QColor(69, 71, 87), 2 / self.current_scale, Qt.PenStyle.SolidLine)
            pen.setDashPattern([7, 14])
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._drag_rect)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.blk_item is not None:
            self._dragging = True
            self._drag_start_pos = event.scenePos()
            self._block_start_pos = self.blk_item.pos()
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging or self.blk_item is None:
            return
        delta = event.scenePos() - self._drag_start_pos
        new_pos = self._block_start_pos + delta
        self.blk_item.setPos(new_pos)
        self.updateHandlePositions()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        self._dragging = False
        event.accept()

    # ── Public API (compatible with TextBlkShapeControl) ──────

    def _is_vertical(self) -> bool:
        """Check if the associated blk_item is in vertical text mode."""
        if self.blk_item is None:
            return False
        ffmt = getattr(self.blk_item, 'fontformat', None)
        return ffmt is not None and bool(ffmt.vertical)

    def _flow_handles_visible(self) -> bool:
        """Return True when flow handles should be visible (not vertical, not editing)."""
        if self.blk_item is None:
            return False
        if self._is_vertical():
            return False
        if getattr(self.blk_item, '_editing', False):
            return False
        return hasattr(self.blk_item, '_left_points') and bool(self.blk_item._left_points)

    def setBlkItem(self, blk_item):
        _debug("=== setBlkItem called ===")
        _debug("  new blk_item=%s (type=%s)", blk_item, type(blk_item).__name__ if blk_item else "None")
        if blk_item is not None:
            _debug("  new blk_item pos=%s boundingRect=%s",
                         blk_item.pos(), blk_item.boundingRect())
        if self.blk_item == blk_item and self.isVisible():
            # Same item — just refresh handle positions and visibility
            # (state may have changed e.g. vertical/horizontal toggle)
            _debug("  same blk_item — refreshing handles")
            flow_visible = self._flow_handles_visible()
            if flow_visible:
                self.rebuildHandles()
            else:
                for h in self.handles:
                    h.setVisible(False)
            has_points = hasattr(blk_item, '_left_points') and bool(blk_item._left_points)
            for h in self._resize_handles:
                h.setVisible(has_points)
            for h in self._h_resize_handles:
                h.setVisible(has_points)
            self.rotation_handle.setVisible(has_points)
            if has_points:
                self.updateHandlePositions()
            self.show()
            return
        if self.blk_item is not None:
            _debug("  old blk_item=%s type=%s pos=%s",
                         self.blk_item, type(self.blk_item).__name__,
                         self.blk_item.pos())
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
        flow_visible = self._flow_handles_visible()
        if flow_visible:
            self.rebuildHandles()
        else:
            for h in self.handles:
                h.setVisible(False)
        # Resize handles: all 4 handles visible in both modes
        has_points = hasattr(blk_item, '_left_points') and bool(blk_item._left_points)
        for h in self._resize_handles:
            h.setVisible(has_points)
        for h in self._h_resize_handles:
            h.setVisible(has_points)
        self.show()

    def rebuildHandles(self):
        """Recreate FlowControlHandle children to match current point counts."""
        blk_item = self.blk_item
        _debug("=== rebuildHandles ===")
        _debug("  old handle count=%d", len(self.handles))
        if blk_item is not None and hasattr(blk_item, '_left_points'):
            _debug("  left_points count=%d, right_points count=%d",
                         len(blk_item._left_points), len(blk_item._right_points))
            _debug("  left_points=%s", _fmt_pts(blk_item._left_points))
            _debug("  right_points=%s", _fmt_pts(blk_item._right_points))
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
            _debug("updateHandlePositions: blk_item is None — skipping")
            return
        if not hasattr(blk_item, '_left_points') or not blk_item._left_points:
            _debug("updateHandlePositions: no _left_points — skipping")
            return

        _debug("=== updateHandlePositions ===")
        _debug("  FlowShapeControl pos before=%s", super().pos())
        _debug("  blk_item=%s pos=%s boundingRect=%s",
                     blk_item, blk_item.pos(), blk_item.boundingRect())
        _debug("  blk_item scenePos=%s", blk_item.mapToScene(QPointF(0, 0)))
        _debug("  left_points=%s", _fmt_pts(blk_item._left_points))
        _debug("  right_points=%s", _fmt_pts(blk_item._right_points))

        super().setPos(QPointF(0, 0))
        _debug("  FlowShapeControl pos after reset=%s", super().pos())

        # Convert blk_item-local coordinates to parent (baseLayer) coordinates
        # using mapToItem which handles ALL parent transforms (scale, offset, rotation).
        # FlowShapeControl and blk_item are both children of baseLayer, so
        # mapToItem(parentItem(), pt) gives us the correct position for child items.
        parent_item = self.parentItem()

        all_points = blk_item._left_points + blk_item._right_points
        _debug("  total handle count=%d, total points=%d",
                     len(self.handles), len(all_points))
        for handle, pt in zip(self.handles, all_points):
            parent_pos = blk_item.mapToItem(parent_item, pt)
            _debug("    handle side=%s idx=%d: local=(%.1f,%.1f) -> parent=(%.1f,%.1f)",
                         handle.side, handle.point_idx,
                         pt.x(), pt.y(),
                         parent_pos.x(), parent_pos.y())
            handle.setPos(parent_pos)

        # Top handle: midpoint of top-left and top-right
        tl = blk_item.mapToItem(parent_item, blk_item._left_points[0])
        tr = blk_item.mapToItem(parent_item, blk_item._right_points[0])
        self.top_handle.setPos(QPointF(
            (tl.x() + tr.x()) / 2,
            (tl.y() + tr.y()) / 2,
        ))

        # Bottom handle: midpoint of bottom-left and bottom-right
        bl = blk_item.mapToItem(parent_item, blk_item._left_points[-1])
        br = blk_item.mapToItem(parent_item, blk_item._right_points[-1])
        self.bottom_handle.setPos(QPointF(
            (bl.x() + br.x()) / 2,
            (bl.y() + br.y()) / 2,
        ))

        # Left handle: midpoint of all left points, shifted left by offset
        left_pts_parent = [blk_item.mapToItem(parent_item, p) for p in blk_item._left_points]
        lx = sum(p.x() for p in left_pts_parent) / len(left_pts_parent) - DIAMOND_OFFSET / self.current_scale
        ly = sum(p.y() for p in left_pts_parent) / len(left_pts_parent)
        self.left_handle.setPos(QPointF(lx, ly))

        # Right handle: midpoint of all right points, shifted right by offset
        right_pts_parent = [blk_item.mapToItem(parent_item, p) for p in blk_item._right_points]
        rx = sum(p.x() for p in right_pts_parent) / len(right_pts_parent) + DIAMOND_OFFSET / self.current_scale
        ry = sum(p.y() for p in right_pts_parent) / len(right_pts_parent)
        self.right_handle.setPos(QPointF(rx, ry))

        # Rotation handle: above the top handle
        top_pos = self.top_handle.pos()
        offset = ROTATION_HANDLE_OFFSET / self.current_scale
        self.rotation_handle.setPos(QPointF(top_pos.x(), top_pos.y() - offset))

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
        for h in self._h_resize_handles:
            h.setSize(s)
        r = ROTATION_HANDLE_RADIUS / scale
        self.rotation_handle.setRadius(r)
        pen = self.rotation_handle.pen()
        pen.setWidthF(1.5 / scale)
        self.rotation_handle.setPen(pen)

    def startEditing(self):
        """Hide flow handles when entering text edit mode."""
        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)
        for h in self._h_resize_handles:
            h.setVisible(False)
        self.rotation_handle.setVisible(False)

    def endEditing(self):
        """Show flow handles again when exiting text edit mode."""
        visible = self._flow_handles_visible() and not self.blk_item.isEditing()
        has_points = self.blk_item is not None and \
                     hasattr(self.blk_item, '_left_points') and \
                     bool(self.blk_item._left_points)
        for h in self.handles:
            h.setVisible(visible)
        for h in self._resize_handles:
            h.setVisible(has_points)
        for h in self._h_resize_handles:
            h.setVisible(has_points)
        self.rotation_handle.setVisible(has_points)

    def hideControls(self):
        for h in self.handles:
            h.hide()
        for h in self._resize_handles:
            h.hide()
        for h in self._h_resize_handles:
            h.hide()
        self.rotation_handle.hide()

    def showControls(self):
        has_points = self.blk_item is not None and \
                     hasattr(self.blk_item, '_left_points') and \
                     bool(self.blk_item._left_points)
        for h in self.handles:
            h.setVisible(not self._is_vertical())
        for h in self._resize_handles:
            h.setVisible(has_points)
        for h in self._h_resize_handles:
            h.setVisible(has_points)
        self.rotation_handle.setVisible(has_points)

    def setAngle(self, angle: float):
        if self.blk_item is not None:
            center = self.blk_item.boundingRect().center()
            self.blk_item.setTransformOriginPoint(center)
            self.blk_item.setRotation(angle)
            self.blk_item.blk.angle = angle

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
            self.prepareGeometryChange()
            self._drag_rect = rect
            self.update()
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

        _debug("handleContextMenu called — scene_pos=(%.1f, %.1f)", scene_pos.x(), scene_pos.y())

        # First check if we clicked on a control handle or a FlowTextBlkItem
        # via scene lookup (handles are high z-order, blk items may be lower).
        if self.scene() is not None:
            items_at_pos = self.scene().items(scene_pos)
            _debug("  items at pos: %d", len(items_at_pos))
            for item in items_at_pos:
                _debug("    - %s (type=%s)", item, type(item).__name__)
                if isinstance(item, FlowControlHandle):
                    _debug("  -> FlowControlHandle found, showing it")
                    item.showHandleContextMenu(screen_pos)
                    return True
                if isinstance(item, FlowTextBlkItem):
                    _debug("  -> FlowTextBlkItem found via scene.items()")
                    item.showFlowContextMenu(scene_pos, screen_pos)
                    return True

        # Fallback: if blk_item is set and is a FlowTextBlkItem that was not
        # found via scene.items() (e.g. because it's below other items), use it.
        if isinstance(self.blk_item, FlowTextBlkItem):
            _debug("  -> Fallback: using self.blk_item (FlowTextBlkItem)")
            self.blk_item.showFlowContextMenu(scene_pos, screen_pos)
            return True

        _debug("  -> Returning False (no flow item handled)")
        return False

    def show(self):
        _debug("=== FlowShapeControl.show ===")
        _debug("  blk_item=%s", self.blk_item)
        if self.blk_item is not None:
            _debug("  blk_item pos=%s has _left_points=%s count=%d",
                         self.blk_item.pos(),
                         hasattr(self.blk_item, '_left_points'),
                         len(getattr(self.blk_item, '_left_points', [])))
        super().show()
        if self.need_rescale:
            self.updateScale(self.current_scale)
            self.need_rescale = False
        flow_visible = self._flow_handles_visible()
        has_points = self.blk_item is not None and \
                     hasattr(self.blk_item, '_left_points') and \
                     bool(self.blk_item._left_points)
        _debug("  flow_visible=%s, handle count=%d", flow_visible, len(self.handles))
        for h in self.handles:
            h.setVisible(flow_visible)
        for h in self._resize_handles:
            h.setVisible(has_points)
        for h in self._h_resize_handles:
            h.setVisible(has_points)
        self.rotation_handle.setVisible(has_points)
        if has_points:
            self.updateHandlePositions()
        self.setZValue(1)

    def hide(self):
        super().hide()
        for h in self.handles:
            h.setVisible(False)
        for h in self._resize_handles:
            h.setVisible(False)
        for h in self._h_resize_handles:
            h.setVisible(False)
        self.rotation_handle.setVisible(False)

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
        if self.blk_item is not None:
            self.blk_item.setRotation(angle)
            self.blk_item.blk.angle = angle

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