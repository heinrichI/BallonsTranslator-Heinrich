"""
FontAutoAdjuster — extracted from FlowTextBlkItem.

Handles iterative font shrink/grow to fit text within boundary control points.
Owns _auto_grow_enabled and _internal_font_change flags.
"""

import logging
from typing import Callable, List, Tuple

from qtpy.QtCore import QPointF

from .scene_textlayout import HorizontalTextDocumentLayout

MIN_FONT_SIZE_PT: float = 5.0
FONT_SHRINK_FACTOR: float = 0.9


class FontAutoAdjuster:
    """Iteratively adjusts font size so text fits within boundary control points.

    Args:
        layout: The HorizontalTextDocumentLayout instance.
        document: QTextDocument instance.
        log: Logging callback (msg: str, level: int = logging.DEBUG).
        change_font_size: Callable that applies a relative font size change.
            Signature: change_font_size(factor: float) -> None
            Must handle _internal_font_change guard internally.
        get_points: Callable returning (left_points, right_points) lists.
        sync_font: Callable invoked after font size changes to sync fontformat/blk.
    """

    def __init__(self, layout, document, log, change_font_size, get_points, sync_font):
        self._layout = layout
        self._document = document
        self._log = log
        self._change_font_size = change_font_size
        self._get_points = get_points
        self._sync_font = sync_font
        self._auto_grow_enabled: bool = True
        self._internal_font_change: bool = False

    def shrink(self) -> bool:
        """Iteratively reduce font size until text fits or reaches MIN_FONT_SIZE_PT.

        Uses control-points y-range as target height, NOT layout.available_height.
        Before each iteration, resets layout.available_height/max_height to target
        values because reLayout() expands them when text overflows.
        """
        layout = self._layout
        if layout is None:
            self._log("_auto_shrink_font: layout is None, SKIP")
            return False
        if not isinstance(layout, HorizontalTextDocumentLayout):
            self._log("_auto_shrink_font: not horizontal layout, SKIP")
            return False
        if not self._document.toPlainText().strip():
            self._log("_auto_shrink_font: empty text, SKIP")
            return False

        min_font = layout.max_font_size()
        if min_font <= MIN_FONT_SIZE_PT:
            self._log("_auto_shrink_font: min_font=%.1f <= MIN, SKIP" % min_font)
            return False

        left_pts, right_pts = self._get_points()
        if left_pts and right_pts:
            all_ys = [p.y() for p in left_pts] + [p.y() for p in right_pts]
            target_height = max(all_ys) - min(all_ys)
            all_xs = [p.x() for p in left_pts] + [p.x() for p in right_pts]
            target_width = max(all_xs) - min(all_xs)
        else:
            target_height = layout.available_height
            target_width = layout.available_width
        if target_height < 10:
            return False

        text_extent = layout.shrink_height
        text_width = layout.shrink_width
        self._log("=== _auto_shrink_font ===")
        self._log("  target_height=%.1f text_extent=%.1f target_width=%.1f text_width=%.1f" %
                     (target_height, text_extent, target_width, text_width))

        char_level_breaks = getattr(layout, '_has_char_level_breaks', False)
        height_overflow = text_extent > target_height
        width_overflow = text_width > target_width if target_width > 0 else False
        close_to_width = target_width > 0 and text_width > target_width * 0.85
        if not height_overflow and not width_overflow and not char_level_breaks and not close_to_width:
            self._log("  => no overflow and NOT close to width, NO SHRINK")
            return False

        applied = False
        doc_margin = self._document.documentMargin()
        for iteration in range(1, 21):
            if applied:
                layout.available_height = target_height
                layout.max_height = target_height + doc_margin * 2
                layout.reLayout()

            text_extent = layout.shrink_height
            text_width = layout.shrink_width
            self._log("  iter %d: text_extent=%.1f target_h=%.1f text_w=%.1f target_w=%.1f" %
                         (iteration, text_extent, target_height, text_width, target_width))

            height_ok = text_extent <= target_height
            width_ok = text_width <= target_width if target_width > 0 else True
            if height_ok and width_ok:
                self._log("  => text fits, STOP")
                break

            close_to_width = target_width > 0 and text_width > target_width * 0.85
            if close_to_width and text_width > 0:
                factor = min(FONT_SHRINK_FACTOR, (target_width / text_width) * 0.95)
            elif not height_ok and text_extent > 0:
                factor = min(FONT_SHRINK_FACTOR, (target_height / text_extent) * 0.95)
            else:
                factor = FONT_SHRINK_FACTOR
            if factor >= 1.0:
                break

            self._internal_font_change = True
            try:
                self._change_font_size(factor)
            finally:
                self._internal_font_change = False
            applied = True

            new_min = layout.max_font_size()
            if new_min <= MIN_FONT_SIZE_PT:
                break

        self._log("  _auto_shrink_font DONE, applied=%s" % applied)

        if applied:
            self._sync_font()

        return applied

    def grow(self) -> bool:
        """Iteratively increase font size until text fills ~90% of available height.

        Respects width constraints: does not grow when char-level breaks
        indicate font is at max width, and caps grow factor to prevent
        width overflow.
        """
        layout = self._layout
        if layout is None:
            self._log("_auto_grow_font: layout is None, SKIP")
            return False
        if not isinstance(layout, HorizontalTextDocumentLayout):
            self._log("_auto_grow_font: not horizontal layout, SKIP")
            return False
        if not self._document.toPlainText().strip():
            self._log("_auto_grow_font: empty text, SKIP")
            return False

        left_pts, right_pts = self._get_points()
        if left_pts and right_pts:
            all_ys = [p.y() for p in left_pts] + [p.y() for p in right_pts]
            target_height = max(all_ys) - min(all_ys)
            all_xs = [p.x() for p in left_pts] + [p.x() for p in right_pts]
            target_width = max(all_xs) - min(all_xs)
        else:
            target_height = layout.available_height
            target_width = layout.available_width
        if target_height < 10:
            self._log("_auto_grow_font: target_height=%.1f < 10, SKIP" % target_height)
            return False

        text_extent = layout.shrink_height
        text_width = layout.shrink_width
        if text_extent >= target_height * 0.70:
            self._log("  _auto_grow: text fills %.0f%% of height, SKIP" % (text_extent / target_height * 100))
            return False
        self._log("  _auto_grow: text_extent=%.1f target_h=%.1f text_w=%.1f target_w=%.1f" %
                     (text_extent, target_height, text_width, target_width))

        applied = False
        doc_margin = self._document.documentMargin()
        for iteration in range(20):
            layout.available_height = target_height
            layout.max_height = target_height + doc_margin * 2
            layout.reLayout()

            text_extent = layout.shrink_height
            text_width = layout.shrink_width
            width_ok = text_width <= target_width if target_width > 0 else True

            if not width_ok:
                self._log("  _auto_grow iter %d: width overflow %.1f>%.1f, STOP" %
                             (iteration, text_width, target_width))
                break

            height_ok = text_extent >= target_height * 0.90
            if height_ok:
                self._log("  _auto_grow iter %d: height=%.0f%%, STOP" %
                             (iteration, text_extent / target_height * 100))
                break

            height_factor = (target_height * 0.90) / max(text_extent, 1)
            if text_width > target_width and target_width > 0:
                width_factor = target_width / max(text_width, 1)
            else:
                width_factor = 1.08
            factor = min(1.08, height_factor, width_factor)

            self._internal_font_change = True
            try:
                self._change_font_size(factor)
            finally:
                self._internal_font_change = False
            applied = True

        if applied:
            self._sync_font()

        return applied
