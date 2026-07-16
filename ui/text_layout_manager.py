"""
TextLayoutManager — извлечённый из SceneTextManager.

Содержит чистую бизнес-логику layout текста:
- Автоматический подбор размера шрифта (binary search)
- Mask-based layout
- Восстановление форматирования символов

НЕ зависит от View (TransPairWidget, Canvas и т.д.).
"""

import logging
from typing import List, Tuple, Optional

import numpy as np
from qtpy.QtGui import QFont, QFontMetricsF, QTextCharFormat

from utils.logger import logger as LOGGER
from utils.text_processing import seg_text, is_cjk
from utils.text_layout import layout_text
from utils.imgproc_utils import extract_ballon_region

QUIET_UI = True

def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)


# ── Constants ────────────────────────────────────────────────

LAYOUT_MIN_FONT_PT = 8.0
LAYOUT_BEST_FONT_SIZE_ITERATION = 30
LAYOUT_FIT_FILL_W_RATIO = 1
LAYOUT_FIT_FILL_H_RATIO = 0.9
LAYOUT_BLOCK_SHRINK_W = 1.0


# ── Helper functions ─────────────────────────────────────────

def get_text_size(fm: QFontMetricsF, text: str) -> Tuple[int, int]:
    """Calculate text width and height."""
    brt = fm.tightBoundingRect(text)
    br = fm.boundingRect(text)
    return int(np.ceil(fm.horizontalAdvance(text))), int(np.ceil(brt.height()))


def get_words_length_list(fm: QFontMetricsF, words: List[str]) -> List[int]:
    """Calculate width of each word."""
    lengths = []
    for word in words:
        length = fm.horizontalAdvance(word)
        lengths.append(int(np.ceil(length)))
    return lengths


# ── TextLayoutManager ───────────────────────────────────────

