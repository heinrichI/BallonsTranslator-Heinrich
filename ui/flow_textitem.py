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
import re
from typing import List, Union, Tuple

logger = logging.getLogger('BallonTranslator')

from qtpy.QtWidgets import QGraphicsItem, QWidget, QGraphicsSceneHoverEvent, QGraphicsTextItem, QStyleOptionGraphicsItem, QStyle, QGraphicsSceneMouseEvent, QMenu, QAction
from qtpy.QtCore import Qt, QRectF, QPointF, Signal
from qtpy.QtGui import (QPainter, QPen, QColor, QPainterPath, QTextCursor)

from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from .textitem import TextBlkItem
from .scene_textlayout import HorizontalTextDocumentLayout
from .textitem import TEXTRECT_SHOW_COLOR, TEXTRECT_SELECTED_COLOR
import pyphen


# ── Constants ────────────────────────────────────────────────

DEFAULT_POINTS_PER_SIDE: int = 3  # количество точек при инициализации из прямоугольника
MIN_POINTS_PER_SIDE: int = 3      # минимальное количество точек для кривой Безье и удаления
MIN_FONT_SIZE_PT: float = 5.0     # минимальный размер шрифта для auto-shrink
FONT_SHRINK_FACTOR: float = 0.9   # мультипликативный коэффициент за итерацию auto-shrink


# ── Hyphenation ──────────────────────────────────────────────

_LATIN_RE = re.compile(r'[a-zA-Zà-ÿÀ-ß]+', re.UNICODE)
_CYRILLIC_RE = re.compile(r'[а-яёА-ЯЁ]+', re.UNICODE)
_PYPHEN_CACHE: dict = {}  # lang -> Pyphen instance cache
_LANG_MAP = {
    'LATIN': 'en_US',      # default Latin → English hyphenation
    'CYRILLIC': 'ru_RU',  # default Cyrillic → Russian hyphenation
}


def _get_pyphen(lang: str = 'en_US'):
    """Get a cached Pyphen instance for the given language."""
    if lang not in _PYPHEN_CACHE:
        _PYPHEN_CACHE[lang] = pyphen.Pyphen(lang=lang)
    return _PYPHEN_CACHE[lang]


