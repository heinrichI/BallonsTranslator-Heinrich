from qtpy.QtCore import Signal, Qt, QPointF, QSize, QLineF, QDateTime, QRectF, QPoint
from qtpy.QtGui import QPen, QColor, QCursor, QPainter, QPixmap, QBrush, QFontMetrics, QImage
try:
    from qtpy.QtWidgets import QUndoCommand
except:
    from qtpy.QtGui import QUndoCommand

from typing import Union, Tuple, List
import numpy as np
from utils.logger import logger

from .image_edit import ImageEditMode, PixmapItem, DrawingLayer, StrokeImgItem
from .canvas import Canvas, TextBlkItem
from .textedit_area import TransPairWidget
from utils.config import pcfg

class StrokeItemUndoCommand(QUndoCommand):
    def __init__(self, target_layer: DrawingLayer, rect: Tuple[int], qimg: QImage, erasing=False):
        super().__init__()
        self.qimg = qimg
        self.x = rect[0]
        self.y = rect[1]
        self.target_layer = target_layer
        self.key = str(QDateTime.currentMSecsSinceEpoch())
        if erasing:
            self.compose_mode = QPainter.CompositionMode.CompositionMode_DestinationOut
        else:
            self.compose_mode = QPainter.CompositionMode.CompositionMode_SourceOver
        
    def undo(self):
        if self.qimg is not None:
            self.target_layer.removeQImage(self.key)
            self.target_layer.update()

    def redo(self):
        if self.qimg is not None:
            self.target_layer.addQImage(self.x, self.y, self.qimg, self.compose_mode, self.key)
            self.target_layer.scene().update()


class InpaintUndoCommand(QUndoCommand):
    def __init__(self, canvas: Canvas, inpainted: np.ndarray, mask: np.ndarray, inpaint_rect: List[int], merge_existing_mask=False):
        super().__init__()
        self.canvas = canvas
        img_array = self.canvas.imgtrans_proj.inpainted_array
        mask_array = self.canvas.imgtrans_proj.mask_array
        img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        self.undo_img = np.copy(img_view)
        self.undo_mask = np.copy(mask_view)
        self.redo_img = inpainted
        if merge_existing_mask:
            self.redo_mask = np.bitwise_or(mask, mask_view)
        else:
            self.redo_mask = mask
        self.inpaint_rect = inpaint_rect

    def redo(self) -> None:
        inpaint_rect = self.inpaint_rect
        img_array = self.canvas.imgtrans_proj.inpainted_array
        mask_array = self.canvas.imgtrans_proj.mask_array
        img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        img_view[:] = self.redo_img
        mask_view[:] = self.redo_mask
        self.canvas.updateLayers()

    def undo(self) -> None:
        inpaint_rect = self.inpaint_rect
        img_array = self.canvas.imgtrans_proj.inpainted_array
        mask_array = self.canvas.imgtrans_proj.mask_array
        img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
        img_view[:] = self.undo_img
        mask_view[:] = self.undo_mask
        self.canvas.updateLayers()


class EmptyCommand(QUndoCommand):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
    