class TextLayoutManager:
    """
    Чистая бизнес-логика layout текста в блоках.
    
    Не зависит от View — только от Model (TextBlock) и утилит.
    Вызывающий код (Presenter) отвечает за обновление View.
    """
    
    def __init__(self, pcfg):
        """
        Args:
            pcfg: ProgramConfig — конфигурация программы
        """
        self.pcfg = pcfg
        self.auto_textlayout_flag = False
    
    def layout_textblk(self, blkitem, text: str = None, mask: np.ndarray = None,
                       bounding_rect: List = None, region_rect: List = None,
                       img_array: np.ndarray = None) -> Optional[str]:
        """
        Auto text layout for a text block.
        
        Args:
            blkitem: TextBlkItem — текстовый блок (View)
            text: Текст для layout (None = из blkitem)
            mask: Маска региона (None = вычислить автоматически)
            bounding_rect: Границы блока [x, y, w, h]
            region_rect: Регион для layout
            img_array: Изображение страницы
            
        Returns:
            str: Новый текст после layout или None если layout не удался
        """
        if img_array is None:
            return None
        
        im_h, im_w = img_array.shape[:2]
        
        src_is_cjk = is_cjk(self.pcfg.module.translate_source)
        tgt_is_cjk = is_cjk(self.pcfg.module.translate_target)
        
        # Disable for vertical writing
        if blkitem.blk.vertical:
            return None
        
        old_br = blkitem.absBoundingRect(qrect=True)
        old_br = [old_br.x(), old_br.y(), old_br.width(), old_br.height()]
        if old_br[2] < 1:
            return None
        
        restore_charfmts = False
        if text is None:
            text = blkitem.toPlainText()
            restore_charfmts = True
        
        if not text.strip():
            return None
        
        # =====================================================
        # AUTO MODE: binary search for max font fitting in block
        # =====================================================
        if self.auto_textlayout_flag and self.pcfg.let_fntsize_flag == 0 and self.pcfg.let_autolayout_flag:
            return self._auto_layout(blkitem, text, img_array, old_br, restore_charfmts)
        
        # =====================================================
        # ORIGINAL MODE: mask-based layout with global font size
        # =====================================================
        return self._mask_layout(blkitem, text, img_array, old_br, 
                                 src_is_cjk, tgt_is_cjk, mask, bounding_rect, 
                                 region_rect, restore_charfmts)
    
    def _auto_layout(self, blkitem, text: str, img_array: np.ndarray,
                     old_br: List, restore_charfmts: bool) -> Optional[str]:
        """
        AUTO MODE: binary search for max font size fitting in block.
        
        Returns:
            str: Text after layout or None
        """
        orig_rect = blkitem.absBoundingRect(qrect=True)
        target_w = orig_rect.width()
        target_h = orig_rect.height()
        
        blk_br = blkitem.blk.bounding_rect()
        if len(blk_br) >= 4:
            target_w = max(target_w, blk_br[2])
            target_h = max(target_h, blk_br[3])
        
        if target_w < 2 or target_h < 2:
            LOGGER.warning(f"[layout_textblk] idx={blkitem.idx} target too small: "
                           f"{target_w:.1f}x{target_h:.1f}")
            return None
        
        if restore_charfmts:
            char_fmts = blkitem.get_char_fmts()
        
        original_size = blkitem.font().pointSizeF()
        if original_size < 1:
            original_size = 12.0
        
        optimal_size = self._find_best_font_size(
            blkitem, text, target_w, target_h, original_size
        )
        
        block_w = target_w * LAYOUT_BLOCK_SHRINK_W
        blkitem.setFontSize(optimal_size)
        blkitem.setPlainText(text)
        blkitem.set_size(block_w, target_h, set_layout_maxsize=True, auto_font_adjust=False)
        
        if restore_charfmts:
            for cf in char_fmts:
                cf.setFontPointSize(optimal_size)
            self._restore_charfmts(blkitem, text, text, char_fmts)
        
        # Restore auto-adjust and run one shrink pass
        blkitem._auto_font_adjust = True
        saved_grow = blkitem.font_adjuster._auto_grow_enabled
        blkitem.font_adjuster._auto_grow_enabled = False
        blkitem._update_flow_layout()
        blkitem.font_adjuster._auto_grow_enabled = saved_grow
        
        return text
    
    def _mask_layout(self, blkitem, text: str, img_array: np.ndarray,
                     old_br: List, src_is_cjk: bool, tgt_is_cjk: bool,
                     mask: Optional[np.ndarray], bounding_rect: Optional[List],
                     region_rect: Optional[List], restore_charfmts: bool) -> Optional[str]:
        """
        ORIGINAL MODE: mask-based layout with global font size.
        
        Returns:
            str: New text after layout or None
        """
        im_h, im_w = img_array.shape[:2]
        
        blk_font = blkitem.font()
        fmt = blkitem.get_fontformat()
        blk_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, fmt.letter_spacing * 100)
        text_size_func = lambda text: get_text_size(QFontMetricsF(blk_font), text)
        
        if mask is None:
            bounding_rect = blkitem.absBoundingRect(max_h=im_h, max_w=im_w)
            if bounding_rect[2] <= 0 or bounding_rect[3] <= 0:
                return text
            
            if tgt_is_cjk:
                max_enlarge_ratio = 2.5
            else:
                max_enlarge_ratio = 3
            enlarge_ratio = min(
                max(bounding_rect[2] / bounding_rect[3], bounding_rect[3] / bounding_rect[2]) * 1.5,
                max_enlarge_ratio
            )
            mask, ballon_area, mask_xyxy, region_rect = extract_ballon_region(
                img_array, bounding_rect, enlarge_ratio=enlarge_ratio, cal_region_rect=True
            )
        else:
            mask_xyxy = [bounding_rect[0], bounding_rect[1], 
                         bounding_rect[0] + bounding_rect[2], 
                         bounding_rect[1] + bounding_rect[3]]
        
        words, delimiter = seg_text(text, self.pcfg.module.translate_target)
        if len(words) < 1:
            return None
        
        wl_list = get_words_length_list(QFontMetricsF(blk_font), words)
        text_w, text_h = text_size_func(text)
        text_area = text_w * text_h
        
        if tgt_is_cjk:
            line_height = int(round(fmt.line_spacing * text_size_func('X木')[1]))
        else:
            line_height = int(round(fmt.line_spacing * text_size_func('X')[1]))
        delimiter_len = text_size_func(delimiter)[0]
        
        ref_src_lines = False
        if not blkitem.blk.src_is_vertical:
            ref_src_lines = blkitem.blk.line_coord_valid(old_br)
        
        max_central_width = np.inf
        if fmt.alignment == 1:
            if len(blkitem.blk) > 0:
                centroid = blkitem.blk.center().astype(np.int64).tolist()
                centroid[0] -= mask_xyxy[0]
                centroid[1] -= mask_xyxy[1]
            else:
                centroid = [bounding_rect[2] // 2, bounding_rect[3] // 2]
        else:
            max_central_width = np.inf
            centroid = [0, 0]
            abs_centroid = [bounding_rect[0], bounding_rect[1]]
            if len(blkitem.blk) > 0:
                blkitem.blk.lines[0]
                abs_centroid = blkitem.blk.lines[0][0]
                centroid[0] = int(abs_centroid[0] - mask_xyxy[0])
                centroid[1] = int(abs_centroid[1] - mask_xyxy[1])
        
        new_text, xywh, start_from_top, adjust_xy = layout_text(
            blkitem.blk,
            mask,
            mask_xyxy,
            centroid,
            words,
            wl_list,
            delimiter,
            delimiter_len,
            line_height,
            0,
            max_central_width,
            src_is_cjk=src_is_cjk,
            tgt_is_cjk=tgt_is_cjk,
            ref_src_lines=ref_src_lines
        )
        
        if restore_charfmts:
            char_fmts = blkitem.get_char_fmts()
        
        ffmt = QFontMetricsF(blk_font)
        maxw = max([ffmt.horizontalAdvance(t) for t in new_text.split('\n')])
        blkitem.set_size(maxw * 1.5, xywh[3], set_layout_maxsize=True)
        blkitem.setPlainText(new_text)
        
        if restore_charfmts:
            self._restore_charfmts(blkitem, text, new_text, char_fmts)
        
        blkitem.squeezeBoundingRect()
        return new_text
    
    def _find_best_font_size(self, blkitem, text: str,
                              target_w: float, target_h: float,
                              original_size: float) -> float:
        """
        Binary-search the largest point size so that text fits within
        target_w × target_h.
        """
        lo = max(LAYOUT_MIN_FONT_PT, 4.0)
        hi = max(original_size * 3.0, 120.0)
        best = lo
        
        # Apply fill ratio
        target_w = target_w * LAYOUT_BLOCK_SHRINK_W * LAYOUT_FIT_FILL_W_RATIO
        target_h = target_h * LAYOUT_FIT_FILL_H_RATIO
        
        # Suppress visual repainting
        saved_repaint = getattr(blkitem, 'repaint_on_changed', None)
        if saved_repaint is not None:
            blkitem.repaint_on_changed = False
        
        # Block outgoing signals
        blkitem.blockSignals(True)
        
        try:
            iteration = 0
            orig_avail_h = blkitem.layout.available_height if hasattr(blkitem.layout, 'available_height') else None
            orig_max_h = blkitem.layout.max_height if hasattr(blkitem.layout, 'max_height') else None
            
            for iteration in range(LAYOUT_BEST_FONT_SIZE_ITERATION):
                if hi - lo < 0.1:
                    break
                mid = (lo + hi) / 2.0
                
                # Reset layout dimensions
                if orig_avail_h is not None:
                    blkitem.layout.available_height = orig_avail_h
                if orig_max_h is not None:
                    blkitem.layout.max_height = orig_max_h
                
                # Set font size and text
                blkitem.setFontSize(mid)
                blkitem.setPlainText(text)
                blkitem.set_size(target_w, target_h, set_layout_maxsize=True, auto_font_adjust=False)
                
                # Check if text fits
                doc_h = (blkitem.layout.shrink_height 
                        if hasattr(blkitem.layout, 'shrink_height') and blkitem.layout.shrink_height > 0 
                        else blkitem.document().size().height())
                fits = doc_h <= target_h
                
                if fits:
                    best = mid
                    lo = mid
                else:
                    hi = mid
        
        finally:
            blkitem.blockSignals(False)
            if saved_repaint is not None:
                blkitem.repaint_on_changed = saved_repaint
        
        return best
    
    def _restore_charfmts(self, blkitem, text: str, new_text: str, 
                          char_fmts: List[QTextCharFormat]):
        """Restore character formatting after text layout."""
        cursor = blkitem.textCursor()
        cpos = 0
        num_text = len(new_text)
        num_fmt = len(char_fmts)
        blkitem.layout.relayout_on_changed = False
        blkitem.repaint_on_changed = False
        
        if num_text >= num_fmt:
            for fmt_i in range(num_fmt):
                fmt = char_fmts[fmt_i]
                ori_char = text[fmt_i].strip()
                if ori_char == '':
                    continue
                else:
                    if cursor.atEnd():
                        break
                    matched = False
                    while cpos < num_text:
                        if new_text[cpos] == ori_char:
                            matched = True
                            break
                        cpos += 1
                    if matched:
                        cursor.clearSelection()
                        cursor.setPosition(cpos)
                        cursor.setPosition(cpos + 1, QTextCursor.MoveMode.KeepAnchor)
                        cursor.setCharFormat(fmt)
                        cursor.setBlockCharFormat(fmt)
                        cpos += 1
        
        blkitem.repaint_on_changed = True
        blkitem.layout.relayout_on_changed = True
        blkitem.layout.reLayout()
        blkitem.repaint_background()
