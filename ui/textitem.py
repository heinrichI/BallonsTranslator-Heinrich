import math, re
import inspect
import logging
import numpy as np
from typing import List, Optional, Union, Tuple

from qtpy.QtWidgets import QGraphicsItem, QWidget, QGraphicsSceneHoverEvent, QGraphicsTextItem, QStyleOptionGraphicsItem, QStyle, QGraphicsSceneMouseEvent, QMenu, QAction
from qtpy.QtCore import Qt, QRect, QRectF, QPointF, Signal, QSizeF
from qtpy.QtGui import (QGradient, QKeyEvent, QFont, QTextCursor, QPixmap, QPainterPath, QTextDocument,
                       QInputMethodEvent, QPainter, QPen, QColor, QTextCharFormat, QTextDocument, QLinearGradient,
                       QBrush, QPalette, QAbstractTextDocumentLayout)

from utils.textblock import TextBlock, FontFormat, TextAlignment, LineSpacingType
from utils.imgproc_utils import xywh2xyxypoly, rotate_polygons
from utils.fontformat import FontFormat, px2pt, pt2px
from utils.shared import LOG_PREFIXES as _LOG_PREFIXES
from .misc import td_pattern, table_pattern
from .scene_textlayout import VerticalTextDocumentLayout, HorizontalTextDocumentLayout, SceneTextLayout
from .text_graphical_effect import apply_shadow_effect
from .text_format_manager import TextFormatManager
from .font_size_manager import FontSizeManager
from .font_auto_adjuster import FontAutoAdjuster
from utils.config import pcfg

LOGGER = logging.getLogger('BallonTranslator')

QUIET_UI = True  # Set to False for verbose UI debug logging  (DEBUG ON: flow-drag investigation)

def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)

DEBUG_FONTSIZE = False  # Set to True for font size debug logging

_LOG_TARGET = "BUT OF COURSE!"

def _is_log_target(blk):
    if not DEBUG_FONTSIZE:
        return False
    if blk is None:
        return False
    try:
        text = blk.get_text() if hasattr(blk, 'get_text') else ''
        return text.startswith(_LOG_TARGET)
    except Exception:
        return False

TEXTRECT_SHOW_COLOR = QColor(30, 147, 229, 170)
TEXTRECT_SELECTED_COLOR = QColor(248, 64, 147, 170)


