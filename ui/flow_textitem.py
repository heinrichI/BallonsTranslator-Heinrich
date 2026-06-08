"""
FlowTextBlkItem — drop-in replacement for TextBlkItem that supports
curved/trapezoidal text boundaries defined by DEFAULT_POINTS_PER_SIDE
control points per side.

The left and right boundary each have DEFAULT_POINTS_PER_SIDE QPointF
control points (evenly distributed by y) in item-local coordinates.
Per-line x-offsets are fed into
HorizontalTextDocumentLayout.set_line_x_offsets() so the text reflows
automatically when handles are dragged.

draw_boundaries flag:  set to False before render_result_img() to suppress
the visual boundary overlay in the exported image.
"""

import logging
from typing import List, Union, Tuple

logger = logging.getLogger('BallonTranslator')

from qtpy.QtWidgets import QGraphicsItem, QWidget, QGraphicsSceneHoverEvent, QGraphicsTextItem, QStyleOptionGraphicsItem, QStyle, QGraphicsSceneMouseEvent, QMenu, QAction
from qtpy.QtCore import Qt, QRectF, QPointF, Signal
from qtpy.QtGui import (QPainter, QPen, QColor, QPainterPath, QTextCursor)

from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from .textitem import TextBlkItem
from .scene_textlayout import HorizontalTextDocumentLayout


# ── Constants ────────────────────────────────────────────────

DEFAULT_POINTS_PER_SIDE: int = 3  # количество точек при инициализации из прямоугольника
MIN_POINTS_PER_SIDE: int = 3      # минимальное количество точек для кривой Безье и удаления


# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────

def interpolate_boundary(points: List[QPointF], y: float) -> float:
    """
    Linear interpolation between MIN_POINTS_PER_SIDE sorted-by-y control points.
    Returns x at height y.
    """
    if len(points) < 2:
        return points[0].x() if points else 0.0

    # Sort by y just to be safe
    pts = sorted(points, key=lambda p: p.y())

    # Clamp to the range of the control points
    if y <= pts[0].y():
        return pts[0].x()
    if y >= pts[-1].y():
        return pts[-1].x()

    # Find the segment
    for i in range(len(pts) - 1):
        y0, y1 = pts[i].y(), pts[i + 1].y()
        if y0 <= y <= y1:
            if abs(y1 - y0) < 1e-9:
                return pts[i].x()
            t = (y - y0) / (y1 - y0)
            return pts[i].x() + t * (pts[i + 1].x() - pts[i].x())

    return pts[-1].x()


def build_quad_path(points: List[QPointF]) -> QPainterPath:
    """
    Build a quadratic Bezier path that passes THROUGH all points.
    For >= MIN_POINTS_PER_SIDE points, the curve passes through pts[0],
    pts[1] (middle), and pts[-1]. To achieve this, we compute the true
    Bezier control point C such that B(0.5) = pts[1]:
        C = 2 * pts[1] - 0.5 * (pts[0] + pts[-1])
    """
    path = QPainterPath()
    if len(points) < 2:
        return path

    pts = sorted(points, key=lambda p: p.y())

    if len(pts) == 2:
        path.moveTo(pts[0])
        path.lineTo(pts[1])
    elif len(pts) >= MIN_POINTS_PER_SIDE:
        # Compute control point so curve passes through pts[1] at t=0.5
        ctrl = QPointF(
            2 * pts[1].x() - 0.5 * (pts[0].x() + pts[2].x()),
            2 * pts[1].y() - 0.5 * (pts[0].y() + pts[2].y()),
        )
        path.moveTo(pts[0])
        path.quadTo(ctrl, pts[2])
    return path


# ─────────────────────────────────────────────────────────────
# FlowTextBlkItem
# ─────────────────────────────────────────────────────────────