class RunBlkTransCommand(QUndoCommand):
    def __init__(self, canvas: Canvas, blkitems: List[TextBlkItem], transpairw_list: List[TransPairWidget], mode: int, st_manager=None):
        super().__init__()

        self.empty_command = None
        if mode > 1:
            self.empty_command = EmptyCommand()
            canvas.push_draw_command(self.empty_command)

        self.op_counter = -1
        self.blkitems = blkitems
        self.transpairw_list = transpairw_list

        # Per-block font-size auto-adjustment data
        self.layout_data = []

        if mode < 3:
            for blkitem, transpairw in zip(self.blkitems, self.transpairw_list):
                trs = blkitem.blk.translation if mode != 0 else ''

                # Check whether auto font-size fitting should be applied
                needs_layout = (
                    mode != 0
                    and st_manager is not None
                    # and st_manager.auto_textlayout_flag
                    and pcfg.let_fntsize_flag == 0
                    and pcfg.let_autolayout_flag
                    and not blkitem.blk.vertical
                    and bool(trs.strip())
                )

                if needs_layout:
                    # ---- save old state ----
                    old_html = blkitem.toHtml()
                    old_font_size = blkitem.font().pointSizeF()
                    if old_font_size < 1:
                        old_font_size = 12.0
                    old_rect = blkitem.absBoundingRect(qrect=True)
                    old_w = old_rect.width()
                    old_h = old_rect.height()

                    # ---- target dimensions (same logic as layout_textblk auto-mode) ----
                    target_w = old_w
                    target_h = old_h
                    blk_br = blkitem.blk.bounding_rect()
                    if len(blk_br) >= 4:
                        target_w = max(target_w, blk_br[2])
                        target_h = max(target_h, blk_br[3])

                    layout_ok = False
                    if target_w >= 2 and target_h >= 2:
                        optimal_size = st_manager._find_best_font_size(
                            blkitem, trs, target_w, target_h, old_font_size
                        )

                        block_w = target_w
                        # blkitem.setFont(pcfg.global_fontformat)
                        blkitem.setLetterSpacing(st_manager.formatpanel.global_format.letter_spacing)
                        blkitem.setFontFamily(st_manager.formatpanel.global_format.font_family)
                        blkitem.setFontSize(optimal_size)
                        blkitem.setPlainText(trs)
                        blkitem.set_size(block_w, target_h, set_layout_maxsize=True)
                        # Restore auto-adjust for shrink safety net, but disable grow
                        # since binary search already found the optimal size.
                        # Grow would increase font past boundaries causing overflow.
                        blkitem._auto_font_adjust = True
                        saved_grow = blkitem.font_adjuster._auto_grow_enabled
                        blkitem.font_adjuster._auto_grow_enabled = False
                        blkitem._update_flow_layout()
                        blkitem.font_adjuster._auto_grow_enabled = saved_grow

                        # Post-layout validation: if text still exceeds target height
                        # after the shrink pass, apply additional shrink iterations.
                        # This handles cases where binary search optimal size doesn't
                        # perfectly match the final layout (large fonts, hyphenation).
                        layout = blkitem.layout
                        if layout is not None:
                            cur_shrink_h = getattr(layout, 'shrink_height', 0)
                            if cur_shrink_h > target_h and target_h > 0:
                                doc_margin = blkitem.document().documentMargin()
                                for _ in range(10):
                                    cur_shrink_h = getattr(layout, 'shrink_height', 0)
                                    if cur_shrink_h <= target_h or cur_shrink_h <= 0:
                                        break
                                    factor = min(0.92, (target_h / cur_shrink_h) * 0.95)
                                    if factor >= 1.0:
                                        break
                                    blkitem.font_adjuster._internal_font_change = True
                                    try:
                                        blkitem.font_adjuster._change_font_size(factor)
                                    finally:
                                        blkitem.font_adjuster._internal_font_change = False
                                    layout.available_height = target_h
                                    layout.max_height = target_h + doc_margin * 2
                                    layout.reLayout()
                                optimal_size = blkitem.font().pointSizeF()
                                blkitem.font_adjuster._sync_font()

                        # transpairw uses undo-safe method (its own undo stack)
                        transpairw.e_trans.setPlainTextAndKeepUndoStack(trs)

                        # ---- save new state ----
                        self.layout_data.append({
                            'old_html': old_html,
                            'old_font_size': old_font_size,
                            'old_w': old_w,
                            'old_h': old_h,
                            'new_html': blkitem.toHtml(),
                            'new_font_size': optimal_size,
                            'new_w': block_w,
                            'new_h': target_h,
                        })
                        layout_ok = True

                    if not layout_ok:
                        # target too small — fall back to plain text
                        transpairw.e_trans.setPlainTextAndKeepUndoStack(trs)
                        blkitem.setPlainTextAndKeepUndoStack(trs)
                        self.layout_data.append(None)
                else:
                    # no layout — original behaviour
                    if mode != 0:
                        transpairw.e_trans.setPlainTextAndKeepUndoStack(trs)
                        blkitem.setPlainTextAndKeepUndoStack(trs)
                    self.layout_data.append(None)

                blkitem.blk.rich_text = ''
                if mode >= 0:
                    transpairw.e_source.setPlainTextAndKeepUndoStack(blkitem.blk.get_text())

        self.canvas = canvas
        self.mode = mode
        if mode > 1:
            self.undo_img_list = []
            self.undo_mask_list = []
            self.redo_img_list = []
            self.redo_mask_list = []
            self.inpaint_rect_lst = []
            img_array = self.canvas.imgtrans_proj.inpainted_array
            mask_array = self.canvas.imgtrans_proj.mask_array
            self.num_inpainted = 0
            for item in self.blkitems:
                inpainted_dict = item.blk.region_inpaint_dict
                item.blk.region_inpaint_dict = None
                if inpainted_dict is None:
                    self.undo_img_list.append(None)
                    self.undo_mask_list.append(None)
                    self.redo_mask_list.append(None)
                    self.redo_img_list.append(None)
                    self.inpaint_rect_lst.append(None)
                else:
                    inpaint_rect = inpainted_dict['inpaint_rect']
                    img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                    mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                    self.undo_img_list.append(np.copy(img_view))
                    self.undo_mask_list.append(np.copy(mask_view))
                    self.redo_img_list.append(inpainted_dict['inpainted'])
                    self.redo_mask_list.append(inpainted_dict['mask'])
                    self.inpaint_rect_lst.append(inpaint_rect)
                    self.num_inpainted += 1

    def redo(self) -> None:

        if self.empty_command is not None:
            self.empty_command.redo()

        if self.mode > 1 and self.num_inpainted > 0:
            img_array = self.canvas.imgtrans_proj.inpainted_array
            mask_array = self.canvas.imgtrans_proj.mask_array
            for inpaint_rect, redo_img, redo_mask in zip(self.inpaint_rect_lst, self.redo_img_list, self.redo_mask_list):
                if inpaint_rect is None:
                    continue
                img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                img_view[:] = redo_img
                mask_view[:] = redo_mask
            self.canvas.updateLayers()

        if self.op_counter < 0:
            self.op_counter += 1
            return

        if self.mode < 3:
            for i, (blkitem, transpairw) in enumerate(zip(self.blkitems, self.transpairw_list)):
                if self.mode != 0:
                    transpairw.e_trans.redo()
                    ld = self.layout_data[i] if i < len(self.layout_data) else None
                    if ld is not None:
                        blkitem.setFontSize(ld['new_font_size'])
                        blkitem.setHtml(ld['new_html'])
                        blkitem.set_size(ld['new_w'], ld['new_h'], set_layout_maxsize=True)
                    else:
                        blkitem.redo()
                if self.mode >= 0:
                    transpairw.e_source.redo()

    def undo(self) -> None:

        if self.empty_command is not None:
            self.empty_command.undo()

        if self.mode > 1 and self.num_inpainted > 0:
            img_array = self.canvas.imgtrans_proj.inpainted_array
            mask_array = self.canvas.imgtrans_proj.mask_array
            for inpaint_rect, undo_img, undo_mask in zip(self.inpaint_rect_lst, self.undo_img_list, self.undo_mask_list):
                if inpaint_rect is None:
                    continue
                img_view = img_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                mask_view = mask_array[inpaint_rect[1]: inpaint_rect[3], inpaint_rect[0]: inpaint_rect[2]]
                img_view[:] = undo_img
                mask_view[:] = undo_mask
            self.canvas.updateLayers()

        if self.mode < 3:
            for i, (blkitem, transpairw) in enumerate(zip(self.blkitems, self.transpairw_list)):
                if self.mode != 0:
                    transpairw.e_trans.undo()
                    ld = self.layout_data[i] if i < len(self.layout_data) else None
                    if ld is not None:
                        blkitem.setFontSize(ld['old_font_size'])
                        blkitem.setHtml(ld['old_html'])
                        blkitem.set_size(ld['old_w'], ld['old_h'], set_layout_maxsize=True)
                    else:
                        blkitem.undo()
                if self.mode >= 0:
                    transpairw.e_source.undo()