class TextBlkItem(QGraphicsTextItem):

    begin_edit = Signal(int)
    end_edit = Signal(int)
    hover_enter = Signal(int)
    hover_move = Signal(int)
    moved = Signal()
    moving = Signal(QGraphicsTextItem)
    rotated = Signal(float)
    reshaped = Signal(QGraphicsTextItem)
    leftbutton_pressed = Signal(int)
    doc_size_changed = Signal(int)
    pasted = Signal(int)
    redo_signal = Signal()
    undo_signal = Signal()
    push_undo_stack = Signal(int, bool)
    propagate_user_edited = Signal(int, str, bool)
    toggle_flow_mode_requested = Signal(int)

    def __init__(self, blk: TextBlock = None, idx: int = 0, set_format=True, show_rect=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pre_editing = False
        self.blk: TextBlock = None
        self.fontformat: FontFormat = None
        self._user_font_size: float = None  # User's chosen font size (preserved across auto-layout)
        self.format_manager: TextFormatManager = None  # Will be initialized in initTextBlock
        self.repainting = False
        self.reshaping = False
        self.under_ctrl = False
        self.draw_rect = show_rect
        self._display_rect: QRectF = QRectF(0, 0, 1, 1)
        self.old_ffmt_values = None
        self._last_selection = None  # (clean_text, start, end) — canvas selection that survives endEdit
        # (clean_text, start, end) — canvas cursor position at endEdit time
        # (start == end for a bare cursor). Display-only: the panel font-size
        # box follows the last canvas cursor after editing ends. Must NOT be
        # used by per-selection format ops (use _last_selection there).
        self._last_cursor_state: Optional[Tuple[str, int, int]] = None
        # Clean-text snapshot that blk.outline_ranges was last set against
        # (written by set_selection_outline). None means "no snapshot": the
        # initial load in __init__ and any project reload accept the
        # persisted ranges — safe, because hyphenation is deterministic for
        # unchanged text.
        self._outline_clean_text: Optional[str] = None

        self.idx = idx
        
        self.background_pixmap: QPixmap = None
        self.stroke_qcolor = QColor(0, 0, 0)
        self.oldPos = QPointF()
        self.oldRect = QRectF()
        self.repaint_on_changed = True

        self.is_formatting = False
        self.old_undo_steps = 0
        self.in_redo_undo = False
        self.change_from: int = 0
        self.change_added: int = 0
        self.input_method_from = -1
        self.input_method_text = ''
        self.block_all_input = False
        self.block_change_signal = False

        self.layout: Union[VerticalTextDocumentLayout, HorizontalTextDocumentLayout] = None
        # Auto font adjust: True when shrink/grow runs on handle drag.
        # Set False when user changes font manually (setFontSize) or when
        # the "Font Size: use global setting" option is selected
        # (pcfg.let_fntsize_flag == 1) — in that mode the program must not
        # resize the user's font. Re-evaluated on reshape end and gated in
        # _auto_adjust_font so a runtime settings change applies immediately.
        self._auto_font_adjust: bool = (pcfg.let_fntsize_flag != 1)
        # Per-block font size lock (context menu toggle): while locked,
        # automatic font adjust (shrink/grow on resize) must not change the
        # font — only explicit changes from the font panel are allowed.
        self._font_size_locked: bool = False
        self.font_adjuster: FontAutoAdjuster = None  # lazily created in _ensure_font_adjuster
        self._auto_adjusting: bool = False  # re-entrancy guard for auto-adjust loops
        self._fully_initialized: bool = False  # True after __init__ completes
        self.document().setDocumentMargin(0)
        self.initTextBlock(blk, set_format=set_format)
        self.setBoundingRegionGranularity(0)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        # Mark fully initialized AFTER initTextBlock/setRect so the first
        # auto-adjust passes only run on real user resize, not during init.
        self._fully_initialized = True
        # Eagerly create the adjuster so the attribute is always usable.
        self._ensure_font_adjuster()

    def inputMethodEvent(self, e: QInputMethodEvent):
        if self.pre_editing == False:
            cursor = self.textCursor()
            self.input_method_from = cursor.selectionStart()
        if e.preeditString() == '':
            self.pre_editing = False
            self.input_method_text = e.commitString()
        else:
            self.pre_editing = True
        super().inputMethodEvent(e)
        
    def is_editting(self):
        return self.textInteractionFlags() == Qt.TextInteractionFlag.TextEditorInteraction

    def on_content_changed(self):
        if (self.hasFocus() or self.is_formatting) and not self.pre_editing and not self.block_change_signal:   
            # self.content_changed.emit(self)
            if not self.in_redo_undo:
                undo_steps = self.document().availableUndoSteps()
                new_steps = undo_steps - self.old_undo_steps
                joint_previous = new_steps == 0

                if not self.is_formatting:
                    change_from = self.change_from
                    added_text = ''
                    if self.input_method_from != -1:
                        added_text = self.input_method_text
                        change_from = self.input_method_from
                        self.input_method_from = -1

                    elif self.change_added > 0:
                        cursor = self.textCursor()
                        cursor.setPosition(change_from)
                        cursor.setPosition(change_from + self.change_added, QTextCursor.MoveMode.KeepAnchor)
                        added_text = cursor.selectedText()

                    self.propagate_user_edited.emit(change_from, added_text, joint_previous)
                    self.change_added = 0

                if new_steps > 0:
                    self.old_undo_steps = undo_steps
                    self.push_undo_stack.emit(new_steps, self.is_formatting)

        if not (self.hasFocus() and self.pre_editing):
            if self.repaint_on_changed:
                if not self.repainting:
                    self.repaint_background()
            self.update()

    def _make_stroke_doc(self, html: str):
        doc = QTextDocument()
        doc.setUndoRedoEnabled(False)
        doc.setDocumentMargin(self.document().documentMargin())
        doc.setDefaultFont(self.document().defaultFont())
        doc.setHtml(html)
        doc.setDefaultTextOption(self.document().defaultTextOption())

        layout = VerticalTextDocumentLayout(doc, self.fontformat) if self.fontformat.vertical \
            else HorizontalTextDocumentLayout(doc, self.fontformat)
        layout._draw_offset = self.layout._draw_offset
        # Copy flow offsets only if they exist (horizontal layout only)
        if hasattr(self.layout, '_line_left_offsets'):
            layout._line_left_offsets = self.layout._line_left_offsets
        if hasattr(self.layout, '_line_right_offsets'):
            layout._line_right_offsets = self.layout._line_right_offsets
        if hasattr(self.layout, '_left_boundary_fn'):
            layout._left_boundary_fn = self.layout._left_boundary_fn
        if hasattr(self.layout, '_right_boundary_fn'):
            layout._right_boundary_fn = self.layout._right_boundary_fn
        layout._is_painting_stroke = True
        layout.setMaxSize(self.layout.max_width, self.layout.max_height, False)
        doc.setDocumentLayout(layout)
        layout.relayout_on_changed = False
        return doc, layout

    @staticmethod
    def _srgb_tuple(srgb) -> tuple:
        """Безопасный перевод srgb (list/tuple/np.array/None) в (r, g, b)."""
        if srgb is None:
            return (0, 0, 0)
        try:
            t = tuple(int(x) for x in srgb)
        except (TypeError, ValueError):
            return (0, 0, 0)
        return t[:3] if len(t) >= 3 else (0, 0, 0)

    def _stroke_groups(self):
        """Stroke groups: { (width_px, (r, g, b)): [(start, end), ...] }.

        Per-range outlines (blk.outline_ranges, set on selections) take
        priority; characters outside those ranges use the block-level
        stroke (fontformat.stroke_width)."""
        import numpy as np

        groups = {}
        n = self.document().rootFrame().lastPosition()
        if n <= 0:
            return groups
        base = pt2px(self.fontformat.font_size)
        ranges = []          # (s, e, w>0, c) — groups to dilate
        covered_spans = []   # every valid span, incl. w==0 (explicit "no outline")
        # Read-time validation: if the document text changed after the
        # ranges were set (snapshot mismatch), treat blk.outline_ranges as
        # EMPTY — fall back to the block-level stroke. The snapshot lives in
        # memory only, so after a project reload it is None and the
        # persisted ranges are accepted — safe, because hyphenation is
        # deterministic for unchanged text.
        if self.blk is not None and not self._outline_text_stale():
            for r in (getattr(self.blk, 'outline_ranges', None) or []):
                try:
                    s, e = int(r[0]), int(r[1])
                    w = float(r[2])
                    c = tuple(int(x) for x in r[3]) if len(r) > 3 and r[3] is not None \
                        else self._srgb_tuple(self.fontformat.srgb)
                except Exception:
                    continue
                if e <= s:
                    continue
                s = max(0, min(s, n))
                e = max(s, min(e, n))
                if e <= s:
                    continue
                covered_spans.append((s, e))
                if w > 0:
                    ranges.append((s, e, w, c))
        for (s, e, w, c) in ranges:
            # Scale the per-range stroke width against the actual font size
            # of the outlined characters (per-range font sizes are
            # supported), falling back to the block base font.
            range_base = self._range_font_size_px(s, e, base)
            groups.setdefault((max(1, int(round(range_base * w))), c), []).append((s, e))
        if self.fontformat.stroke_width > 0:
            block_c = self._srgb_tuple(self.fontformat.srgb)
            w_px = max(1, int(round(base * self.fontformat.stroke_width)))
            covered = np.zeros(n, dtype=bool)
            for (s, e) in covered_spans:
                covered[s:e] = True
            i = 0
            while i < n:
                if not covered[i]:
                    j = i
                    while j + 1 < n and not covered[j + 1]:
                        j += 1
                    groups.setdefault((w_px, block_c), []).append((i, j + 1))
                    i = j + 1
                else:
                    i += 1
        _debug("[stroke] idx=%s _stroke_groups: block_stroke=%s ranges=%s -> %s",
                     self.idx, self.fontformat.stroke_width,
                     getattr(self.blk, 'outline_ranges', None), groups)
        return groups

    def _range_font_size_px(self, s: int, e: int, fallback_px: float) -> float:
        """Max explicit per-character font size (px) within the document
        span [s, e).

        Per-range stroke widths are scaled against the actual size of the
        outlined characters (per-range font sizes are supported), with
        *fallback_px* (the block base font) when no fragment in the span
        carries an explicit size (pointSizeF() <= 0)."""
        doc = self.document()
        max_pt = 0.0
        block = doc.firstBlock()
        while block.isValid():
            if block.position() >= e:
                break
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fstart = frag.position()
                if fstart >= e:
                    break
                if fstart + frag.length() > s:
                    pt = frag.charFormat().font().pointSizeF()
                    if pt > max_pt:
                        max_pt = pt
                it += 1
            block = block.next()
        return pt2px(max_pt) if max_pt > 0 else fallback_px

    def paint_stroke(self, painter: QPainter):
        # Render the document to an image (preserving per-range formatting),
        # dilate alpha per stroke group (per-range outlines + block-level),
        # composite the stroke under the original text.
        from qtpy.QtGui import QImage
        from .misc import pixmap2ndarray
        import cv2
        import numpy as np

        html = self.document().toHtml()
        doc, layout = self._make_stroke_doc(html)

        size = self.layout.documentSize().toSize()
        text_img = QImage(size, QImage.Format.Format_ARGB32)
        text_img.fill(Qt.GlobalColor.transparent)
        text_painter = QPainter(text_img)
        doc.drawContents(text_painter)
        text_painter.end()

        try:
            groups = self._stroke_groups()
            if groups:
                for (w_px, srgb), spans in groups.items():
                    if w_px <= 0:
                        continue
                    # Render a copy of the document with only the group's
                    # characters opaque — everything else transparent.
                    gdoc, _ = self._make_stroke_doc(html)
                    cur = QTextCursor(gdoc)
                    cur.select(QTextCursor.SelectionType.Document)
                    trans = QTextCharFormat()
                    trans.setForeground(QColor(0, 0, 0, 0))
                    cur.mergeCharFormat(trans)
                    for (s, e) in spans:
                        cur.setPosition(s)
                        cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
                        opaque = QTextCharFormat()
                        opaque.setForeground(QColor(0, 0, 0, 255))
                        cur.mergeCharFormat(opaque)
                    gimg = QImage(size, QImage.Format.Format_ARGB32)
                    gimg.fill(Qt.GlobalColor.transparent)
                    gp = QPainter(gimg)
                    gdoc.drawContents(gp)
                    gp.end()
                    garray = pixmap2ndarray(gimg, keep_alpha=True)
                    if garray is None or garray.size == 0:
                        continue
                    galpha = garray[..., -1]
                    kernel_size = max(3, int(w_px * 0.3) * 2 + 1)
                    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
                    stroke_alpha = cv2.dilate(galpha, kernel, iterations=1)

                    # Create stroke image with the group's stroke color
                    stroke_array = garray.copy()
                    stroke_array[..., -1] = stroke_alpha
                    # Set RGB only where alpha > 0
                    mask = stroke_alpha > 0
                    stroke_array[..., 0] = np.where(mask, srgb[0], stroke_array[..., 0])
                    stroke_array[..., 1] = np.where(mask, srgb[1], stroke_array[..., 1])
                    stroke_array[..., 2] = np.where(mask, srgb[2], stroke_array[..., 2])

                    # stroke_array is RGBA byte order (from pixmap2ndarray) —
                    # declaring it as ARGB32 would swap R and B channels.
                    stroke_img = QImage(stroke_array.data, stroke_array.shape[1], stroke_array.shape[0], QImage.Format.Format_RGBA8888)
                    painter.drawImage(0, 0, stroke_img)

                # Draw original text on top
                painter.drawImage(0, 0, text_img)
            else:
                doc.drawContents(painter)
        except Exception as e:
            # Fallback to direct drawing if post-processing fails
            LOGGER.error(f"Stroke post-processing failed: {e}")
            doc.drawContents(painter)

        layout._is_painting_stroke = False

    def repaint_background(self):
        empty = self.document().isEmpty()
        if self.repainting:
            return

        paint_stroke = self.fontformat.stroke_width > 0 or self._has_outline_ranges()
        paint_shadow = self.fontformat.shadow_radius > 0 and self.fontformat.shadow_strength > 0
        if not paint_shadow and not paint_stroke or empty:
            self.background_pixmap = None
            return
        
        self.repainting = True
        font_size = self.layout.max_font_size(to_px=True)
        target_map = QPixmap(self.boundingRect().size().toSize())
        target_map.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target_map)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        if paint_stroke:
            self.paint_stroke(painter)
        else:
            self.document().drawContents(painter)

        # shadow
        if paint_shadow:
            r = int(round(self.fontformat.shadow_radius * font_size))
            xoffset, yoffset = int(self.fontformat.shadow_offset[0] * font_size), int(self.fontformat.shadow_offset[1] * font_size)
            shadow_map, img_array = apply_shadow_effect(target_map, self.fontformat.shadow_color, self.fontformat.shadow_strength, r)
            cm = painter.compositionMode()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
            painter.drawPixmap(xoffset, yoffset, shadow_map)
            painter.setCompositionMode(cm)

        painter.end()
        self.background_pixmap = target_map
        self.repainting = False
        
    def docSizeChanged(self):
        self.setCenterTransform()
        self.doc_size_changed.emit(self.idx)

    def initTextBlock(self, blk: TextBlock = None, set_format=True):
        self.blk = blk
        # (Re)binding a block: the in-memory outline snapshot belongs to the
        # previous block's text. Reset it so the NEW block's persisted
        # ranges are accepted during init (see
        # _maybe_invalidate_outline_ranges).
        self._outline_clean_text = None
        self.fontformat = blk.fontformat.deepcopy() if blk and blk.fontformat else blk.fontformat
        # Initialize TextFormatManager and FontSizeManager
        self.format_manager = TextFormatManager(self)
        self.font_size_mgr = FontSizeManager(self)
        # Save the font size explicitly — deepcopy may share internal state with blk.fontformat
        self._saved_font_size = self.fontformat.font_size if self.fontformat else 0
        if _is_log_target(self.blk):
            LOGGER.debug("[FONT] initTextBlock: idx=%d blk_font_size=%.1fpt fontformat_size=%.1fpt saved=%.1fpt",
                    self.idx if hasattr(self, 'idx') else -1,
                    px2pt(blk.fontformat.font_size) if blk and blk.fontformat else -1,
                    px2pt(self.fontformat.font_size) if self.fontformat else -1, px2pt(self._saved_font_size))
        if blk is None:
            xyxy = [0, 0, 0, 0]
            blk = TextBlock(xyxy)
            blk.lines = [xyxy]
            bx1, by1, bx2, by2 = xyxy
            xywh = np.array([[bx1, by1, bx2-bx1, by2-by1]])
            blk.lines = xywh2xyxypoly(xywh).reshape(-1, 4, 2).tolist()
        self.setVertical(blk.vertical)
        self.setRect(blk.bounding_rect())
        
        if blk.angle != 0:
            self.setRotation(blk.angle)
        
        set_char_fmt = False
        if blk.translation:
            set_char_fmt = True

        font_fmt = blk.fontformat
        if set_format:
            self.set_fontformat(font_fmt, set_char_format=set_char_fmt, set_stroke_width=False, set_effect=False)

        if not blk.rich_text:
            if blk.translation:
                self.setPlainText(blk.translation)
        else:
            self.setHtml(blk.rich_text)
            self.setLetterSpacing(font_fmt.letter_spacing, repaint_background=False)
            cursor = self.textCursor()
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cfmt = cursor.charFormat()
            cursor.setCharFormat(cfmt)
            cursor.setBlockCharFormat(cfmt)
            self.setTextCursor(cursor)
        if self.fontformat.gradient_enabled:
            self.setGradientEnabled(True)
        self.setShadow(font_fmt, repaint=False)
        self.setStrokeWidth(font_fmt.stroke_width, repaint_background=False)
        # Sync font_size from document — detector/OCR may have set fontformat.font_size=0
        doc_font_size = self.document().defaultFont().pointSizeF()
        old_font_size = self.fontformat.font_size
        if doc_font_size > 0:
            self.fontformat.font_size = pt2px(doc_font_size)
        if _is_log_target(self.blk):
            LOGGER.debug("[FONT] initTextBlock sync: idx=%d doc_size=%.1fpt old=%.1fpt new=%.1fpt",
                        self.idx if hasattr(self, 'idx') else -1,
                        doc_font_size, px2pt(old_font_size), px2pt(self.fontformat.font_size))
        self.repaint_background()

    def setCenterTransform(self):
        center = self.boundingRect().center()
        self.setTransformOriginPoint(center)

    def rect(self) -> QRectF:
        return QRectF(self.pos(), self.boundingRect().size())

    def startReshape(self):
        self.oldRect = self.absBoundingRect(qrect=True)
        self.reshaping = True

    def endReshape(self):
        # Reshape is a user resize action — re-enable auto-adjust so the
        # NEXT handle drag auto-sizes again (mirrors FlowTextBlkItem).
        # "Font Size: use global setting" keeps it disabled.
        if hasattr(self, 'font_adjuster'):
            self._auto_font_adjust = (pcfg.let_fntsize_flag != 1)
        self.reshaped.emit(self)
        self.reshaping = False

    def padRect(self, rect: QRectF) -> QRectF:
        p = self.padding()
        P = p * 2
        return QRectF(rect.x() - p, rect.y() - p, rect.width() + P, rect.height() + P)
    
    def unpadRect(self, rect: QRectF) -> QRectF:
        p = -self.padding()
        P = p * 2
        return QRectF(rect.x() - p, rect.y() - p, rect.width() + P, rect.height() + P)

    def setRect(self, rect: Union[List, QRectF], padding=True, repaint=True) -> None:
        def xywh_to_xyxy(xywh):
            if isinstance(rect, QRectF):
                    # Access properties using QRectF methods
                    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            else:
                # Fallback for list/tuple inputs
                x, y, w, h = rect[0], rect[1], rect[2], rect[3]
            return [x, y, x + w, y + h]

        if isinstance(rect, List):
            rect = QRectF(*rect)
        if padding:
            rect = self.padRect(rect)
        old_w = self._display_rect.width() if self._display_rect is not None else 0
        old_h = self._display_rect.height() if self._display_rect is not None else 0
        self.setPos(rect.topLeft())
        self.prepareGeometryChange()
        self._display_rect = rect
        # Capture the intended size BEFORE setMaxSize: when text overflows,
        # reLayout() emits size_enlarged → on_document_enlarged → set_size,
        # which expands _display_rect. We must shrink against the user's
        # intended size, not the expanded one.
        intended_w = rect.width()
        intended_h = rect.height()
        self.layout.setMaxSize(rect.width(), rect.height())
        self.setCenterTransform()
        self.blk.xyxy = xywh_to_xyxy(rect)
        if repaint:
            self.repaint_background()
        # Auto font-adjust on handle drag (plain TextBlkItem).
        # Only when fully initialized, size actually changed, and auto-adjust
        # is enabled. FlowTextBlkItem overrides this path with _update_flow_layout.
        # Use type-name check to avoid NameError from circular import ordering.
        # NOTE: compare against intended_w/h, NOT rect.width()/height(): the
        # bounce-back (setMaxSize → size_enlarged → set_size) mutates
        # self._display_rect in place — the same QRectF object as `rect` here —
        # restoring the natural height. When the block was already at its
        # natural height, rect.height() == old_h and the hook would skip the
        # shrink (height-only resizes did nothing).
        if (self._fully_initialized
                and self._auto_font_adjust
                and (abs(intended_w - old_w) > 0.5 or abs(intended_h - old_h) > 0.5)
                and type(self).__name__ != 'FlowTextBlkItem'):
            self._auto_adjust_font(target_w=intended_w, target_h=intended_h)

    def documentSize(self):
        return self.layout.documentSize()

    def boundingRect(self) -> QRectF:
        br = super().boundingRect()
        if self._display_rect is not None:
            br.setHeight(self._display_rect.height())
            br.setWidth(self._display_rect.width())
        return br

    def padding(self) -> float:
        return self.document().documentMargin()

    def setPadding(self, p: float):
        _p = self.padding()
        if _p >= p:
            return
        abr = self.absBoundingRect(qrect=True)
        self.layout.relayout_on_changed = False
        self.layout.updateDocumentMargin(p)
        self.layout.relayout_on_changed = True
        self.setRect(abr, repaint=False)

    def absBoundingRect(self, max_h=None, max_w=None, qrect=False) -> Union[List, QRectF]:
        br = self.boundingRect()
        P = 2 * self.padding()
        w, h = br.width() - P, br.height() - P
        pos = self.pos()
        x = pos.x() + self.padding()
        y = pos.y() + self.padding()
        if max_h is not None:
            y = min(max(0, y), max_h)
            y1 = y + h
            h = min(max_h, y1) - y
        if max_w is not None:
            x = min(max(0, x), max_w)
            x1 = x + w
            w = min(max_w, x1) - x
        if qrect:
            return QRectF(x, y, w, h)
        return [int(round(x)), int(round(y)), math.ceil(w), math.ceil(h)]

    def sync_coordinates(self):
        """Синхронизировать xyxy, lines, _bounding_rect из визуального состояния.

        Единственный метод записи координат. Не вызывать set_lines_by_xywh
        или записывать blk.xyxy напрямую — только через этот метод.
        """
        self.blk._bounding_rect = self.absBoundingRect()
        self.blk.set_lines_by_xywh(
            self.blk._bounding_rect,
            angle=-self.blk.angle,
            recalc_xyxy_from_lines=True
        )
        bx, by, bw, bh = self.blk._bounding_rect
        self.blk.xyxy = [int(bx), int(by), int(bx + bw), int(by + bh)]
        self._verify_coords()

    def _verify_coords(self):
        """Проверить согласованность координат (только в debug-режиме).

        Вызывается из sync_coordinates(). В release-режиме ничего не делает.
        """
        import sys
        if not sys.gettrace():
            return
        if not self.blk:
            return
        bx, by, bw, bh = self.absBoundingRect()
        expected = [int(bx), int(by), int(bx + bw), int(by + bh)]
        if self.blk.xyxy != expected:
            LOGGER.warning(
                "[COORD-INVARIANT] blk.xyxy=%s != absBoundingRect=%s idx=%d",
                self.blk.xyxy, expected, self.idx
            )

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        br = self.boundingRect()
        path.addRect(br)
        return path

    def setScale(self, scale: float) -> None:
        self.setTransformOriginPoint(0, 0)
        super().setScale(scale)
        self.setCenterTransform()

    @property
    def angle(self) -> int:
        return self.blk.angle

    def toTextBlock(self) -> TextBlock:
        raise NotImplementedError

    def setAngle(self, angle: int):
        self.setCenterTransform()
        if self.blk.angle != angle:
            self.setRotation(angle)
        self.blk.angle = angle

    def setVertical(self, vertical: bool):
        if self.fontformat is not None:
            self.fontformat.vertical = vertical

        valid_layout = True
        doc = self.document()
        if self.layout is not None:
            if isinstance(self.layout, VerticalTextDocumentLayout) == vertical:
                return
            self.layout.size_enlarged.disconnect(self.on_document_enlarged)
            self.layout.documentSizeChanged.disconnect(self.docSizeChanged)
        else:
            valid_layout = False
            doc.contentsChanged.connect(self.on_content_changed)
            doc.contentsChange.connect(self.on_content_changing)

        if valid_layout:
            rect = self.rect() if self.layout is not None else None
        
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        doc.documentLayout().blockSignals(True)
        if vertical:
            layout = VerticalTextDocumentLayout(doc, self.fontformat)
        else:
            layout = HorizontalTextDocumentLayout(doc, self.fontformat)
        
        self.layout = layout
        doc.setDocumentLayout(layout)
        layout.size_enlarged.connect(self.on_document_enlarged)
        layout.documentSizeChanged.connect(self.docSizeChanged)
        
        if valid_layout:
            layout.setMaxSize(rect.width(), rect.height())
            self.setCenterTransform()
            self.repaint_background()
        self.doc_size_changed.emit(self.idx)

    # ── Auto font-adjust (shared with FlowTextBlkItem) ────────

    def _block_text(self) -> str:
        """Return first 30 chars of block text for logging filter."""
        try:
            return self.document().toPlainText()[:30]
        except Exception:
            return ""

    def _should_log(self) -> bool:
        """True only for blocks whose text starts with a _LOG_PREFIXES entry."""
        txt = self._block_text()
        return any(txt.startswith(p) for p in _LOG_PREFIXES)

    def _log(self, msg: str, level: int = logging.DEBUG):
        """When quiet, log only for blocks matching _LOG_PREFIXES."""
        if level <= logging.DEBUG and not self._should_log():
            return
        LOGGER.log(level, "[%s] %s", self._block_text()[:20], msg)

    def _ensure_font_adjuster(self):
        """Lazily create the FontAutoAdjuster for this block.

        Plain TextBlkItem (non-flow) uses the same FontAutoAdjuster as
        FlowTextBlkItem so that handle-drag auto font-shrink/grow works
        after toggling from flow mode. The adjuster falls back to
        layout.available_height/width (no control points) — exactly what a
        plain rectangular block needs.
        """
        if self.font_adjuster is None:
            self.font_adjuster = FontAutoAdjuster(
                layout=self.layout,
                document=self.document(),
                log=self._log,
                change_font_size=self._font_adjuster_change_size,
                get_points=lambda: ([], []),  # plain block: no flow points
                sync_font=self._font_adjuster_sync,
            )
        return self.font_adjuster

    def _font_adjuster_change_size(self, factor: float):
        """Called by FontAutoAdjuster to apply a relative font size change."""
        adj = self._ensure_font_adjuster()
        adj._internal_font_change = True
        try:
            self.setRelFontSize(factor)
        finally:
            adj._internal_font_change = False

    def _font_adjuster_sync(self):
        """Called by FontAutoAdjuster after font size changes to sync fontformat/blk."""
        try:
            doc_font_pt = self.document().defaultFont().pointSizeF()
            if doc_font_pt > 0:
                self.font_size_mgr.set(doc_font_pt, source="auto_layout")
        except Exception:
            pass

    def _auto_adjust_font(self, target_w: float = None, target_h: float = None):
        """Run shrink/grow for a plain rectangular block after resize.

        Mirrors FlowTextBlkItem._update_flow_layout's auto-adjust section
        using the layout's available_height/width as target constraints.

        Args:
            target_w/target_h: The user's intended block size (full display
                rect, same convention as setRect/set_size). Passed from
                setRect/set_size because _display_rect may have been expanded
                by on_document_enlarged → set_size when text overflowed during
                setMaxSize (reLayout() expands available_height on overflow).
        """
        adj = self._ensure_font_adjuster()
        # Re-entrancy guard: shrink/grow call setRelFontSize → setFontSize
        # → squeezeBoundingRect → set_size → _auto_adjust_font.
        if self._auto_adjusting or not self._fully_initialized:
            return False
        if not self._auto_font_adjust:
            return False
        # Per-block font lock (context menu): block automatic font changes
        # while locked. Explicit panel changes go through setFontSize and
        # are not affected by the lock.
        if self._font_size_locked:
            return False
        # "Font Size: use global setting" (pcfg.let_fntsize_flag == 1) —
        # never auto-size the font. Checked here (single choke point for the
        # setRect/set_size hooks) so the setting also wins for items created
        # before the option was changed at runtime.
        if pcfg.let_fntsize_flag == 1:
            return False
        if not isinstance(self.layout, HorizontalTextDocumentLayout):
            return False
        if self._display_rect is None or not self._display_rect.isValid():
            return False

        self._auto_adjusting = True
        try:
            # Reset layout constraints to the intended block size because
            # reLayout() expands available_height on overflow. Convention
            # (same as setMaxSize): available = full size - 2*margin,
            # max = full size. A font that fits here will not re-trigger
            # size_enlarged when the size is re-asserted below.
            margin = self.document().documentMargin()
            if target_h is None:
                target_h = self._display_rect.height()
            if target_w is None:
                target_w = self._display_rect.width()
            self.layout.available_height = max(target_h - 2*margin, 0)
            self.layout.max_height = target_h
            self.layout.available_width = max(target_w - 2*margin, 0)
            self.layout.max_width = target_w
            font_changed = adj.shrink()
            if font_changed:
                # Undo the size_enlarged bounce-back: setMaxSize expanded
                # _display_rect to the natural text height, but now that the
                # font fits, restore the user's intended block size.
                if (self.layout.shrink_height <= self.layout.available_height
                        and self.layout.shrink_width <= self.layout.available_width):
                    self.set_size(target_w, target_h, set_layout_maxsize=True,
                                  set_blk_size=True, auto_font_adjust=False)
            # Only grow when shrink did NOT apply — prevents oscillation
            if adj._auto_grow_enabled and not font_changed:
                font_changed = adj.grow() or font_changed
            if font_changed:
                try:
                    self.reshaped.emit(self)
                except Exception:
                    pass
            return font_changed
        finally:
            self._auto_adjusting = False

    def updateUndoSteps(self):
        self.old_undo_steps = self.document().availableUndoSteps()

    def on_content_changing(self, from_: int, removed: int, added: int):
        if not self.pre_editing:
            if self.hasFocus():
                self.change_from = from_
                self.change_added = added

    def keyPressEvent(self, e: QKeyEvent) -> None:

        if self.block_all_input:
            e.setAccepted(True)
            return

        if e.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_Z:
                e.accept()
                self.undo_signal.emit()
                return
            elif e.key() == Qt.Key.Key_Y:
                e.accept()
                self.redo_signal.emit()
                return
            elif e.key() == Qt.Key.Key_V:
                if self.isEditing():
                    e.accept()
                    self.pasted.emit(self.idx)
                    return
        elif e.modifiers() == Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier:
            if e.key() == Qt.Key.Key_Z:
                e.accept()
                self.redo_signal.emit()
                return
        elif e.key() == Qt.Key.Key_Return:
            e.accept()
            self.textCursor().insertText('\n')
            return
        return super().keyPressEvent(e)

    def undo(self) -> None:
        self.in_redo_undo = True
        self.document().undo()
        self.in_redo_undo = False
        self.old_undo_steps = self.document().availableUndoSteps()

    def redo(self) -> None:
        self.in_redo_undo = True
        self.document().redo()
        self.in_redo_undo = False
        self.old_undo_steps = self.document().availableUndoSteps()

    def on_document_enlarged(self):
        size = self.documentSize()
        self.set_size(size.width(), size.height())

    def get_scale(self) -> float:
        tl = self.topLevelItem()
        if tl is not None:
            return tl.scale()
        else:
            return self.scale()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget) -> None:
        if _is_log_target(self.blk):
            LOGGER.debug("[FONTSIZE] BASE paint: idx=%d doc_font=%.1fpt fontformat=%.1fpx size_pt=%.1fpt",
                self.idx if hasattr(self, 'idx') else -1,
                self.document().defaultFont().pointSizeF(),
                self.fontformat.font_size if self.fontformat else 0,
                self.fontformat.size_pt if self.fontformat else 0)
        # subpixel antialiasing is enabled for super().paint upon drawing on some non-transparent background https://github.com/dmMaze/BallonsTranslator/issues/919
        # which can be avoided by calling super().paint first, but it results in disappeared background in editting mode
        # so the checking logic lies here
        
        if self.is_editting():
            self._draw_accessories(painter)

        option.state = QStyle.State_None
        super().paint(painter, option, widget)

        if not self.is_editting():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
            self._draw_accessories(painter)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


    def _draw_accessories(self, painter: QPainter):
        br = self.boundingRect()
        painter.save()
        
        if self.background_pixmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(br.toRect(), self.background_pixmap)

        draw_rect = self.draw_rect and not self.under_ctrl
        if self.isSelected() and not self.is_editting():
            pen = QPen(TEXTRECT_SELECTED_COLOR, 3.5 / self.get_scale(), Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.unpadRect(br))
        elif draw_rect:
            # Check if in normal mode (not flow mode) and use different color
            if self.blk and not self.blk.is_flow_mode:
                pen = QPen(QColor(255, 165, 0, 170), 3 / self.get_scale(), Qt.PenStyle.SolidLine)  # Orange for normal mode
            else:
                pen = QPen(TEXTRECT_SHOW_COLOR, 3 / self.get_scale(), Qt.PenStyle.SolidLine)  # Blue for flow mode
            painter.setPen(pen)
            painter.drawRect(self.unpadRect(br))
        painter.restore()


    def startEdit(self, pos: QPointF = None) -> None:
        self.pre_editing = False
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus()
        self.begin_edit.emit(self.idx)
        if pos is not None:
            hit = self.layout.hitTest(pos, None)
            cursor = self.textCursor()
            cursor.setPosition(hit)
            self.setTextCursor(cursor)

    def endEdit(self, keep_focus=True) -> None:
        self.end_edit.emit(self.idx)
        cursor = self.textCursor()
        clean_text = self.document().toPlainText().replace('\xad', '')
        if cursor.hasSelection():
            # Keep the selection for subsequent panel format operations:
            # clearing the cursor selection below would otherwise make the
            # user's "format that part" intent unreachable (the panel
            # fallback only sees panel-side selections). Validated by the
            # clean-text snapshot in _effective_selection().
            self._last_selection = (
                clean_text,
                cursor.selectionStart(),
                cursor.selectionEnd(),
            )
            self._last_cursor_state = (
                clean_text,
                cursor.selectionStart(),
                cursor.selectionEnd(),
            )
            _debug("[stroke] idx=%d endEdit: saved _last_selection=(%d, %d) text=%r",
                        self.idx, cursor.selectionStart(), cursor.selectionEnd(),
                        clean_text)
        else:
            self._last_cursor_state = (
                clean_text,
                cursor.position(),
                cursor.position(),
            )
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        if keep_focus:
            self.setFocus()

    def isEditing(self) -> bool:
        return self.textInteractionFlags() == Qt.TextInteractionFlag.TextEditorInteraction

    def isMultiFontSize(self) -> bool:
        doc = self.document()
        block = doc.firstBlock()
        if block.isValid():
            it = block.begin()
            if it.atEnd():
                firstFontSize = block.charFormat().fontPointSize()
            else:
                # empty blocks causes frozen for pyside==6.8.1
                # also randomly freezes pyqt==6.6.1 https://github.com/dmMaze/BallonsTranslator/issues/736
                firstFontSize = it.fragment().charFormat().fontPointSize()
        else:
            return False
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                font_size = fragment.charFormat().fontPointSize()
                if not firstFontSize == font_size:
                    return True
                it += 1
            block = block.next()
        return False
    
    def minFontSize(self, to_px=True):
        doc = self.document()
        block = doc.firstBlock()
        min_font_size = 0.0
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                font_size = fragment.charFormat().fontPointSize()
                if font_size > 0:
                    if min_font_size <= 0 or font_size < min_font_size:
                        min_font_size = font_size
                it += 1
            block = block.next()
        # Fallback to stored font_size if nothing found in document
        if min_font_size <= 0 and self.fontformat is not None:
            return self.fontformat.font_size
        if to_px:
            min_font_size = pt2px(min_font_size)
        return min_font_size

    def get_cursor_font_range(self) -> Optional[Tuple[int, int]]:
        """(start, end) in item-document coordinates for the *live* cursor
        position, or None.

        Used by the panel font-size display only. Unlike _effective_selection():
        bare-cursor positions are reported too (size "under the cursor"),
        and the last-resort fallback is _last_cursor_state (the canvas cursor
        at endEdit time), not _last_selection — a bare cursor moved to another
        word must not keep displaying the old selection's size."""
        try:
            from . import shared_widget as SW
            cursor = self.textCursor()
            item_sel = None
            if cursor.hasSelection():
                item_sel = (cursor.selectionStart(), cursor.selectionEnd())
            item_pos = cursor.position()
            editing = self.isEditing()

            e_sel = None
            e_pos = None
            e_focused = False
            st = SW.st_manager
            if st is not None and getattr(st, 'pairwidget_list', None) \
                    and 0 <= self.idx < len(st.pairwidget_list):
                e_trans = st.pairwidget_list[self.idx].e_trans
                if e_trans is not None:
                    item_text = self.document().toPlainText()
                    if item_text.replace('\xad', '') == e_trans.toPlainText():
                        c2 = e_trans.textCursor()
                        if c2.hasSelection():
                            ps, pe = c2.selectionStart(), c2.selectionEnd()
                            e_sel = (self._panel_pos_to_doc_start(item_text, ps),
                                     self._panel_pos_to_doc_end(item_text, pe))
                        else:
                            e_pos = self._panel_pos_to_doc_start(item_text,
                                                                 c2.position())
                        e_focused = bool(e_trans.hasFocus())

            # Priority = most recent interaction first: an editing canvas
            # cursor, then the focused paired editor (the editor the user
            # is looking at), then a canvas selection, then a stale editor
            # selection, then the last endEdit cursor state.
            if editing:
                if item_sel is not None:
                    return item_sel
                return (item_pos, item_pos + 1)
            if e_focused:
                if e_sel is not None:
                    return e_sel
                if e_pos is not None:
                    return (e_pos, e_pos + 1)
            if item_sel is not None:
                return item_sel
            if e_sel is not None:
                return e_sel
            state = getattr(self, '_last_cursor_state', None)
            if state is not None:
                text, s, e = state
                if text == self.document().toPlainText().replace('\xad', ''):
                    return (s, max(s + 1, e))
        except Exception:
            pass
        _debug("[FONTSIZE] idx=%s get_cursor_font_range -> None",
                    getattr(self, 'idx', None))
        return None

    def get_cursor_font_size(self) -> Optional[Tuple[float, bool]]:
        """(size_pt, mixed) of the live cursor position for the panel font-size
        display, or None (the panel keeps the block-scalar display).

        Per-range sizes live in the block document's char formats
        (setFontSize -> set_cursor_cfmt); characters never individually sized
        (pointSize <= 0) fall back to the block scalar. mixed=True when the
        range spans several sizes (the panel shows "size+")."""
        rng = self.get_cursor_font_range()
        if rng is None:
            return None
        s, e = rng
        doc = self.document()
        if doc.isEmpty():
            return None
        lastpos = doc.rootFrame().lastPosition()
        s = max(0, min(int(s), lastpos))
        e = max(s, min(int(e), lastpos))
        if e <= s:
            e = min(s + 1, lastpos)
        if lastpos <= 0 or e <= s:
            return None
        fallback_pt = self.fontformat.size_pt if self.fontformat is not None else 0.0
        first_size: Optional[float] = None
        mixed = False
        block = doc.findBlock(s)
        while block.isValid() and block.position() < e:
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fstart = frag.position()
                fend = fstart + frag.length()
                if fstart >= e:
                    break
                if fend > s:
                    pt = frag.charFormat().fontPointSize()
                    if pt <= 0:
                        pt = fallback_pt
                    pt = round(pt, 2)
                    if first_size is None:
                        first_size = pt
                    elif pt != first_size:
                        mixed = True
                it += 1
            block = block.next()
        if first_size is None:
            return None
        return first_size, mixed

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if not self.isEditing():
            self.startEdit(pos=event.pos())
        else:
            super().mouseDoubleClickEvent(event)
        
    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseMoveEvent(event)  
        if self.textInteractionFlags() != Qt.TextInteractionFlag.TextEditorInteraction:
            self.moving.emit(self)

    # QT 5.15.x causing segmentation fault
    def contextMenuEvent(self, event):
        # Don't show menu if in edit mode
        if self.is_editting():
            super().contextMenuEvent(event)
            return

        event.accept()
        menu = QMenu()
        self.injectToggleFlowMenu(menu)
        self.injectFontLockMenu(menu)
        menu.exec_(event.globalPos())

    def injectToggleFlowMenu(self, menu: QMenu):
        """Insert the 'Toggle Flow Mode' action at the top of an existing QMenu."""
        toggle_flow = QAction(self.tr('Toggle Flow Mode'), menu)
        LOGGER.debug(f"[TOGGLE_MENU] Adding toggle action for idx={self.idx}, is FlowTextBlkItem=False")
        def on_toggle_clicked():
            LOGGER.debug(f"[TOGGLE_ACTION] Toggle clicked for idx={self.idx}")
            # Try to get SceneTextManager and call toggle directly
            scene = self.scene()
            if scene and hasattr(scene, 'st_manager'):
                LOGGER.debug(f"[TOGGLE_ACTION] Calling toggle_block_flow_mode directly via st_manager")
                scene.st_manager.toggle_block_flow_mode(self.idx)
            else:
                LOGGER.debug(f"[TOGGLE_ACTION] Falling back to signal (scene={scene}, has st_manager={scene and hasattr(scene, 'st_manager')})")
                self.toggle_flow_mode_requested.emit(self.idx)
        toggle_flow.triggered.connect(on_toggle_clicked)
        menu.setProperty('_bt_toggle_flow_action', toggle_flow)
        first_action = menu.actions()[0] if menu.actions() else None
        if first_action is not None:
            menu.insertAction(first_action, toggle_flow)
            sep = QAction(menu)
            sep.setSeparator(True)
            menu.insertAction(first_action, sep)
        else:
            menu.addAction(toggle_flow)
            menu.addSeparator()

    def showNormalContextMenu(self, scene_pos: QPointF, screen_pos):
        """Show the standard canvas context menu with the flow-mode toggle on top.

        Used by TextBlkShapeControl.handleContextMenu for normal (non-flow)
        blocks, mirroring FlowTextBlkItem.showFlowContextMenu.
        """
        self.setSelected(True)
        scene = self.scene()
        if scene is not None and hasattr(scene, 'build_context_menu') and hasattr(scene, 'exec_context_menu'):
            std_menu, actions = scene.build_context_menu()
            self.injectToggleFlowMenu(std_menu)
            self.injectFontLockMenu(std_menu)
            screen_pt = screen_pos.toPoint() if hasattr(screen_pos, 'toPoint') else screen_pos
            scene.exec_context_menu(std_menu, actions, screen_pt)

    def injectFontLockMenu(self, menu: QMenu):
        """Add a checkable 'Lock font size' action to the block context menu.

        While locked, automatic font adjust (shrink/grow on block resize) is
        blocked for this block. The font size can only be changed explicitly
        from the font panel (setFontSize is not affected by the lock).
        """
        lock = QAction(self.tr('Lock font size'), menu)
        lock.setCheckable(True)
        lock.setChecked(getattr(self, '_font_size_locked', False))
        lock.setToolTip(self.tr(
            'Block automatic font resizing when this block is resized. '
            'The font size can only be changed from the font panel.'))
        lock.toggled.connect(lambda checked: setattr(self, '_font_size_locked', checked))
        # Place directly next to 'Toggle Flow Mode' (right after it). The
        # toggle action is tagged by injectToggleFlowMenu / injectFlowMenuItems.
        actions = menu.actions()
        toggle = menu.property('_bt_toggle_flow_action')
        if toggle is not None and toggle in actions:
            idx = actions.index(toggle)
            menu.insertAction(actions[idx + 1] if idx + 1 < len(actions) else None, lock)
        else:
            menu.addAction(lock)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = self.pos()
            sel = None
            if self.scene() is not None:
                sel = [i.idx for i in self.scene().selectedItems() if hasattr(i, 'idx')]
            _debug("[FLOWDRAG] native press (block handles it itself): idx=%s scenePos=(%.1f,%.1f) selected=%s",
                   self.idx, event.scenePos().x(), event.scenePos().y(), sel)
            self.leftbutton_pressed.emit(self.idx)
        return super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.oldPos != self.pos():
                self.moved.emit()
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self.hover_move.emit(self.idx)
        return super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self.hover_enter.emit(self.idx)
        return super().hoverEnterEvent(event)

    def toPixmap(self) -> QPixmap:
        pixmap = QPixmap(self.boundingRect().size().toSize())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        doc = self.document()
        doc.drawContents(painter)
        painter.end()
        return pixmap

    def toHtml(self) -> str:
        html = super().toHtml()
        tables = table_pattern.findall(html)
        if tables:
            _, td = td_pattern.findall(html)[0]
            html = tables[0] + td + '</body></html>'

        return html.replace('>\n<', '><')

    def get_fontformat(self) -> FontFormat:
        fmt = self.textCursor().charFormat()
        font = fmt.font()
        color = fmt.foreground().color()
        fontformat = self.fontformat.deepcopy()
        fontformat.frgb = [color.red(), color.green(), color.blue()]
        fontformat.font_weight = font.weight()
        fontformat.font_family = font.family()
        # Always use self.fontformat.font_size (user's choice, set by setFontSize)
        # This preserves the user's choice across auto-layout
        # Preserve gradient settings
        fontformat.gradient_enabled = self.fontformat.gradient_enabled
        fontformat.gradient_start_color = self.fontformat.gradient_start_color
        fontformat.gradient_end_color = self.fontformat.gradient_end_color
        fontformat.gradient_angle = self.fontformat.gradient_angle
        fontformat.gradient_size = self.fontformat.gradient_size
        caller = inspect.stack()[1].function if len(inspect.stack()) > 1 else '?'
        if _is_log_target(self.blk):
            LOGGER.debug("[FONTSIZE] TEXTITEM get_fontformat: idx=%d font_size=%.1fpx size_pt=%.1fpt caller=%s",
                self.idx, fontformat.font_size, fontformat.size_pt, caller)
        return fontformat

    def set_fontformat(self, ffmat: FontFormat, set_char_format=False, set_stroke_width=True, set_effect=True):
        self.repainting = True
        if self.fontformat.vertical != ffmat.vertical:
            self.setVertical(ffmat.vertical)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        format = cursor.charFormat()
        font = self.document().defaultFont()
        
        font.setFamily(ffmat.font_family)
        font.setPointSizeF(ffmat.size_pt)
        caller = inspect.stack()[1].function if len(inspect.stack()) > 1 else '?'
        if _is_log_target(self.blk):
            LOGGER.debug("[FONTSIZE] TEXTITEM set_fontformat: size_pt=%.1fpt from font_size=%.1fpx caller=%s",
                ffmat.size_pt, ffmat.font_size, caller)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)

        fweight = ffmat.font_weight
        if fweight is  None:
            fweight = font.weight()
            ffmat.font_weight = fweight
        font.setBold(ffmat.bold)

        old_doc_font = self.document().defaultFont().pointSizeF()
        self.document().setDefaultFont(font)
        if _is_log_target(self.blk):
            LOGGER.debug("[FONTSIZE] TEXTITEM set_fontformat setDocFont: idx=%d doc_font %.1fpt -> %.1fpt (ffmat.size_pt=%.1f)",
                self.idx if hasattr(self, 'idx') else -1,
                old_doc_font, font.pointSizeF(), ffmat.size_pt)
        format.setFont(font)
        if ffmat.gradient_enabled:
            gradient = self.get_text_gradient(ffmat)
            format.setForeground(gradient)
        else:
            format.setForeground(QColor(*ffmat.foreground_color()))
        if not ffmat.bold:
            format.setFontWeight(fweight)
        format.setFontItalic(ffmat.italic)
        format.setFontUnderline(ffmat.underline)
        if not ffmat.vertical:
            format.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
            format.setFontLetterSpacing(ffmat.letter_spacing * 100)
        cursor.setCharFormat(format)
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setBlockCharFormat(format)
        if set_char_format:
            cursor.setCharFormat(format)
        cursor.clearSelection()
        # https://stackoverflow.com/questions/37160039/set-default-character-format-in-qtextdocument
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        self.stroke_qcolor = QColor(*ffmat.stroke_color())

        if set_effect:
            self.setShadow(ffmat, repaint=False)
        if set_stroke_width:
            self.setStrokeWidth(ffmat.stroke_width, repaint_background=False)
        self.setOpacity(ffmat.opacity)
        
        alignment_qt_flag = [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignCenter, Qt.AlignmentFlag.AlignRight][ffmat.alignment]
        doc = self.document()
        op = doc.defaultTextOption()
        op.setAlignment(alignment_qt_flag)
        doc.setDefaultTextOption(op)
        
        if ffmat.vertical:
            self.setLetterSpacing(ffmat.letter_spacing)
        self.setLineSpacing(ffmat.line_spacing)
        
        # Preserve gradient properties
        self.fontformat.gradient_enabled = ffmat.gradient_enabled
        self.fontformat.gradient_start_color = ffmat.gradient_start_color
        self.fontformat.gradient_end_color = ffmat.gradient_end_color
        self.fontformat.gradient_angle = ffmat.gradient_angle
        self.fontformat.gradient_size = ffmat.gradient_size

        old_font_size = self.fontformat.font_size
        self.fontformat.merge(ffmat)
        if _is_log_target(self.blk):
            LOGGER.debug("[FONT] set_fontformat merge: idx=%d old=%.1fpt new=%.1fpt ffmat=%.1fpt doc_size=%.1fpt",
                        self.idx if hasattr(self, 'idx') else -1,
                        px2pt(old_font_size), px2pt(self.fontformat.font_size), px2pt(ffmat.font_size),
                        self.document().defaultFont().pointSizeF())
        
        if self.fontformat.gradient_enabled:
            self.update()

        self.repainting = False
        if set_effect or set_stroke_width:
            self.repaint_background()

    def updateBlkFormat(self):
        fmt = self.get_fontformat()
        # Use self.fontformat.font_size as the source of truth.
        # It is updated by setFontSize() (user changes) and _font_adjuster_sync() (auto-shrink).
        # Do NOT read from document defaultFont — it can be stale after initTextBlock()
        # sets it to the original blk.fontformat value before auto-shrink runs.
        if self.fontformat is not None:
            fmt.font_size = self.fontformat.font_size
            if self.blk is not None and self.blk.fontformat is not None:
                self.blk.fontformat.font_size = self.fontformat.font_size
        old_blk_size = self.blk.fontformat.font_size
        old_blk_stroke = self.blk.fontformat.stroke_width
        self.blk.fontformat.merge(fmt)
        if self.blk.fontformat.stroke_width != old_blk_stroke:
            _debug("[stroke] idx=%d updateBlkFormat: blk stroke CHANGED %s -> %s (item stroke=%s)",
                           self.idx, old_blk_stroke, self.blk.fontformat.stroke_width,
                           self.fontformat.stroke_width)
        # DEBUG: verify object identity
        _is_same = self.fontformat is self.blk.fontformat
        if _is_same:
            LOGGER.debug("[FONT] WARNING: self.fontformat IS self.blk.fontformat! idx=%d", self.idx)
        if _is_log_target(self.blk):
             LOGGER.debug("[FONT] updateBlkFormat: idx=%d old_blk=%.1fpt new_blk=%.1fpt fmt_size=%.1fpt fontformat_size=%.1fpt same=%s",
                    self.idx if hasattr(self, 'idx') else -1,
                    px2pt(old_blk_size), px2pt(self.blk.fontformat.font_size), px2pt(fmt.font_size),
                    px2pt(self.fontformat.font_size) if self.fontformat else -1, _is_same)


    def set_cursor_cfmt(self, cursor: QTextCursor, cfmt: QTextCharFormat, merge_char: bool = False):
        doc_is_empty = self.document().isEmpty()
        if merge_char:
            self.block_change_signal = True
            cursor.mergeCharFormat(cfmt)
            self.block_change_signal = False
        # Apply to block format only when there is no active selection or the
        # whole document is selected. Otherwise mergeBlockCharFormat would
        # overwrite the format of the entire block, ignoring the selected
        # fragment (bold/italic/etc. would apply to all text instead of just
        # the selection).
        doc = self.document()
        full_doc_selected = (cursor.selectionStart() == 0 and
                             cursor.selectionEnd() == doc.rootFrame().lastPosition())
        if not cursor.hasSelection() or full_doc_selected:
            cursor.mergeBlockCharFormat(cfmt)
        cursor.clearSelection()
        self.setTextCursor(cursor)
        # Always update document default font to match the cursor font
        old_doc_font = self.document().defaultFont().pointSizeF()
        new_font = cursor.blockCharFormat().font()
        self.document().setDefaultFont(new_font)
        if _is_log_target(self.blk):
            LOGGER.debug("[FONTSIZE] TEXTITEM set_cursor_cfmt: idx=%d doc_font %.1fpt -> %.1fpt",
                self.idx if hasattr(self, 'idx') else -1,
                old_doc_font, new_font.pointSizeF())

    def _before_set_ffmt(self, set_selected: bool, restore_cursor: bool):
        self.is_formatting = True
        cursor = self.textCursor()

        cursor_pos = None
        if restore_cursor:
            cursor_pos = (cursor.position(), cursor.anchor().__pos__()) if restore_cursor else None

        if set_selected:
            has_set_all = not cursor.hasSelection()
            if has_set_all:
                cursor.select(QTextCursor.SelectionType.Document)
        else:
            has_set_all = False
            cursor = QTextCursor(self.document())
            cursor.select(QTextCursor.SelectionType.Document)

        cursor.beginEditBlock()
        return cursor, dict(cursor_pos=cursor_pos, has_set_all=has_set_all)

    def _after_set_ffmt(self, cursor: QTextCursor, repaint_background: bool, restore_cursor: bool, cursor_pos: Tuple, has_set_all: bool):
        
        if restore_cursor:
            if cursor_pos is not None:
                pos1, pos2 = cursor_pos
                if has_set_all:
                    cursor.setPosition(pos1)
                else:
                    cursor.setPosition(min(pos1, pos2))
                    cursor.setPosition(max(pos1, pos2), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor)

        if repaint_background:
            self.repaint_background()

        cursor.endEditBlock()
        self.is_formatting = False

    def setFontFamily(self, value: str, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        self.layout.relayout_on_changed = False
        self._doc_set_font_family(value, cursor)
        self.layout.relayout_on_changed = True
        self.layout.reLayoutEverything()
        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def _doc_set_font_family(self, value: str, cursor: QTextCursor):
        doc = self.document()
        lastpos = doc.rootFrame().lastPosition()
        if cursor.selectionStart() == 0 and \
            cursor.selectionEnd() == lastpos:
            font = doc.defaultFont()
            font.setFamily(value)
            doc.setDefaultFont(font)

        sel_start = cursor.selectionStart()
        sel_end = cursor.selectionEnd()
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                
                frag_start = fragment.position()
                frag_end = frag_start + fragment.length()
                pos2 = min(frag_end, sel_end)
                pos1 = max(frag_start, sel_start)
                if pos1 < pos2:
                    cfmt = fragment.charFormat()
                    under_line = cfmt.fontUnderline()
                    cfont = cfmt.font()
                    font = QFont(value, cfont.pointSize(), cfont.weight(), cfont.italic())
                    font.setPointSizeF(cfont.pointSizeF())
                    font.setBold(font.bold())
                    font.setWordSpacing(cfont.wordSpacing())
                    font.setLetterSpacing(cfont.letterSpacingType(), cfont.letterSpacing())
                    cfmt.setFont(font)
                    cfmt.setFontUnderline(under_line)
                    cursor.setPosition(pos1)
                    cursor.setPosition(pos2, QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(cfmt)
                it += 1
            block = block.next()

        cfmt = cursor.charFormat()
        cfmt.setFontFamily(value)
        self.set_cursor_cfmt(cursor, cfmt)

    def setFontWeight(self, value: float, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        cfmt = QTextCharFormat()
        cfmt.setFontWeight(value)
        self.set_cursor_cfmt(cursor, cfmt, True)
        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def setFontItalic(self, value: bool, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        cfmt = QTextCharFormat()
        cfmt.setFontItalic(value)
        self.set_cursor_cfmt(cursor, cfmt, True)
        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def setFontUnderline(self, value: bool, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        cfmt = QTextCharFormat()
        cfmt.setFontUnderline(value)
        self.set_cursor_cfmt(cursor, cfmt, True)
        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def setGradientEnabled(self, value: bool, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        self.fontformat.gradient_enabled = value
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        cfmt = QTextCharFormat()
        if value:
            gradient = self.get_text_gradient()
            cfmt.setForeground(gradient)
        else:
            cfmt.setForeground(QColor(*[int(c) for c in self.fontformat.frgb]))

        self.set_cursor_cfmt(cursor, cfmt, True)
        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def get_text_gradient(self, fontformat: FontFormat = None):
        gradient = QLinearGradient()
        if fontformat is None:
            fontformat = self.fontformat
        angle = fontformat.gradient_angle
        rad = math.radians(angle)
        dx = math.cos(rad)
        dy = math.sin(rad)
        
        # Set gradient points with size adjustment
        rect = self.boundingRect()
        center = rect.center()
        radius = max(rect.width(), rect.height()) * fontformat.gradient_size
        gradient.setStart(center.x() - dx * radius, center.y() - dy * radius)
        gradient.setFinalStop(center.x() + dx * radius, center.y() + dy * radius)
        
        # Set gradient colors
        start_color = QColor(*fontformat.gradient_start_color)
        end_color = QColor(*fontformat.gradient_end_color)
        gradient.setColorAt(0, start_color)
        gradient.setColorAt(1, end_color)
        return gradient

    def setLineSpacing(self, value: float, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        self.is_formatting = True
        self.fontformat.line_spacing = value
        self.layout.setLineSpacing(value)
        if repaint_background:
            self.repaint_background()
            self.update()
        self.is_formatting = False

    def setLineSpacingType(self, value: int, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False):
        self.is_formatting = True
        self.fontformat.line_spacing_type = value
        self.layout.setLineSpacingType(value)
        if repaint_background:
            self.repaint_background()
            self.update()
        self.is_formatting = False

    def setLetterSpacing(self, value: float, repaint_background: bool = True, set_selected: bool = False, restore_cursor: bool = False, force=False):
        self.is_formatting = True
        self.fontformat.letter_spacing = value
        if self.fontformat.vertical:
            self.layout.setLetterSpacing(value)
        else:
            cursor = QTextCursor(self.document())
            char_fmt = QTextCharFormat()
            char_fmt.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
            char_fmt.setFontLetterSpacing(value * 100)
            cursor.select(QTextCursor.SelectionType.Document)
            self.set_cursor_cfmt(cursor, char_fmt, True)

        if repaint_background:
            self.repaint_background()
            self.update()

        self.is_formatting = False

    def setFontColor(self, value: Tuple, repaint_background: bool = False, set_selected: bool = False, restore_cursor: bool = False, force=False):
        cursor, after_kwargs = self._before_set_ffmt(set_selected, restore_cursor)
        cfmt = QTextCharFormat()
        # Coerce components to int — undo values may be floats (e.g. [0.0, 0.0, 0.0])
        # and QColor requires ints.
        cfmt.setForeground(QColor(*[int(c) for c in value]))
        self.set_cursor_cfmt(cursor, cfmt, True)
        self._after_set_ffmt(cursor, repaint_background=repaint_background, restore_cursor=restore_cursor, **after_kwargs)

    def _has_outline_ranges(self) -> bool:
        return bool(self.blk is not None and getattr(self.blk, 'outline_ranges', None))

    def _outline_text_stale(self) -> bool:
        """True when blk.outline_ranges is stale: the clean document text no
        longer matches the snapshot captured in set_selection_outline().

        The snapshot lives in memory only — after a project reload it is
        None and the persisted ranges are accepted again: safe, because
        hyphenation is deterministic for unchanged text."""
        snapshot = getattr(self, '_outline_clean_text', None)
        if snapshot is None:
            return False
        return self.document().toPlainText().replace('\u00ad', '') != snapshot

    def _save_outline_snapshot(self) -> None:
        """Record the clean document text that blk.outline_ranges is valid
        against (called after every successful outline_ranges mutation)."""
        self._outline_clean_text = self.document().toPlainText().replace('\u00ad', '')

    def _maybe_invalidate_outline_ranges(self) -> None:
        """Clear stale per-range outlines after the block text was replaced
        (setPlainText/setHtml hook).

        Does nothing during the initial load in __init__: the snapshot is
        None at that moment, so persisted ranges are accepted."""
        snapshot = getattr(self, '_outline_clean_text', None)
        if snapshot is None:
            return
        if self.document().toPlainText().replace('\u00ad', '') == snapshot:
            return
        if self.blk is not None and getattr(self.blk, 'outline_ranges', None):
            _debug("[stroke] idx=%s text changed: clearing stale outline_ranges %s",
                       self.idx, self.blk.outline_ranges)
            self.blk.outline_ranges = []
            self.repaint_background()
            self.update()
        self._outline_clean_text = None

    def setPlainText(self, text: str = '') -> None:
        """QGraphicsTextItem.setPlainText + outline invalidation hook.

        FlowTextBlkItem overrides this and calls super(), so the flow path
        (hyphenated document text) is covered by the same hook."""
        super().setPlainText(text)
        self._maybe_invalidate_outline_ranges()

    def setHtml(self, html: str = '') -> None:
        """QGraphicsTextItem.setHtml + outline invalidation hook
        (rich-text path)."""
        super().setHtml(html)
        self._maybe_invalidate_outline_ranges()

    def _effective_selection(self):
        """Selection as (start, end) in item-document coordinates, or None.

        Uses the item's own cursor if it has a selection, otherwise falls
        back to the paired panel editor (text selected in the translation
        panel rather than on the canvas), then to the last canvas selection
        saved in endEdit() (selections are cleared on focus loss, but the
        user's intent to format "that part" should survive). The item
        document may contain soft hyphens (flow blocks), so panel offsets
        are mapped through the soft-hyphen positions."""
        try:
            cursor = self.textCursor()
            if cursor.hasSelection():
                sel = (cursor.selectionStart(), cursor.selectionEnd())
                _debug("[stroke] idx=%d _effective_selection -> item cursor %s",
                             self.idx, sel)
                return sel
            from . import shared_widget as SW
            st = SW.st_manager
            if st is not None and getattr(st, 'pairwidget_list', None) \
                    and self.idx < len(st.pairwidget_list):
                e_trans = st.pairwidget_list[self.idx].e_trans
                if e_trans is not None:
                    c2 = e_trans.textCursor()
                    if c2.hasSelection():
                        item_text = self.document().toPlainText()
                        if item_text.replace('\xad', '') != e_trans.toPlainText():
                            _debug("[stroke] idx=%d panel selection REJECTED (text mismatch): item=%r panel=%r",
                                        self.idx, item_text.replace('\xad', ''),
                                        e_trans.toPlainText())
                            return None
                        ps, pe = c2.selectionStart(), c2.selectionEnd()
                        sel = (self._panel_pos_to_doc_start(item_text, ps),
                               self._panel_pos_to_doc_end(item_text, pe))
                        _debug("[stroke] idx=%d _effective_selection -> panel %s (panel sel (%d, %d))",
                                     self.idx, sel, ps, pe)
                        return sel
            last = getattr(self, '_last_selection', None)
            if last is not None:
                text, s, e = last
                if text == self.document().toPlainText().replace('\xad', ''):
                    _debug("[stroke] idx=%d _effective_selection -> last_selection (%d, %d)",
                                 self.idx, s, e)
                    return s, e
                _debug("[stroke] idx=%d last_selection stale (text changed)", self.idx)
        except Exception:
            pass
        _debug("[stroke] idx=%d _effective_selection -> None (item_sel=%s, last_sel=%s)",
                     self.idx, self.textCursor().hasSelection(),
                     getattr(self, '_last_selection', None) is not None)
        return None

    @staticmethod
    def _panel_pos_to_doc_start(item_text: str, pos: int) -> int:
        """Item-document offset of the *pos*-th non-soft-hyphen char."""
        clean, i, n = 0, 0, len(item_text)
        while i < n and clean < pos:
            if item_text[i] != '\xad':
                clean += 1
            i += 1
        while i < n and item_text[i] == '\xad':
            i += 1
        return i

    @staticmethod
    def _panel_pos_to_doc_end(item_text: str, pos: int) -> int:
        """Exclusive item-document offset covering *pos* non-soft-hyphen
        chars (for selection end mapping)."""
        clean, i, n = 0, 0, len(item_text)
        while i < n and clean < pos:
            if item_text[i] != '\xad':
                clean += 1
            i += 1
        return i

    def _has_effective_selection(self) -> bool:
        return self._effective_selection() is not None

    def get_selection_outline(self):
        """(width, [r, g, b]) of the outline range covering the effective
        selection, or None if no range covers it."""
        sel = self._effective_selection()
        if sel is None or not self._has_outline_ranges():
            return None
        # Stale ranges (text changed after they were set) are treated as
        # empty — see _outline_text_stale().
        if self._outline_text_stale():
            return None
        s, e = sel
        for r in self.blk.outline_ranges:
            try:
                w = float(r[2])
                if int(r[0]) <= s and int(r[1]) >= e and 0 <= w:
                    color = [int(x) for x in r[3]] if len(r) > 3 and r[3] is not None \
                        else list(self._srgb_tuple(self.fontformat.srgb))
                    return w, color
            except Exception:
                continue
        return None

    def set_selection_outline(self, width=None, srgb=None) -> bool:
        """Apply/replace a per-range outline for the effective selection.

        width=None with srgb set: update only the color of existing ranges
        overlapping the selection. Returns True if a selection was found and
        something was changed.
        """
        sel = self._effective_selection()
        if sel is None or self.blk is None:
            _debug("[stroke] idx=%d set_selection_outline NO-OP: sel=%s width=%s srgb=%s",
                        self.idx, sel, width, srgb)
            return False
        s, e = sel
        s = max(0, int(s))
        e = max(s, int(e))
        if e <= s:
            _debug("[stroke] idx=%d set_selection_outline NO-OP: empty sel (%d, %d)", self.idx, s, e)
            return False
        ranges = self.blk.outline_ranges if isinstance(getattr(self.blk, 'outline_ranges', None), list) else []
        if width is not None and width < 0:
            # Sentinel: remove ranges overlapping the selection, so the span
            # falls back to the block-level outline (undo of "no outline").
            if not ranges:
                return False
            keep = []
            changed = False
            for r in ranges:
                try:
                    rs, re_ = int(r[0]), int(r[1])
                except Exception:
                    keep.append(r)
                    continue
                if not (rs < e and re_ > s):
                    keep.append(r)
                    continue
                changed = True
                if rs < s:
                    keep.append([rs, s, r[2], r[3]])
                if re_ > e:
                    keep.append([e, re_, r[2], r[3]])
            if changed:
                keep.sort(key=lambda r: (int(r[0]), int(r[1])))
                self.blk.outline_ranges = keep
                self._save_outline_snapshot()
                _debug("[stroke] idx=%d set_selection_outline REMOVE (width<0) sel=(%d, %d): %s -> %s",
                            self.idx, s, e, ranges, keep)
            return changed
        if width is None:
            if srgb is None:
                return False
            changed = False
            for r in ranges:
                try:
                    if int(r[0]) < e and int(r[1]) > s:
                        r[3] = [int(x) for x in srgb]
                        changed = True
                except Exception:
                    continue
            if changed:
                self._save_outline_snapshot()
                _debug("[stroke] idx=%d set_selection_outline COLOR sel=(%d, %d) srgb=%s: -> %s",
                            self.idx, s, e, srgb, self.blk.outline_ranges)
            return changed
        color = [int(x) for x in srgb] if srgb is not None \
            else list(self._srgb_tuple(self.fontformat.srgb))
        # Keep old ranges that do NOT overlap the selection untouched; for
        # overlapping ones keep only the non-overlapping sub-ranges; then
        # append the new range. (A whole-block replace would wipe out
        # previously set ranges outside the selection.)
        keep = []
        for r in ranges:
            try:
                rs, re_ = int(r[0]), int(r[1])
            except Exception:
                keep.append(r)
                continue
            if re_ <= s or rs >= e:
                keep.append(r)
                continue
            if rs < s:
                keep.append([rs, s, r[2], r[3]])
            if re_ > e:
                keep.append([e, re_, r[2], r[3]])
        keep.append([s, e, float(width), color])
        keep.sort(key=lambda r: (int(r[0]), int(r[1])))
        self.blk.outline_ranges = keep
        self._save_outline_snapshot()
        _debug("[stroke] idx=%d set_selection_outline SET sel=(%d, %d) width=%s color=%s: %s -> %s",
                    self.idx, s, e, width, color, ranges, keep)
        return True

    def setStrokeColor(self, scolor: Union[QColor, Tuple[int, int, int]],
                       set_selected: bool = False, restore_cursor: bool = False, **kwargs) -> None:
        color = scolor if isinstance(scolor, QColor) else QColor(*[int(c) for c in scolor])
        if set_selected:
            if not self.set_selection_outline(
                    srgb=[color.red(), color.green(), color.blue()]):
                # No effective selection (or no overlapping range) — no-op
                # for ANY value. Never fall back to the block-level scalar:
                # the value was meant for the selection only (undo/redo
                # included).
                _debug("[stroke] idx=%d setStrokeColor -> selection no-op (no effective selection)",
                            self.idx)
                return
            _debug("[stroke] idx=%d setStrokeColor -> SELECTION path; block srgb stays %s",
                        self.idx, list(self.fontformat.srgb))
            self.repaint_background()
            self.update()
            return
        _debug("[stroke] idx=%d setStrokeColor -> WHOLE-BLOCK path (set_selected=%s): srgb %s -> %s",
                       self.idx, set_selected, list(self.fontformat.srgb),
                       [color.red(), color.green(), color.blue()])
        self.stroke_qcolor = color
        self.fontformat.srgb = [color.red(), color.green(), color.blue()]
        self.repaint_background()
        self.update()

    def setStrokeWidth(self, stroke_width: float, padding: bool = True, repaint_background: bool = True,
                       restore_cursor: bool = False, set_selected: bool = False, **kwargs) -> None:
        if set_selected:
            if not self.set_selection_outline(width=stroke_width):
                # No effective selection (or nothing to change/remove) —
                # no-op for ANY value, including the remove-sentinel. Never
                # fall back to the block-level scalar: the value was meant
                # for the selection only (undo/redo included).
                _debug("[stroke] idx=%d setStrokeWidth(%s) -> selection no-op (no effective selection)",
                            self.idx, stroke_width)
                return
            # Per-range outline for the selection — the block scalar is
            # intentionally left untouched.
            _debug("[stroke] idx=%d setStrokeWidth(%s) -> SELECTION path; block scalar stays %s",
                        self.idx, stroke_width, self.fontformat.stroke_width)
            if padding:
                w = max(float(stroke_width), self.fontformat.stroke_width)
                if w > 0:
                    p = self.layout.max_font_size(to_px=True) * (w + 0.05) / 2
                    self.setPadding(p)
            if repaint_background:
                self.repaint_background()
            self.update()
            return
        if stroke_width < 0:
            # Negative width is not a valid whole-block stroke width (it is
            # only the remove-sentinel of the selection path).
            _debug("[stroke] idx=%d setStrokeWidth(%s) -> WHOLE-BLOCK no-op (negative width)",
                        self.idx, stroke_width)
            return

        _debug("[stroke] idx=%d setStrokeWidth(%s) -> WHOLE-BLOCK path (set_selected=%s): block stroke %s -> %s",
                       self.idx, stroke_width, set_selected,
                       self.fontformat.stroke_width, stroke_width)
        cursor, after_kwargs = self._before_set_ffmt(set_selected=False, restore_cursor=restore_cursor)

        self.fontformat.stroke_width = stroke_width
        if stroke_width > 0 and padding:
            p = self.layout.max_font_size(to_px=True) * (stroke_width + 0.05) / 2
            self.setPadding(p)

        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)
        if repaint_background:
            self.update()

    def setRelFontSize(self, value: float, repaint_background: bool = False, set_selected: bool = False, restore_cursor: bool = False, clip_size: bool = False, **kwargs):
        current = self.layout.max_font_size()
        if current < 1:
            current = self.document().defaultFont().pointSizeF()
        new_size = round(current * value, 2)
        self.setFontSize(new_size, repaint_background, set_selected, restore_cursor, clip_size, **kwargs)

    def scaleFontSizes(self, factor: float, repaint_background: bool = False):
        """Scale the font size of every character range by *factor*, preserving
        the relative differences between per-selection ranges (so auto font
        adjust does not flatten user-chosen sizes)."""
        if factor <= 0:
            return
        doc = self.document()
        base_pt = self.layout.max_font_size() if self.layout is not None else 0
        if base_pt <= 0:
            base_pt = doc.defaultFont().pointSizeF()
        if base_pt <= 0:
            return
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start, QTextCursor.MoveMode.MoveAnchor)
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.text():
                    sz = frag.charFormat().font().pointSizeF()
                    if sz <= 0:
                        sz = base_pt
                    new_sz = max(4.0, sz * factor)
                    if abs(new_sz - sz) > 1e-6:
                        fmt = QTextCharFormat()
                        fmt.setFontPointSize(new_sz)
                        cursor.setPosition(frag.position())
                        cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                        cursor.mergeCharFormat(fmt)
                it += 1
            block = block.next()
        df = doc.defaultFont()
        if df.pointSizeF() > 0:
            df.setPointSizeF(df.pointSizeF() * factor)
        doc.setDefaultFont(df)
        cursor.endEditBlock()
        self.layout.reLayoutEverything()
        if repaint_background:
            self.repaint_background()
            self.update()


    def setFontSize(self, value: float, repaint_background: bool = False, set_selected: bool = False, restore_cursor: bool = False, clip_size: bool = False, _is_auto_layout: bool = False, **kwargs):
        '''
        value should be point size
        '''
        # Update fontformat.font_size so it persists when saving
        # But only if NOT called from auto-layout (which should not overwrite user's choice)
        if self.fontformat is not None:
            if not _is_auto_layout:
                source = "user"
                self.font_size_mgr.set(value, source=source)
                self._user_font_size = pt2px(value)  # Save user's choice
                caller = inspect.stack()[1].function if len(inspect.stack()) > 1 else '?'
                # User changed the font manually → disable auto-adjust so
                # shrink/grow do not override the user's choice. Internal
                # calls from FontAutoAdjuster (via _internal_font_change
                # guard in _font_adjuster_change_size) skip this.
                adj = getattr(self, 'font_adjuster', None)
                if adj is not None and not adj._internal_font_change:
                    self._auto_font_adjust = False
                elif adj is None:
                    self._auto_font_adjust = False
                if _is_log_target(self.blk):
                    LOGGER.debug("[FONTSIZE] TEXTITEM setFontSize: idx=%d input_pt=%.1f -> font_size_px=%.1f _auto_font_adjust=%s caller=%s",
                        self.idx, value, pt2px(value), self._auto_font_adjust, caller)

        cursor, after_kwargs = self._before_set_ffmt(set_selected=set_selected, restore_cursor=restore_cursor)
        self.layout.relayout_on_changed = False
        if self.fontformat.stroke_width != 0:
            repaint_background = True
        if repaint_background:
            fs = pt2px(max(self.layout.max_font_size(), value))
            self.layout.relayout_on_changed = False
            if self.fontformat.stroke_width > 0:
                self.setPadding(fs * (self.fontformat.stroke_width + 0.05) / 2)
            self.layout.relayout_on_changed = True
        cfmt = QTextCharFormat()
        cfmt.setFontPointSize(value)
        self.set_cursor_cfmt(cursor, cfmt, True)
        self.layout.relayout_on_changed = True
        self.layout.reLayoutEverything()
        if clip_size:
            self.squeezeBoundingRect(cond_on_alignment=True)

        self._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)

    def setAlignment(self, value, restore_cursor=False, repaint_background=True, *args, **kwargs):
        cursor, after_kwargs = self._before_set_ffmt(set_selected=False, restore_cursor=restore_cursor)
        if isinstance(value, int):
            qt_align_flag = [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignCenter, Qt.AlignmentFlag.AlignRight][value]
        doc = self.document()
        op = doc.defaultTextOption()
        op.setAlignment(qt_align_flag)
        doc.setDefaultTextOption(op)
        if repaint_background:
            self.repaint_background()
            self.update()
        self.fontformat.alignment = value
        self._after_set_ffmt(cursor, repaint_background=False, restore_cursor=restore_cursor, **after_kwargs)

    def get_char_fmts(self) -> List[QTextCharFormat]:
        cursor = self.textCursor()
        
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        char_fmts = []
        while True:
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
            cursor.clearSelection()
            char_fmts.append(cursor.charFormat())
            if cursor.atEnd():
                break
        return char_fmts

    def setShadow(self, fmt: FontFormat, repaint=True):
        self.fontformat.shadow_radius = fmt.shadow_radius
        self.fontformat.shadow_strength = fmt.shadow_strength
        self.fontformat.shadow_color = fmt.shadow_color
        self.fontformat.shadow_offset = fmt.shadow_offset
        if self.fontformat.shadow_radius > 0:
            self.setPadding(self.layout.max_font_size(to_px=True))
        if repaint:
            self.repaint_background()

    def setBGAttribute(self, attr_name: str, value, repaint=True):
        setattr(self.fontformat, attr_name, value)
        if repaint:
            self.repaint_background()
            self.update()

    def setGradientAttribute(self, attr_name: str, value):
        self.old_ffmt_values = {}
        self.old_ffmt_values[attr_name] = self.fontformat[attr_name]
        setattr(self.fontformat, attr_name, value)
        self.setGradientEnabled(self.fontformat.gradient_enabled)
        self.old_ffmt_values = None

    def setOpacity(self, opacity: float):
        super().setOpacity(opacity)
        self.fontformat.opacity = opacity

    def setPlainTextAndKeepUndoStack(self, text: str):
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)

    def squeezeBoundingRect(self, cond_on_alignment: bool = False, repaint=True):
        mh, mw = self.layout.minSize()
        if mh == 0 or mw == 0:
            return
        br = self.absBoundingRect(qrect=True)
        br_w, br_h = br.width(), br.height()

        if self.fontformat.vertical:
            if cond_on_alignment:
                mh = br.height()
        else:
            if cond_on_alignment:
                mw = br.width()

        if np.abs(br_w - mw) > 0.001 or np.abs(br_h - mh) > 0.001:
            P = self.padding() * 2
            mh += P
            mw += P
            self.set_size(mw, mh, set_layout_maxsize=True, set_blk_size=True)
            if self.under_ctrl:
                self.doc_size_changed.emit(self.idx)
            if repaint:
                self.repaint_background()

    def scene_scale_factor(self):
        scale = 1
        if hasattr(self.scene(), 'scale_factor'):
            scale = self.scene().scale_factor
        return scale
            
    def set_size(self, w: float, h: float, set_layout_maxsize=False, set_blk_size=True, auto_font_adjust=True):
        '''
        rotation invariant
        '''

        if set_layout_maxsize:
            self.layout.setMaxSize(w, h)

        old_w = self._display_rect.width()
        old_h = self._display_rect.height()
        old_w_changed = abs(old_w - w) > 0.5
        old_h_changed = abs(old_h - h) > 0.5

        oc = self.sceneBoundingRect().center()
        self._display_rect.setWidth(w)
        self._display_rect.setHeight(h)
        self.setCenterTransform()
        pos_shift = oc - self.sceneBoundingRect().center()
        pos_shift = pos_shift / self.scene_scale_factor()
        
        align_c = align_tl = align_tr = False
        if self.fontformat.vertical:
            align_tr = True
        else:
            alignment = self.fontformat.alignment
            if alignment == TextAlignment.Left:
                align_tl = True
            elif alignment == TextAlignment.Right:
                align_tr = True
            else:
                align_c = True

        if align_c:
            pass
        else:
            dw, dh = (w - old_w) / 2, (h - old_h) / 2
            if align_tr:
                dw = -dw
            rad = -np.deg2rad(self.rotation())
            c, s = np.cos(rad), np.sin(rad)
            dx = c * dw + s * dh
            dy = -s * dw + c * dh
            pos_shift = pos_shift + QPointF(dx, dy)

        self.setPos(self.pos() + pos_shift)
        if self.blk is not None and set_blk_size:
            self.blk._bounding_rect = self.absBoundingRect()

        # Auto font-adjust for plain (non-flow) blocks after resize.
        # TextLayoutManager calls set_size(..., auto_font_adjust=False) during
        # binary search — that flag suppresses shrink/grow here.
        if (auto_font_adjust
                and self._fully_initialized
                and self._auto_font_adjust
                and (old_w_changed or old_h_changed)
                and type(self).__name__ != 'FlowTextBlkItem'):
            self._auto_adjust_font(target_w=w, target_h=h)


# Import alias so other modules can use FlowTextBlkItem as TextBlkItem
# This is intentionally at the bottom to avoid circular imports.
try:
    from .flow_textitem import FlowTextBlkItem  # noqa: F401
except Exception:
    pass
