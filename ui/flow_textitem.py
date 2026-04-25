"""
FlowTextBlkItem — drop-in replacement for TextBlkItem that supports
curved/trapezoidal text boundaries defined by 3 control points per side.

The left and right boundary each have 3 QPointF control points (top, middle,
bottom) in item-local coordinates.  Per-line x-offsets are fed into
HorizontalTextDocumentLayout.set_line_x_offsets() so the text reflows
automatically when handles are dragged.

draw_boundaries flag:  set to False before render_result_img() to suppress
the visual boundary overlay in the exported image.
"""

from typing import List, Union, Tuple

from qtpy.QtWidgets import QGraphicsItem, QWidget, QGraphicsSceneHoverEvent, QGraphicsTextItem, QStyleOptionGraphicsItem, QStyle, QGraphicsSceneMouseEvent
from qtpy.QtCore import Qt, QRectF, QPointF, Signal
from qtpy.QtGui import (QPainter, QPen, QColor, QPainterPath, QTextCursor)

from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from .textitem import TextBlkItem
from .scene_textlayout import HorizontalTextDocumentLayout


# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────

def interpolate_boundary(points: List[QPointF], y: float) -> float:
    """
    Linear interpolation between 3 sorted-by-y control points.
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
    Build a quadratic Bezier path through 3 control points for visual display.
    """
    path = QPainterPath()
    if len(points) < 2:
        return path

    pts = sorted(points, key=lambda p: p.y())

    if len(pts) == 2:
        path.moveTo(pts[0])
        path.lineTo(pts[1])
    elif len(pts) >= 3:
        # Use middle point as control point for quadratic Bezier
        # midpoint of start-end as actual point, middle as control
        mid_x = (pts[0].x() + pts[2].x()) / 2
        mid_y = (pts[0].y() + pts[2].y()) / 2
        # Use the actual middle control point from the list
        ctrl = pts[1]
        path.moveTo(pts[0])
        path.quadTo(ctrl, pts[2])
    return path


# ─────────────────────────────────────────────────────────────
# FlowTextBlkItem
# ─────────────────────────────────────────────────────────────

class FlowTextBlkItem(TextBlkItem):
    """
    Extends TextBlkItem with:
    - 3 left + 3 right boundary control points (item-local coords)
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
        """Initialise 3+3 boundary points from a plain rectangle."""
        if rect is None or rect.width() < 1 or rect.height() < 1:
            return
        # Convert to item-local coordinates
        pos = self.pos()
        x0 = rect.x() - pos.x()
        x1 = rect.x() + rect.width() - pos.x()
        y0 = rect.y() - pos.y()
        y1 = rect.y() + rect.height() - pos.y()
        ym = (y0 + y1) / 2

        self._left_points = [
            QPointF(x0, y0),
            QPointF(x0, ym),
            QPointF(x0, y1),
        ]
        self._right_points = [
            QPointF(x1, y0),
            QPointF(x1, ym),
            QPointF(x1, y1),
        ]

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

    # ── Hover events ──────────────────────────────────────────

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

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