class FlowTextBlkItem(TextBlkItem):
    """
    Extends TextBlkItem with:
    - DEFAULT_POINTS_PER_SIDE left + right boundary control points (item-local coords)
    - Per-line x-offset layout via HorizontalTextDocumentLayout
    - Hover-only visual boundary overlay (suppressed when draw_boundaries=False)
    """

    def __init__(self, blk: TextBlock = None, idx: int = 0, set_format=True, show_rect=False, *args, **kwargs):
        self._left_points: List[QPointF] = []
        self._right_points: List[QPointF] = []
        self._hover: bool = False
        self.draw_boundaries: bool = True

        super().__init__(blk, idx, set_format, show_rect, *args, **kwargs)
        self.setAcceptHoverEvents(True)

        # Initialize flow points from the block if already set
        if blk is not None:
            if blk.left_points and blk.right_points:
                self._left_points = [QPointF(p[0], p[1]) for p in blk.left_points]
                self._right_points = [QPointF(p[0], p[1]) for p in blk.right_points]
            else:
                self._init_points_from_rect(self.absBoundingRect(qrect=True))

    # ── Control point initialisation ──────────────────────────

    def _init_points_from_rect(self, rect: QRectF):
        """Initialise DEFAULT_POINTS_PER_SIDE boundary points per side from a plain rectangle."""
        if rect is None or rect.width() < 1 or rect.height() < 1:
            return
        # Convert to item-local coordinates
        pos = self.pos()
        x0 = rect.x() - pos.x()
        x1 = rect.x() + rect.width() - pos.x()
        y0 = rect.y() - pos.y()
        y1 = rect.y() + rect.height() - pos.y()

        self._left_points = []
        self._right_points = []
        for i in range(DEFAULT_POINTS_PER_SIDE):
            t = i / (DEFAULT_POINTS_PER_SIDE - 1) if DEFAULT_POINTS_PER_SIDE > 1 else 0.0
            y = y0 + t * (y1 - y0)
            self._left_points.append(QPointF(x0, y))
            self._right_points.append(QPointF(x1, y))

    # ── Layout helpers ────────────────────────────────────────

    def _get_line_x_offsets(self) -> Tuple[dict, dict]:
        """
        Compute per-line left offsets and right boundaries to feed into the layout.
        Returns (left_offsets: dict, right_boundaries: dict)
        """
        if not self._left_points or not self._right_points:
            return {}, {}

        layout = self.layout
        if not isinstance(layout, HorizontalTextDocumentLayout):
            return {}, {}

        doc_margin = self.document().documentMargin()
        left_offsets = {}
        right_boundaries = {}

        # Walk all text lines and compute positions from boundaries
        block = self.document().firstBlock()
        line_idx = 0
        while block.isValid():
            tl = block.layout()
            for i in range(tl.lineCount()):
                line = tl.lineAt(i)
                if not line.isValid():
                    continue
                line_y = line.position().y()
                # Left boundary x at this y (item-local)
                left_x = interpolate_boundary(self._left_points, line_y)
                # Right boundary x at this y (item-local)
                right_x = interpolate_boundary(self._right_points, line_y)
                
                left_offsets[line_idx] = left_x - doc_margin
                right_boundaries[line_idx] = right_x
                line_idx += 1
            block = block.next()

        return left_offsets, right_boundaries

    def _update_flow_layout(self):
        """Push current boundary offsets to the layout engine and repaint."""
        import logging as _logging
        _log = _logging.getLogger('BallonTranslator')
        _log.debug('_update_flow_layout: item_pos=(%.1f,%.1f) left=%s right=%s',
            self.pos().x(), self.pos().y(),
            [(round(p.x(),1), round(p.y(),1)) for p in self._left_points],
            [(round(p.x(),1), round(p.y(),1)) for p in self._right_points])
        if isinstance(self.layout, HorizontalTextDocumentLayout):
            left_offsets, right_boundaries = self._get_line_x_offsets()
            self.layout.set_line_x_offsets(left_offsets, right_boundaries)
        self.repaint_background()
        self.update()

    # ── Serialisation ─────────────────────────────────────────

    def save_flow_points(self):
        """Write _left_points / _right_points back to the blk data model."""
        if self.blk is None:
            return
        self.blk.left_points = [[p.x(), p.y()] for p in self._left_points]
        self.blk.right_points = [[p.x(), p.y()] for p in self._right_points]

    # ── Override size/pos methods to prevent pos() shift ─────

    def set_size(self, w: float, h: float, set_layout_maxsize=False, set_blk_size=True):
        """For flow items: update layout max size but never shift pos()."""
        if set_layout_maxsize and hasattr(self, 'layout') and self.layout is not None:
            try:
                self.layout.setMaxSize(w, h)
            except Exception:
                pass
        self.setCenterTransform()
        self.prepareGeometryChange()
        if set_blk_size and self.blk is not None:
            self.blk._bounding_rect = self.absBoundingRect()
        self.update()

    def on_document_enlarged(self):
        # For flow items: do NOT shift pos() to preserve control point positions.
        self.setCenterTransform()
        self.prepareGeometryChange()
        self.update()

    def docSizeChanged(self):
        # For flow items: just update transform, never shift pos().
        self.setCenterTransform()
        self.update()

    # ── BoundingRect override ─────────────────────────────────

    def boundingRect(self) -> QRectF:
        rect = super().boundingRect()
        all_pts = self._left_points + self._right_points
        if all_pts:
            xs = [p.x() for p in all_pts]
            ys = [p.y() for p in all_pts]
            pts_rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            rect = rect.united(pts_rect)
        return rect

    # ── Hover events ──────────────────────────────────────────

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    # ── Context menu helpers ──────────────────────────────────

    def add_point_left(self, click_y: float):
        """Add a control point on the left boundary at the given local Y."""
        if not self._left_points:
            return
        x = interpolate_boundary(self._left_points, click_y)
        new_pt = QPointF(x, click_y)
        self._left_points.append(new_pt)
        self._left_points.sort(key=lambda p: p.y())
        self._after_add_point()

    def add_point_right(self, click_y: float):
        """Add a control point on the right boundary at the given local Y."""
        if not self._right_points:
            return
        x = interpolate_boundary(self._right_points, click_y)
        new_pt = QPointF(x, click_y)
        self._right_points.append(new_pt)
        self._right_points.sort(key=lambda p: p.y())
        self._after_add_point()

    def _after_add_point(self):
        """Refresh layout and rebuild shape handles after adding a point."""
        self._update_flow_layout()
        scene = self.scene()
        if scene is not None:
            for item in scene.items():
                from .flow_shapecontrol import FlowShapeControl
                if isinstance(item, FlowShapeControl) and item.blk_item is self:
                    item.rebuildHandles()
                    break

    def injectFlowMenuItems(self, menu: QMenu, scene_pos: QPointF):
        """
        Insert flow-specific actions at the top of an existing QMenu.
        Called by FlowShapeControl.handleContextMenu() to build the
        combined context menu.
        """
        if not self._left_points or not self._right_points:
            return

        local_pos = self.mapFromScene(scene_pos)
        click_y = local_pos.y()

        # Build the two flow actions with lambda closures for click_y
        add_left = QAction("Добавить точку к левой стороне", menu)
        add_right = QAction("Добавить точку к правой стороне", menu)
        add_left.triggered.connect(lambda checked, y=click_y: self.add_point_left(y))
        add_right.triggered.connect(lambda checked, y=click_y: self.add_point_right(y))

        # Insert at top: we want [add_left, add_right, sep, original_actions...]
        # insertAction(before, action) inserts action BEFORE before.
        # So we add in reverse order.
        first_action = menu.actions()[0] if menu.actions() else None

        # Step 1: insert separator before first_action
        sep = QAction(menu)
        sep.setSeparator(True)
        if first_action is not None:
            menu.insertAction(first_action, sep)
            # Step 2: insert add_right before sep
            menu.insertAction(sep, add_right)
            # Step 3: insert add_left before add_right
            menu.insertAction(add_right, add_left)
        else:
            # Menu is empty — just add actions
            menu.addAction(add_left)
            menu.addAction(add_right)
            menu.addSeparator()

    def showFlowContextMenu(self, scene_pos: QPointF, screen_pos):
        """
        Legacy entry point for the combined context menu.
        Builds the standard canvas menu, injects flow items, and shows it.
        """
        logger.debug("showFlowContextMenu called — scene_pos=(%.1f, %.1f)", scene_pos.x(), scene_pos.y())
        scene = self.scene()
        if scene is not None and hasattr(scene, 'build_context_menu') and hasattr(scene, 'exec_context_menu'):
            std_menu, actions = scene.build_context_menu()
            logger.debug("  std_menu built, actions=%d. Now injecting flow items.", len(actions) if actions else 0)
            self.injectFlowMenuItems(std_menu, scene_pos)
            screen_pt = screen_pos.toPoint() if hasattr(screen_pos, 'toPoint') else screen_pos
            scene.exec_context_menu(std_menu, actions, screen_pt)
            logger.debug("  Context menu executed.")
        else:
            logger.debug("  scene=%s, has build_context_menu=%s, has exec_context_menu=%s",
                         scene,
                         hasattr(scene, 'build_context_menu') if scene else False,
                         hasattr(scene, 'exec_context_menu') if scene else False)

    # ── Paint ─────────────────────────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget) -> None:
        # Draw text via parent
        super().paint(painter, option, widget)

        # Draw boundary overlay only when hovered/under control and draw_boundaries is True
        if self.draw_boundaries and (self._hover or self.under_ctrl) and \
                self._left_points and self._right_points:
            painter.save()
            scale = self.get_scale()
            pen = QPen(QColor(30, 147, 229, 200), 1.5 / scale, Qt.PenStyle.SolidLine)
            painter.setPen(pen)

            # Draw left boundary curve
            left_path = build_quad_path(self._left_points)
            painter.drawPath(left_path)

            # Draw right boundary curve
            right_path = build_quad_path(self._right_points)
            painter.drawPath(right_path)

            # Draw top and bottom connector lines
            left_sorted = sorted(self._left_points, key=lambda p: p.y())
            right_sorted = sorted(self._right_points, key=lambda p: p.y())
            painter.drawLine(left_sorted[0], right_sorted[0])
            painter.drawLine(left_sorted[-1], right_sorted[-1])

            painter.restore()