def _hyphenate_text(text: str, min_word_len: int = 5) -> str:
    """
    Insert soft hyphens (U+00AD) between syllables of long words.
    Supports both Cyrillic (ru_RU) and Latin (en_US) text.
    Non-alphabetic text and words shorter than min_word_len are left unchanged.

    Soft hyphens are zero-width and invisible in the editor; Qt's line breaker
    treats them as valid break points when a word overflows the line width.

    Args:
        text: Input text (may contain mixed languages).
        min_word_len: Minimum word length (in characters) to hyphenate.
                      Shorter words are left as-is.

    Returns:
        Text with soft hyphens inserted at syllable boundaries.
    """
    if not text:
        return text

    def _hyphenate_word(match, hyphenator):
        word = match.group(0)
        if len(word) < min_word_len:
            return word
        return hyphenator.inserted(word, hyphen='\u00AD')

    # Hyphenate Cyrillic words with ru_RU
    ru_hyphenator = _get_pyphen('ru_RU')
    text = _CYRILLIC_RE.sub(lambda m: _hyphenate_word(m, ru_hyphenator), text)

    # Hyphenate Latin words with en_US
    en_hyphenator = _get_pyphen('en_US')
    text = _LATIN_RE.sub(lambda m: _hyphenate_word(m, en_hyphenator), text)

    return text


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
        self._updating_flow: bool = False  # guard flag to prevent _display_rect changes during flow updates
        self._auto_grow_enabled: bool = True  # set to False when global font size is used

        super().__init__(blk, idx, set_format, show_rect, *args, **kwargs)
        self.setAcceptHoverEvents(True)

        logging.debug("=== FlowTextBlkItem.__init__ ===")
        logging.debug("  idx=%d pos=%s", idx, self.pos())
        logging.debug("  blk=%s", blk)

        # Initialize flow points from the block if already set
        if blk is not None:
            logging.debug("  blk has left_points=%s right_points=%s",
                          bool(blk.left_points), bool(blk.right_points))
            if blk.left_points and blk.right_points:
                self._left_points = [QPointF(p[0], p[1]) for p in blk.left_points]
                self._right_points = [QPointF(p[0], p[1]) for p in blk.right_points]
                logging.debug("  restored from blk: left=%s right=%s",
                              [(p.x(), p.y()) for p in self._left_points],
                              [(p.x(), p.y()) for p in self._right_points])
            else:
                # Use _display_rect (properly sized by setRect) to avoid
                # absBoundingRect returning near-zero during early init.
                dr = self._display_rect
                pos = self.pos()
                abr = QRectF(pos.x(), pos.y(), dr.width(), dr.height())
                logging.debug("  calling _init_points_from_rect with displayRect-based=%s", abr)
                self._init_points_from_rect(abr)
        logging.debug("  after init: left=%s right=%s",
                      [(p.x(), p.y()) for p in self._left_points],
                      [(p.x(), p.y()) for p in self._right_points])

    # ── Text change overrides ────────────────────────────────

    def setPlainText(self, text: str = ''):
        """Override to ensure flow layout boundaries are applied after text changes.
        Also hyphenates text via pyphen (Cyrillic → ru_RU, Latin → en_US) to enable
        syllable-level line breaking.  Does NOT call _auto_shrink_font here — that
        is deferred to set_size() where layout dimensions are known and
        layout_textblk binary search works."""
        # Apply hyphenation before passing text to the layout engine.
        # Soft hyphens are zero-width and invisible; Qt wraps at them naturally.
        text = _hyphenate_text(text)
        super().setPlainText(text)
        if self._left_points and self._right_points:
            # Only reapply boundary functions (no auto-shrink since layout size unknown yet).
            if isinstance(self.layout, HorizontalTextDocumentLayout):
                lp = self._left_points[:]
                rp = self._right_points[:]
                self.layout.set_boundary_functions(
                    left_fn=lambda y, _lp=lp: interpolate_boundary(_lp, y),
                    right_fn=lambda y, _rp=rp: interpolate_boundary(_rp, y),
                )
                self.repaint_background()
                self.update()

    def setHtml(self, text: str = ''):
        """Override setHtml to also apply hyphenation (used for rich text loading
        and undo/redo restoration)."""
        text = _hyphenate_text(text)
        super().setHtml(text)
        if self._left_points and self._right_points:
            if isinstance(self.layout, HorizontalTextDocumentLayout):
                lp = self._left_points[:]
                rp = self._right_points[:]
                self.layout.set_boundary_functions(
                    left_fn=lambda y, _lp=lp: interpolate_boundary(_lp, y),
                    right_fn=lambda y, _rp=rp: interpolate_boundary(_rp, y),
                )
                self.repaint_background()
                self.update()

    def setPlainTextAndKeepUndoStack(self, text: str):
        """Override from TextBlkItem to apply hyphenation for undo-safe text setting."""
        text = _hyphenate_text(text)
        super().setPlainTextAndKeepUndoStack(text)
        if self._left_points and self._right_points:
            if isinstance(self.layout, HorizontalTextDocumentLayout):
                lp = self._left_points[:]
                rp = self._right_points[:]
                self.layout.set_boundary_functions(
                    left_fn=lambda y, _lp=lp: interpolate_boundary(_lp, y),
                    right_fn=lambda y, _rp=rp: interpolate_boundary(_rp, y),
                )
                self.repaint_background()
                self.update()

    # ── Control point initialisation ──────────────────────────

    def _init_points_from_rect(self, rect: QRectF):
        """Initialise DEFAULT_POINTS_PER_SIDE boundary points per side from a plain rectangle.
        rect is in scene coordinates (includes pos offset).  Skips if rect is too small
        (degenerate or not yet fully initialised)."""
        logging.debug("=== _init_points_from_rect ===")
        logging.debug("  rect=%s (x=%.1f y=%.1f w=%.1f h=%.1f)",
                      rect, rect.x() if rect else 0, rect.y() if rect else 0,
                      rect.width() if rect else 0, rect.height() if rect else 0)
        if rect is None or rect.width() < 10 or rect.height() < 10:
            logging.debug("  rect too small, returning")
            return
        pos = self.pos()
        logging.debug("  self.pos()=%s", pos)
        # Convert to item-local coordinates
        x0 = rect.x() - pos.x()
        x1 = rect.x() + rect.width() - pos.x()
        y0 = rect.y() - pos.y()
        y1 = rect.y() + rect.height() - pos.y()
        logging.debug("  local: x0=%.1f x1=%.1f y0=%.1f y1=%.1f", x0, x1, y0, y1)

        self._left_points = []
        self._right_points = []
        for i in range(DEFAULT_POINTS_PER_SIDE):
            t = i / (DEFAULT_POINTS_PER_SIDE - 1) if DEFAULT_POINTS_PER_SIDE > 1 else 0.0
            y = y0 + t * (y1 - y0)
            self._left_points.append(QPointF(x0, y))
            self._right_points.append(QPointF(x1, y))
        logging.debug("  final left=%s right=%s",
                      [(p.x(), p.y()) for p in self._left_points],
                      [(p.x(), p.y()) for p in self._right_points])

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

    def _auto_shrink_font(self) -> bool:
        """
        Iteratively reduce font size until text fits in available space
        or reaches MIN_FONT_SIZE_PT.  Returns True if shrink was applied.
        Only works for HorizontalTextDocumentLayout — vertical layout
        uses different height metrics that this algorithm doesn't handle.

        Uses the control-points y-range as the target height, NOT
        layout.available_height, because the layout may have already
        expanded its max height to accommodate overflowing text.

        CRITICAL: Before each shrink iteration, we reset layout.available_height
        and layout.max_height back to target values. This is necessary because
        reLayout() in SceneTextLayout expands available_height when text overflows
        (line: self.available_height = new_height). Without resetting, subsequent
        shrink iterations would use the expanded height as the constraint, making
        shrink_height always appear to fit and the loop would exit after one
        iteration without actually achieving the target.
        """
        layout = self.layout
        if layout is None:
            return False
        # Only shrink in horizontal mode — vertical layout has different metrics
        if not isinstance(layout, HorizontalTextDocumentLayout):
            return False

        min_font = layout.max_font_size()
        if min_font <= MIN_FONT_SIZE_PT:
            return False

        # Compute target height from control points (not from layout.available_height
        # which may have grown after the layout expanded to fit overflowing text).
        if self._left_points and self._right_points:
            all_ys = [p.y() for p in self._left_points] + [p.y() for p in self._right_points]
            target_height = max(all_ys) - min(all_ys)
        else:
            target_height = layout.available_height
        if target_height < 10:
            return False

        text_extent = layout.shrink_height

        # Check conditions for shrinking:
        # 1. Height overflow (text_extent > target_height) — standard shrink
        # 2. Overflow + forced char breaks (layout._has_overflow_char_break) —
        #    Only shrink when there are character-level breaks AND the text
        #    overflows vertically. If text fits but has char breaks (narrow
        #    block), let it wrap to more lines — font size is fine.
        if text_extent <= target_height:
            return False

        # If text overflows AND has character-level breaks, always shrink.
        # If text overflows WITHOUT char breaks (just height overflow), also shrink.
        applied = False
        doc_margin = self.document().documentMargin()
        for _ in range(20):
            if applied:
                layout.available_height = target_height
                layout.max_height = target_height + doc_margin * 2
                layout.reLayout()
            else:
                pass  # first iteration, no reset needed

            text_extent = layout.shrink_height

            # Stop shrinking when text fits vertically
            if text_extent <= target_height:
                break

            # compute shrink factor: 5% safety margin, cap at 0.9
            factor = min(FONT_SHRINK_FACTOR, (target_height / text_extent) * 0.95) if text_extent > 0 else FONT_SHRINK_FACTOR
            if factor >= 1.0:
                break

            self.setRelFontSize(factor)
            applied = True

            # check min size after shrink
            new_min = layout.max_font_size()
            if new_min <= MIN_FONT_SIZE_PT:
                break

        if applied:
            # Sync fontformat.size so the font-size panel reflects the new size.
            # Read the actual size from the first text fragment in the document.
            try:
                block = self.document().firstBlock()
                it = block.begin()
                if not it.atEnd():
                    actual_size = it.fragment().charFormat().fontPointSize()
                    if actual_size > 0:
                        if self.fontformat is not None:
                            self.fontformat.size = actual_size
                        if self.blk is not None and self.blk.fontformat is not None:
                            self.blk.fontformat.size = actual_size
            except Exception:
                pass

        return applied

    def _auto_grow_font(self) -> bool:
        """
        Iteratively increase font size until text fills the available space
        or reaches a reasonable maximum.  Inverse of _auto_shrink_font.

        If shrink_height is significantly less than target_height (text is
        too small for the box), increase font size until text fills ~90%
        of the available height.

        Called AFTER _auto_shrink_font() in _update_flow_layout() so that
        overflow is handled first, then growth is applied if there's room.
        """
        layout = self.layout
        if layout is None:
            return False
        if not isinstance(layout, HorizontalTextDocumentLayout):
            return False

        # Target height from control points
        if self._left_points and self._right_points:
            all_ys = [p.y() for p in self._left_points] + [p.y() for p in self._right_points]
            target_height = max(all_ys) - min(all_ys)
        else:
            target_height = layout.available_height
        if target_height < 10:
            return False

        text_extent = layout.shrink_height
        # Only grow if text fills less than 70% of available height
        if text_extent >= target_height * 0.70:
            return False

        applied = False
        doc_margin = self.document().documentMargin()
        for _ in range(20):
            # Reset constraints before each iteration (same as shrink)
            layout.available_height = target_height
            layout.max_height = target_height + doc_margin * 2
            layout.reLayout()

            text_extent = layout.shrink_height
            # Stop when text fills >= 90% of target
            if text_extent >= target_height * 0.90:
                break

            # Compute grow factor: aim for 90% fill, cap at 1.08 per iteration
            factor = min(1.08, (target_height * 0.90) / max(text_extent, 1))

            self.setRelFontSize(factor)
            applied = True

        if applied:
            # Sync fontformat.size so the font-size panel reflects the new size.
            try:
                block = self.document().firstBlock()
                it = block.begin()
                if not it.atEnd():
                    actual_size = it.fragment().charFormat().fontPointSize()
                    if actual_size > 0:
                        if self.fontformat is not None:
                            self.fontformat.size = actual_size
                        if self.blk is not None and self.blk.fontformat is not None:
                            self.blk.fontformat.size = actual_size
            except Exception:
                pass

        return applied

    def _update_flow_layout(self):
        """Push current boundary functions to the layout engine and repaint."""
        from .scene_textlayout import VerticalTextDocumentLayout

        # Guard: prevent _display_rect changes from docSizeChanged during flow updates
        was_updating = self._updating_flow
        self._updating_flow = True
        try:
            if isinstance(self.layout, HorizontalTextDocumentLayout):
                # Compute the y-range of control points and update layout geometry
                # so text actually moves when top/bottom resize handles are dragged.
                if self._left_points and self._right_points:
                    all_ys = [p.y() for p in self._left_points] + [p.y() for p in self._right_points]
                    min_y = min(all_ys)
                    max_y = max(all_ys)
                    target_height = max_y - min_y

                    # Compute target width from control points x-range.
                    all_xs = [p.x() for p in self._left_points] + [p.x() for p in self._right_points]
                    min_x = min(all_xs)
                    max_x = max(all_xs)
                    target_width = max_x - min_x

                    # Set documentMargin = min_y so text STARTS at the new top edge.
                    # This is the ONLY way to make text move vertically with the handles.
                    self.document().setDocumentMargin(min_y)

                    # Compensate max_width so available_width stays correct:
                    # available_width = max_width - 2*doc_margin => max_width = target_width + 2*min_y
                    # available_height = max_height - 2*doc_margin => max_height = target_height + 2*min_y
                    self.layout.setMaxSize(target_width + 2 * min_y, target_height + 2 * min_y)
                else:
                    self._updating_flow = was_updating
                    return

                # Use callable y->x boundary functions instead of per-line-index dicts.
                # This avoids the line-index mismatch bug: layoutBlock resets line_idx
                # per block, but the old dict-based approach used a global counter.
                # With functions, layoutBlock looks up the boundary at the ACTUAL
                # y-position of each line as it is being laid out — so wrapping
                # (which changes line count) is handled correctly in one pass.
                # NO y_offset needed — since doc_margin = min_y, layout y starts at min_y,
                # which is exactly where control points start.
                lp = self._left_points[:]   # snapshot to avoid closure over mutable list
                rp = self._right_points[:]
                self.layout.set_boundary_functions(
                    left_fn=lambda y, _lp=lp: interpolate_boundary(_lp, y),
                    right_fn=lambda y, _rp=rp: interpolate_boundary(_rp, y),
                )
                # set_boundary_functions calls reLayout() internally — no second pass needed.
                # First shrink if text overflows, then grow if there's room.
                font_changed = self._auto_shrink_font()
                if self._auto_grow_enabled:
                    font_changed = self._auto_grow_font() or font_changed
                if font_changed:
                    # Notify the text panel so it refreshes the font-size display.
                    try:
                        self.reshaped.emit(self)
                    except Exception:
                        pass

            elif isinstance(self.layout, VerticalTextDocumentLayout):
                # Vertical mode with INDEPENDENT left and top margins.
                # In VerticalTextDocumentLayout.layoutBlock():
                #   - Text starts at y = docMargin (top), flows downward
                #   - Text starts at x = max_width - docMargin (right), flows leftward
                #   - Text wraps leftward until x reaches _vertical_left_margin (left boundary)
                #
                # We use:
                #   docMargin = min_y          → controls TOP edge of text
                #   max_width = max_x + min_y  → so text_right = max_width - docMargin = max_x (RIGHT fixed!)
                #   max_height = max_y + min_y → so available_height = max_y - min_y
                #   vertical_left_margin = min_x + min_y → controls LEFT edge independently
                #
                # Result:
                #   - Top handle (min_y) → changes text_top + available_height ✓
                #   - Bottom handle (max_y) → changes available_height ✓
                #   - Right handle (max_x) → changes text_right ✓
                #   - Left handle (min_x) → changes available_width (wrapping) but NOT text_right ✓
                if self._left_points and self._right_points:
                    all_xs = [p.x() for p in self._left_points] + [p.x() for p in self._right_points]
                    all_ys = [p.y() for p in self._left_points] + [p.y() for p in self._right_points]
                    min_x, max_x = min(all_xs), max(all_xs)
                    min_y, max_y = min(all_ys), max(all_ys)
                    effective_w = max_x - min_x
                    effective_h = max_y - min_y

                    if effective_w > 10 and effective_h > 10:
                        self.document().setDocumentMargin(min_y)
                        # max_width - docMargin = max_x => max_width = max_x + min_y
                        # available_height = max_y - min_y => max_height = max_y + min_y
                        self.layout.setMaxSize(max_x + min_y, max_y + min_y)
                        # Left boundary: vertical_left_margin = min_x + min_y
                        # Effective text width = (max_x + min_y - min_y) - (min_x + min_y) = max_x - min_x - min_y
                        # But we want effective text width = max_x - min_x
                        # So we need: max_width - docMargin - vertical_left_margin = max_x - min_x
                        # => max_x + min_y - min_y - vertical_left_margin = max_x - min_x
                        # => vertical_left_margin = min_x
                        self.layout.set_vertical_left_margin(min_x)
                        # Fix available_width to account for independent left margin
                        self.layout.available_width = effective_w
                        self.layout.reLayout()

            self.repaint_background()
            self.update()
        finally:
            self._updating_flow = was_updating

    # ── Vertical mode override ────────────────────────────────

    def setVertical(self, vertical: bool):
        """
        Override TextBlkItem.setVertical() to reset flow control points
        to a rectangle when switching between vertical/horizontal modes.

        In vertical mode, flow boundaries are not supported — the text
        renders in a plain rectangular box.  When switching back to
        horizontal, flow points are re-initialized from the current rect.
        """
        # 1. Switch layout engine first (Vertical/HorizontalTextDocumentLayout)
        super().setVertical(vertical)
        # 2. Save the current bounding rect AFTER layout switch.
        #    Use _display_rect + pos() instead of absBoundingRect() because
        #    absBoundingRect() relies on boundingRect() which can return near-zero
        #    during early init (before text is laid out).
        dr = self._display_rect
        p = self.pos()
        if dr is not None and dr.isValid() and dr.width() > 0 and dr.height() > 0:
            rect = QRectF(p.x(), p.y(), dr.width(), dr.height())
            self._init_points_from_rect(rect)
        # 3. Update layout for both modes — vertical mode now also needs layout sync
        self._update_flow_layout()
        self.save_flow_points()

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
        # After layout size is set, reapply flow boundaries + auto-shrink font.
        # This is where _auto_shrink_font gets correct layout dimensions.
        if self._left_points and self._right_points:
            self._update_flow_layout()
        self.update()

    def on_document_enlarged(self):
        # For flow items: do NOT shift pos() to preserve control point positions.
        # Guard: skip prepareGeometryChange() during flow updates to prevent
        # the red dashed border from resizing when dragging the top resize handle.
        if self._updating_flow:
            return
        self.setCenterTransform()
        self.prepareGeometryChange()
        self.update()

    def docSizeChanged(self):
        # For flow items: guard against _display_rect changes during flow updates.
        if self._updating_flow:
            return
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

    def _draw_accessories(self, painter: QPainter):
        """Override to suppress the red dashed border when flow handles are visible
        (under_ctrl). The flow boundary curves already indicate the text area,
        and the dashed _display_rect border would expand when the top resize
        handle moves control points above _display_rect.

        Still draws background_pixmap (text stroke/shadow) even when under_ctrl."""
        br = self.boundingRect()
        painter.save()

        if self.background_pixmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(br.toRect(), self.background_pixmap)

        # Only draw the dashed border when NOT under control (flow handles visible)
        if not self.under_ctrl:
            draw_rect = self.draw_rect and not self.under_ctrl
            if self.isSelected() and not self.is_editting():
                pen = QPen(TEXTRECT_SELECTED_COLOR, 3.5 / self.get_scale(), Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(self.unpadRect(br))
            elif draw_rect:
                pen = QPen(TEXTRECT_SHOW_COLOR, 3 / self.get_scale(), Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawRect(self.unpadRect(br))
        painter.restore()

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