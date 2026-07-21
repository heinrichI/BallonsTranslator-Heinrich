
from typing import List, Union, Tuple
import numpy as np
import copy

from qtpy.QtWidgets import QApplication, QWidget, QGraphicsItem
from qtpy.QtCore import QObject, QRectF, Qt, Signal, QPointF, QPoint
from qtpy.QtGui import QKeyEvent, QTextCursor, QFontMetricsF, QFont, QTextCharFormat, QClipboard, QColor
try:
    from qtpy.QtWidgets import QUndoCommand
except:
    from qtpy.QtGui import QUndoCommand

from .textitem import TextBlkItem, TextBlock
from .flow_textitem import FlowTextBlkItem
from .canvas import Canvas
from .textedit_area import TransTextEdit, SourceTextEdit, TransPairWidget, SelectTextMiniMenu, TextEditListScrollArea, QVBoxLayout, Widget
from utils.fontformat import FontFormat
from .textedit_commands import propagate_user_edit, TextEditCommand, ReshapeItemCommand, MoveBlkItemsCommand, AutoLayoutCommand, ApplyFontformatCommand, RotateItemCommand, TextItemEditCommand, TextEditCommand, PageReplaceOneCommand, PageReplaceAllCommand, MultiPasteCommand, ResetAngleCommand, SqueezeCommand
from .text_panel import FontFormatPanel
from utils.config import pcfg
from utils import shared
from utils.imgproc_utils import extract_ballon_region, rotate_polygons, get_block_mask
from utils.text_processing import seg_text, is_cjk
from utils.text_layout import layout_text

from utils.logger import logger as LOGGER

QUIET_UI = True  # Set to False for verbose UI debug logging

def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)

_LOG_TARGET = "BUT OF COURSE!"

from utils.spell_check_engine import get_spellcheck_engine
from .text_layout_manager import TextLayoutManager, get_text_size, get_words_length_list
from .overlap_resolver import OverlapResolver
from .transpair_wiring import TransPairWiring
from .block_manager import BlockManager
from .clipboard_manager import ClipboardManager
from .selection_manager import SelectionManager
from .event_bus import EventBus, Events

# Keep old constants for backward compatibility
LAYOUT_MIN_FONT_PT = 8.0
LAYOUT_BEST_FONT_SIZE_ITERATION = 30
LAYOUT_FIT_FILL_W_RATIO = 1
LAYOUT_FIT_FILL_H_RATIO = 0.9
LAYOUT_BLOCK_SHRINK_W = 1.0 

class CreateItemCommand(QUndoCommand):
    def __init__(self, blk_item: TextBlkItem, ctrl, parent=None):
        super().__init__(parent)
        self.blk_item = blk_item
        self.ctrl: SceneTextManager = ctrl
        self.op_count = -1
        self.ctrl.addTextBlock(self.blk_item)
        self.pairw = self.ctrl.pairwidget_list[self.blk_item.idx]
        self.ctrl.txtblkShapeControl.setBlkItem(self.blk_item)

    def redo(self):
        if self.op_count < 0:
            self.op_count += 1
            self.blk_item.setSelected(True)
            return
        self.ctrl.recoverTextblkItemList([self.blk_item], [self.pairw])

    def undo(self):
        self.ctrl.deleteTextblkItemList([self.blk_item], [self.pairw])


class EmptyCommand(QUndoCommand):
    def __init__(self, parent=None):
        super().__init__(parent=parent)


class DeleteBlkItemsCommand(QUndoCommand):
    def __init__(self, blk_list: List[TextBlkItem], mode: int, ctrl, parent=None):
        super().__init__(parent)
        self.op_counter = 0
        self.blk_list = []
        self.pwidget_list: List[TransPairWidget] = []
        self.ctrl: SceneTextManager = ctrl
        self.sw = self.ctrl.canvas.search_widget
        self.canvas: Canvas = ctrl.canvas
        self.mode = mode

        self.undo_img_list = []
        self.redo_img_list = []
        self.inpaint_rect_lst = []
        self.mask_pnts = []
        img_array = self.canvas.get_inpainted_array()
        mask_array = self.canvas.get_mask_array()
        original_array = self.canvas.get_image_array()

        self.search_rstedit_list: List[SourceTextEdit] = []
        self.search_counter_list = []
        self.highlighter_list = []
        self.old_counter_sum = self.sw.counter_sum
        self.sw_changed = False

        blk_list.sort(key=lambda blk: blk.idx)
        
        for blkitem in blk_list:
            if not isinstance(blkitem, TextBlkItem):
                continue
            self.blk_list.append(blkitem)
            pw: TransPairWidget = ctrl.pairwidget_list[blkitem.idx]
            self.pwidget_list.append(pw)

            if mode == 1:
                is_empty = False
                msk, xyxy = get_block_mask(blkitem.absBoundingRect(), mask_array, blkitem.rotation())
                if msk is None:
                    is_empty = True
                if is_empty:
                    self.undo_img_list.append(None)
                    self.redo_img_list.append(None)
                    self.inpaint_rect_lst.append(None)
                    self.mask_pnts.append(None)
                else:
                    x1, y1, x2, y2 = xyxy
                    self.mask_pnts.append(np.where(msk))
                    self.undo_img_list.append(np.copy(img_array[y1: y2, x1: x2]))
                    self.redo_img_list.append(np.copy(original_array[y1: y2, x1: x2]))
                    self.inpaint_rect_lst.append([x1, y1, x2, y2])

            rst_idx = self.sw.get_result_edit_index(pw.e_trans)
            if rst_idx != -1:
                self.sw_changed = True
                highlighter = self.sw.highlighter_list.pop(rst_idx)
                counter = self.sw.search_counter_list.pop(rst_idx)
                self.sw.counter_sum -= counter
                if self.sw.current_edit == pw.e_trans:
                    highlighter.set_current_span(-1, -1)
                self.search_rstedit_list.append(self.sw.search_rstedit_list.pop(rst_idx))
                self.search_counter_list.append(counter)
                self.highlighter_list.append(highlighter)

            rst_idx = self.sw.get_result_edit_index(pw.e_source)
            if rst_idx != -1:
                self.sw_changed = True
                highlighter = self.sw.highlighter_list.pop(rst_idx)
                counter = self.sw.search_counter_list.pop(rst_idx)
                self.sw.counter_sum -= counter
                if self.sw.current_edit == pw.e_trans:
                    highlighter.set_current_span(-1, -1)
                self.search_rstedit_list.append(self.sw.search_rstedit_list.pop(rst_idx))
                self.search_counter_list.append(counter)
                self.highlighter_list.append(highlighter)

        self.new_counter_sum = self.sw.counter_sum
        if self.sw_changed:
            if self.sw.counter_sum > 0:
                idx = self.sw.get_result_edit_index(self.sw.current_edit)
                if self.sw.current_cursor is not None and idx != -1:
                    self.sw.result_pos = self.sw.highlighter_list[idx].matched_map[self.sw.current_cursor.position()]
                    if idx > 0:
                        self.sw.result_pos += sum(self.sw.search_counter_list[: idx])
                    self.sw.updateCounterText()
                else:
                    self.sw.setCurrentEditor(self.sw.search_rstedit_list[0])
            else:
                self.sw.setCurrentEditor(None)

        self.ctrl.deleteTextblkItemList(self.blk_list, self.pwidget_list)

    def redo(self):

        if self.mode == 1:
            self.canvas.saved_drawundo_step -= 1
            img_array = self.canvas.get_inpainted_array()
            mask_array = self.canvas.get_mask_array()
            for mskpnt, inpaint_rect, redo_img in zip(self.mask_pnts, self.inpaint_rect_lst, self.redo_img_list):
                if mskpnt == None:
                    continue
                x1, y1, x2, y2 = inpaint_rect
                img_array[y1: y2, x1: x2][mskpnt] = redo_img[mskpnt]
                mask_array[y1: y2, x1: x2][mskpnt] = 0
            self.canvas.updateLayers()

        if self.op_counter == 0:
            self.op_counter += 1
            return

        self.ctrl.deleteTextblkItemList(self.blk_list, self.pwidget_list)
        if self.sw_changed:
            self.sw.counter_sum = self.new_counter_sum
            cursor_removed = False
            for edit in self.search_rstedit_list:
                idx = self.sw.get_result_edit_index(edit)
                if idx != -1:
                    self.sw.search_rstedit_list.pop(idx)
                    self.sw.search_counter_list.pop(idx)
                    self.sw.highlighter_list.pop(idx)
                if edit == self.sw.current_edit:
                    cursor_removed = True
            if cursor_removed:
                if self.sw.counter_sum > 0:
                    self.sw.setCurrentEditor(self.sw.search_rstedit_list[0])
                else:
                    self.sw.setCurrentEditor(None)

    def undo(self):

        if self.mode == 1:
            self.canvas.saved_drawundo_step += 1
            img_array = self.canvas.get_inpainted_array()
            mask_array = self.canvas.get_mask_array()
            for mskpnt, inpaint_rect, undo_img in zip(self.mask_pnts, self.inpaint_rect_lst, self.undo_img_list):
                if mskpnt == None:
                    continue
                x1, y1, x2, y2 = inpaint_rect
                img_array[y1: y2, x1: x2][mskpnt] = undo_img[mskpnt]
                mask_array[y1: y2, x1: x2][mskpnt] = 255
            self.canvas.updateLayers()

        self.ctrl.recoverTextblkItemList(self.blk_list, self.pwidget_list)
        if self.sw_changed:
            self.sw.counter_sum = self.old_counter_sum
            self.sw.search_rstedit_list += self.search_rstedit_list
            self.sw.search_counter_list += self.search_counter_list
            self.sw.highlighter_list += self.highlighter_list
            self.sw.updateCounterText()


class PasteBlkItemsCommand(QUndoCommand):
    def __init__(self, blk_list: List[TextBlkItem], pwidget_list: List[TransPairWidget], ctrl, parent=None):
        super().__init__(parent)
        self.op_counter = 0
        self.blk_list = blk_list
        self.ctrl:SceneTextManager = ctrl
        blk_list.sort(key=lambda blk: blk.idx)

        self.ctrl.canvas.block_selection_signal = True
        for blkitem in blk_list:
            blkitem.setSelected(True)
        self.ctrl.on_incanvas_selection_changed()
        self.ctrl.canvas.block_selection_signal = False
        self.pwidget_list = pwidget_list
        

    def redo(self):
        if self.op_counter == 0:
            self.op_counter += 1
            return
        self.ctrl.recoverTextblkItemList(self.blk_list, self.pwidget_list)

    def undo(self):
        self.ctrl.deleteTextblkItemList(self.blk_list, self.pwidget_list)


class PasteSrcItemsCommand(QUndoCommand):
    def __init__(self, src_list: List[SourceTextEdit], paste_list: List[str]):
        super().__init__()
        self.src_list = src_list
        self.paste_list = paste_list
        self.ori_text_list = [src.toPlainText() for src in src_list]

    def redo(self):
        for src, text in zip(self.src_list, self.paste_list):
            src.setPlainText(text)

    def undo(self):
        for src, text in zip(self.src_list, self.ori_text_list):
            src.setPlainText(text)


class RearrangeBlksCommand(QUndoCommand):

    def __init__(self, rmap: Tuple, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl: SceneTextManager = ctrl
        self.src_ids, self.tgt_ids = rmap[0], rmap[1]

        self.nr = len(self.src_ids)
        self.src2tgt = {}
        self.tgt2src = {}
        for s, t in zip(self.src_ids, self.tgt_ids):
            self.src2tgt[s] = t
            self.tgt2src[t] = s
        self.visible_ = None
        self.redo_visible_idx = self.undo_visible_idx = None
        if len(rmap) > 2:
            self.redo_visible_idx, self.undo_visible_idx = rmap[2]

    def redo(self):
        self.rearange_blk_ids(self.src_ids, self.tgt_ids, self.redo_visible_idx)

    def undo(self):
        self.rearange_blk_ids(self.tgt_ids, self.src_ids, self.undo_visible_idx)

    def rearange_blk_ids(self, src_ids, tgt_ids, visible_idx = None):
        src_ids = np.array(src_ids)
        tgt_ids = np.array(tgt_ids)
        src_order_ids = np.argsort(src_ids)[::-1]

        src_ids = src_ids[src_order_ids]
        tgt_ids = tgt_ids[src_order_ids]
        
        blks: List[TextBlkItem] = []
        pws: List[TransPairWidget] = []
        for pos, pos_tgt in zip(src_ids, tgt_ids):
            pw = self.ctrl.pairwidget_list.pop(pos)
            if visible_idx == pos_tgt:
                pw.hide()
            blk = self.ctrl.textblk_item_list.pop(pos)
            pws.append(pw)
            blks.append(blk)

        tgt_order_ids = np.argsort(tgt_ids)
        for ii in tgt_order_ids:
            pos = tgt_ids[ii]
            self.ctrl.textblk_item_list.insert(pos, blks[ii])
            
            self.ctrl.textEditList.insertPairWidget(pws[ii], pos)
            self.ctrl.pairwidget_list.insert(pos, pws[ii])

        self.ctrl.updateTextBlkItemIdx(set(tgt_ids))
        if visible_idx is not None:
            pw_ct = self.ctrl.pairwidget_list[visible_idx]
            pw_ct.show()
            self.ctrl.textEditList.ensureWidgetVisible(pw_ct, yMargin=pw.height())


class TextPanel(Widget):
    def __init__(self, app: QApplication, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        layout = QVBoxLayout(self)
        self.textEditList = TextEditListScrollArea(self)
        self.formatpanel = FontFormatPanel(app, self)
        layout.addWidget(self.formatpanel)
        layout.addWidget(self.textEditList)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)


class SceneTextManager(QObject):
    new_textblk = Signal(int)
    def __init__(self, 
                 app: QApplication,
                 mainwindow: QWidget,
                 canvas: Canvas, 
                 textpanel: TextPanel, 
                 *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.app = app     
        self.mainwindow = mainwindow
        self.canvas = canvas
        canvas.switch_text_item.connect(self.on_switch_textitem)
        self.selectext_minimenu: SelectTextMiniMenu = None
        self.canvas.scalefactor_changed.connect(self.adjustSceneTextRect)
        self.canvas.end_create_textblock.connect(self.onEndCreateTextBlock)
        self.canvas.paste2selected_textitems.connect(self.on_paste2selected_textitems)
        self.canvas.delete_textblks.connect(self.onDeleteBlkItems)
        self.canvas.copy_textblks.connect(self.onCopyBlkItems)
        self.canvas.paste_textblks.connect(self.onPasteBlkItems)
        self.canvas.format_textblks.connect(self.onFormatTextblks)
        self.canvas.layout_textblks.connect(self.onAutoLayoutTextblks)
        self.canvas.reset_angle.connect(self.onResetAngle)
        self.canvas.squeeze_blk.connect(self.onSqueezeBlk)
        self.canvas.savePng_blk.connect(self.onSavePngBlk)        
        self.canvas.incanvas_selection_changed.connect(self.on_incanvas_selection_changed)
        self.txtblkShapeControl = canvas.txtblkShapeControl
        self.textpanel = textpanel
        self.textEditList = textpanel.textEditList
        self.textEditList.focus_out.connect(self.on_textedit_list_focusout)
        self.textEditList.textpanel_contextmenu_requested.connect(canvas.on_create_contextmenu)
        self.textEditList.selection_changed.connect(self.on_transwidget_selection_changed)
        self.textEditList.rearrange_blks.connect(self.on_rearrange_blks)
        self.formatpanel = textpanel.formatpanel
        self.formatpanel.textstyle_panel.apply_fontfmt.connect(self.onFormatTextblks)

        self.imgtrans_proj = self.canvas.imgtrans

        self._auto_textlayout_flag = False
        self.hovering_transwidget : TransTextEdit = None

        self.prev_blkitem: TextBlkItem = None

        self.SpellCheckEngine = get_spellcheck_engine()
        self.textpanel.formatpanel.word_panel.word_selected.connect(self.on_spell_word_clicked)
        self.textpanel.formatpanel.word_panel.wordDeleted.connect(self.onWordDeleted)

        # Initialize TextLayoutManager (extracted business logic)
        self.layout_manager = TextLayoutManager(pcfg)
        self.layout_manager.auto_textlayout_flag = self._auto_textlayout_flag

        # Initialize OverlapResolver (extracted business logic)
        self.overlap_resolver = OverlapResolver()

        # Initialize TransPairWiring (extracted signal wiring)
        self.pair_wiring = TransPairWiring(self)

        # Initialize BlockManager (extracted block list management)
        self.block_manager = BlockManager(canvas, self.textEditList)

        # Initialize ClipboardManager (extracted clipboard operations)
        self.clipboard_manager = ClipboardManager(app, canvas, self.block_manager)

        # Initialize SelectionManager (extracted selection state management)
        self.selection_manager = SelectionManager(canvas, self.textEditList, self.block_manager, self.formatpanel)

        # Delegate lists to block_manager (maintained for backward compatibility)
        # The block_manager now owns these lists
        self.textblk_item_list = self.block_manager.textblk_item_list
        self.pairwidget_list = self.block_manager.pairwidget_list

        # Initialize EventBus and subscribe to events
        self._event_bus = EventBus.get_instance()
        self._subscribe_to_events()

        # DI services (set by CompositionRoot after creation)
        self._undo_mgr = None

    @property
    def auto_textlayout_flag(self) -> bool:
        return self._auto_textlayout_flag

    @auto_textlayout_flag.setter
    def auto_textlayout_flag(self, value: bool):
        self._auto_textlayout_flag = value
        self.layout_manager.auto_textlayout_flag = value

    def push_undo_command(self, command, update_pushed_step=True):
        """Proxy: добавляет команду в стек undo через DI UndoManager."""
        if self._undo_mgr:
            self._undo_mgr.push_command(command)
        else:
            self.canvas.push_undo_command(command, update_pushed_step)

    def _subscribe_to_events(self):
        """Подписывается на события EventBus."""
        # Навигация
        self._event_bus.subscribe(Events.NAVIGATE_NEXT, lambda d=None: self.on_switch_textitem(1))
        self._event_bus.subscribe(Events.NAVIGATE_PREV, lambda d=None: self.on_switch_textitem(-1))

        # Блоки
        self._event_bus.subscribe(Events.DELETE_TEXT_BLOCKS, self.onDeleteBlkItems)
        self._event_bus.subscribe(Events.COPY_TEXT_BLOCKS, self.onCopyBlkItems)
        self._event_bus.subscribe(Events.PASTE_TEXT_BLOCKS, self.onPasteBlkItems)
        self._event_bus.subscribe(Events.FORMAT_TEXT_BLOCKS, self.onFormatTextblks)
        self._event_bus.subscribe(Events.LAYOUT_TEXT_BLOCKS, self.onAutoLayoutTextblks)

        # Выделение
        self._event_bus.subscribe(Events.SELECTION_CHANGED, self.on_incanvas_selection_changed)

        # Undo/Redo
        self._event_bus.subscribe(Events.UNDO, lambda d=None: self.canvas.undo())
        self._event_bus.subscribe(Events.REDO, lambda d=None: self.canvas.redo())

        # Масштаб
        self._event_bus.subscribe(Events.SCALE_CHANGED, self.adjustSceneTextRect)

    def _unsubscribe_from_events(self):
        """Отписывается от событий EventBus."""
        self._event_bus.unsubscribe(Events.NAVIGATE_NEXT, lambda: self.on_switch_textitem(1))
        self._event_bus.unsubscribe(Events.NAVIGATE_PREV, lambda: self.on_switch_textitem(-1))
        self._event_bus.unsubscribe(Events.DELETE_TEXT_BLOCKS, self.onDeleteBlkItems)
        self._event_bus.unsubscribe(Events.COPY_TEXT_BLOCKS, self.onCopyBlkItems)
        self._event_bus.unsubscribe(Events.PASTE_TEXT_BLOCKS, self.onPasteBlkItems)
        self._event_bus.unsubscribe(Events.FORMAT_TEXT_BLOCKS, self.onFormatTextblks)
        self._event_bus.unsubscribe(Events.LAYOUT_TEXT_BLOCKS, self.onAutoLayoutTextblks)
        self._event_bus.unsubscribe(Events.SELECTION_CHANGED, self.on_incanvas_selection_changed)
        self._event_bus.unsubscribe(Events.SCALE_CHANGED, self.adjustSceneTextRect)

    def on_switch_textitem(self, switch_delta: int, key_event: QKeyEvent = None, current_editing_widget: Union[SourceTextEdit, TransTextEdit] = None):
        n_blk = len(self.textblk_item_list)
        if n_blk < 1:
            return
        
        editing_blk = None
        if current_editing_widget is None:
            editing_blk = self.editingTextItem()
            if editing_blk is not None:
                tgt_idx = editing_blk.idx + switch_delta
            else:
                sel_blks = self.canvas.selected_text_items(sort=False)
                if len(sel_blks) == 0:
                    return
                sel_blk = sel_blks[0]
                tgt_idx = sel_blk.idx + switch_delta
        else:
            tgt_idx = current_editing_widget.idx + switch_delta

        if tgt_idx < 0:
            tgt_idx += n_blk
        elif tgt_idx >= n_blk:
            tgt_idx -= n_blk
        blk = self.textblk_item_list[tgt_idx]

        if current_editing_widget is None:
            if editing_blk is None:
                self.canvas.block_selection_signal = True
                self.canvas.clearSelection()
                blk.setSelected(True)
                self.canvas.block_selection_signal = False
                self.canvas.ensure_visible(blk)
                self.txtblkShapeControl.setBlkItem(blk)
                edit = self.pairwidget_list[tgt_idx].e_trans
                self.changeHoveringWidget(edit)
                self.textEditList.set_selected_list([blk.idx])
            else:
                editing_blk.endEdit()
                editing_blk.setSelected(False)
                self.txtblkShapeControl.setBlkItem(blk)
                blk.setSelected(True)
                blk.startEdit()
                self.canvas.ensure_visible(blk)
        else:
            self.textblk_item_list[current_editing_widget.idx].setSelected(False)
            current_pw = self.pairwidget_list[tgt_idx]
            is_trans = isinstance(current_editing_widget, TransTextEdit)
            if is_trans:
                w = current_pw.e_trans
            else:
                w = current_pw.e_source

            self.changeHoveringWidget(w)
            w.setFocus()

        if key_event is not None:
            key_event.accept()

    def setTextEditMode(self, edit: bool = False):
        if edit:
            self.textpanel.show()
            self.canvas.set_text_layer_visible(True)
        else:
            self.txtblkShapeControl.setBlkItem(None)
            self.textpanel.hide()
            self.textpanel.formatpanel.set_textblk_item()
            self.canvas.set_text_layer_visible(False)

    def adjustSceneTextRect(self, data=None):
        self.txtblkShapeControl.updateBoundingRect()

    def clearSceneTextitems(self):
        """Delegate to block_manager."""
        _debug("clearSceneTextitems: saving flow points for %d items", len(self.textblk_item_list))
        self.hovering_transwidget = None
        self.txtblkShapeControl.setBlkItem(None)
        self.block_manager.clear_all()

    def updateSceneTextitems(self):
        """
        This is a "destructive" function that rebuilds the UI.
        It should only be called safely from the event loop, not directly from
        a signal handler of a widget it is about to destroy.
        """
        _debug("=== updateSceneTextitems START ===")
        _debug("  block count in proj: %d", len(self.imgtrans_proj.current_block_list()))
        self.hovering_transwidget = None
        self.txtblkShapeControl.setBlkItem(None)
        self.clearSceneTextitems()

        block_list = self.imgtrans_proj.current_block_list()
        target_count = sum(1 for b in block_list if hasattr(b, 'get_text') and b.get_text().startswith(_LOG_TARGET))
        if target_count > 0:
            LOGGER.debug("[FONTSIZE] PAGE updateSceneTextitems: block_count=%d (target_blocks=%d)", len(block_list), target_count)
        for i, textblock in enumerate(block_list):
            if hasattr(textblock, 'get_text') and textblock.get_text().startswith(_LOG_TARGET):
                LOGGER.debug("[FONTSIZE] PAGE block[%d]: font_size=%.1fpx", i, textblock.fontformat.font_size)

        for textblock in block_list:
            if textblock.font_family is None or textblock.font_family.strip() == '':
                textblock.font_family = self.formatpanel.familybox.currentText()
            blk_item = self.addTextBlock(textblock)
        
        # Update the word panel with the extracted words
        self.updateUnknownWordsPanel()

        self.updateTextBlkList()


    def addTextBlock(self, blk: Union[TextBlock, TextBlkItem] = None) -> TextBlkItem:
        # import debugpy
        # debugpy.debug_this_thread()
        # debugpy.breakpoint()
        _debug("=== addTextBlock ===")
        _debug("  blk type=%s, idx will be %d",
                     type(blk).__name__ if blk else "None",
                     len(self.textblk_item_list))
        # Log specific blocks on page load
        if blk is not None and hasattr(blk, 'translation'):
            txt = blk.translation or ''
            if txt.startswith('В ЭТОЙ') or txt.startswith('ДА!... НО ОН'):
                LOGGER.debug("[TRACK] LOAD blk='%s' xyxy=%s left=%s right=%s",
                       txt[:20], blk.xyxy,
                       getattr(blk, 'left_points', None),
                       getattr(blk, 'right_points', None))
        did_auto_layout = False
        if isinstance(blk, TextBlkItem):
            blk_item = blk
            blk_item.idx = len(self.textblk_item_list)
            _debug("  existing TextBlkItem, pos=%s", blk_item.pos())
        else:
            translation = ''
            if self.auto_textlayout_flag and not blk.vertical:
                translation = blk.translation
                blk.translation = ''
            _debug("  creating FlowTextBlkItem with blk.xyxy=%s", blk.xyxy if blk else "None")
            blk_item = FlowTextBlkItem(blk, len(self.textblk_item_list), show_rect=self.canvas.textblock_mode)
            if translation:
                blk.translation = translation
                rst = self.layout_textblk(blk_item, text=translation)
                did_auto_layout = True
                if rst is None:
                    blk_item.setPlainText(translation)
        _debug("  after creation: blk_item.pos=%s", blk_item.pos())
        if hasattr(blk_item, '_left_points'):
            _debug("  left_points=%s",
                         [(p.x(), p.y()) for p in blk_item._left_points])
            _debug("  right_points=%s",
                         [(p.x(), p.y()) for p in blk_item._right_points])
            # Log tracked blocks after flow points are set
            txt = blk_item.toPlainText() if blk_item else ''
            if txt.startswith('В ЭТОЙ') or txt.startswith('ДА!... НО ОН'):
                LOGGER.debug("[TRACK] LOAD_FLOW blk='%s' pos=%s left=%s right=%s",
                       txt[:20], blk_item.pos(),
                       [(p.x(), p.y()) for p in blk_item._left_points],
                       [(p.x(), p.y()) for p in blk_item._right_points])
        self.addTextBlkItem(blk_item)

        # Resolve overlaps only during automatic layout (not on page load)
        if did_auto_layout and hasattr(blk_item, '_left_points') and hasattr(blk_item, '_right_points'):
            self._resolve_overlaps(blk_item)
        # LOGGER.info(f"addTextBlock {blk_item.toPlainText()}")

        pair_widget = TransPairWidget(blk, len(self.pairwidget_list), pcfg.fold_textarea)
        self.pairwidget_list.append(pair_widget)
        self.textEditList.addPairWidget(pair_widget)

        # Wire signals using TransPairWiring
        self.pair_wiring.wire_signals(pair_widget, blk_item)

        self.new_textblk.emit(blk_item.idx)
        return blk_item

    def _resolve_overlaps(self, new_item):
        """Resolve overlaps between new_item and existing blocks."""
        self.overlap_resolver.resolve_overlaps(new_item, self.textblk_item_list)

    def addTextBlkItem(self, textblk_item: TextBlkItem) -> TextBlkItem:
        self.textblk_item_list.append(textblk_item)
        self.canvas.add_item_to_text_layer(textblk_item)
        textblk_item.begin_edit.connect(self.onTextBlkItemBeginEdit)
        textblk_item.end_edit.connect(self.onTextBlkItemEndEdit)
        textblk_item.hover_enter.connect(self.onTextBlkItemHoverEnter)
        textblk_item.leftbutton_pressed.connect(self.onLeftbuttonPressed)
        textblk_item.moving.connect(self.onTextBlkItemMoving)
        textblk_item.moved.connect(self.onTextBlkItemMoved)
        textblk_item.reshaped.connect(self.onTextBlkItemReshaped)
        textblk_item.rotated.connect(self.onTextBlkItemRotated)
        textblk_item.push_undo_stack.connect(self.on_push_textitem_undostack)
        textblk_item.undo_signal.connect(self.on_textedit_undo)
        textblk_item.redo_signal.connect(self.on_textedit_redo)
        textblk_item.propagate_user_edited.connect(self.on_propagate_textitem_edit)
        textblk_item.doc_size_changed.connect(self.onTextBlkItemSizeChanged)
        textblk_item.pasted.connect(self.onBlkitemPaste)
        return textblk_item

    def _on_source_text_changed(self):
        """
        Handles the text_changed signal from a SourceTextEdit widget.

        This function retrieves the sender, updates the underlying data model with
        the new text, and then triggers a refresh of the unknown words panel.
        """
        sender = self.sender()
        if not sender:
            return

        idx = sender.idx
        new_text = sender.toPlainText()

        if (len(self.imgtrans_proj.current_block_list()) <= idx):
            print(f"current_block_list {len(self.imgtrans_proj.current_block_list())} < {idx}")
            return
        
        try:
            # 1. Update the data model (TextBlock) with the latest text.
            #    This is a crucial first step.
            text_block: TextBlock = self.imgtrans_proj.current_block_list()[idx]
            text_block.text = new_text # Assumes a method like 'set_text' exists

        except (IndexError, AttributeError) as e:
            print(f"Could not update text block {idx}: {e}")
            return

        # 2. Call the new, lightweight function to update the word panel.
        #    This is safe to call directly because it does not destroy the sender.
        self.updateUnknownWordsPanel()


    def updateUnknownWordsPanel(self):
        """
        Gathers all text from the data model, finds unknown words, and
        updates the word panel UI. This is a targeted update and is much
        more efficient than rebuilding all scene items.
        """
        # Skip running spellcheck if the panel is hidden or spellcheck disabled
        try:
            if not getattr(self, "textpanel", None) or not self.textpanel.isVisible() or not pcfg.enable_spellcheck:
                return
        except Exception:
            # If any error occurs checking visibility or config, be conservative and skip
            return

        words = []
        # Iterate through the data model (the single source of truth)
        # using enumerate to get the index, which your original code used.
        for idx, textblock in enumerate(self.imgtrans_proj.current_block_list()):
            text_segments = textblock.get_text()
            if text_segments:
                # Create a tuple containing the text segment and its index
                combined_item = (text_segments, idx)
                words.append(combined_item)
        
        # Get the list of unknown words from your engine
        unknownWords = self.SpellCheckEngine.GetUnknownWordsViaDictionaryFromList(words)
        
        # Update just the word panel with the new list
        self.textpanel.formatpanel.word_panel.set_words(unknownWords)


    def deleteTextblkItemList(self, blkitem_list: List[TextBlkItem], p_widget_list: List[TransPairWidget]):
        """Delegate to block_manager and handle selection."""
        selection_changed = self.block_manager.delete_textblk_item_list(blkitem_list, p_widget_list)
        self.txtblkShapeControl.setBlkItem(None)
        if selection_changed:
            self.on_incanvas_selection_changed()

    def recoverTextblkItemList(self, blkitem_list: List[TextBlkItem], p_widget_list: List[TransPairWidget]):
        """Delegate to block_manager and handle selection."""
        self.block_manager.recover_textblk_item_list(blkitem_list, p_widget_list)
        # Handle shape control selection
        if self.txtblkShapeControl.blk_item is not None:
            for blkitem in blkitem_list:
                if blkitem.isSelected():
                    blkitem.setSelected(False)
        self.on_incanvas_selection_changed()
        
    def onTextBlkItemSizeChanged(self, idx: int):
        blk_item = self.textblk_item_list[idx]
        if not self.txtblkShapeControl.reshaping:
            if self.txtblkShapeControl.blk_item == blk_item:
                self.txtblkShapeControl.updateBoundingRect()

    @property
    def app_clipborad(self) -> QClipboard:
        """Delegate to clipboard_manager."""
        return self.clipboard_manager.app_clipboard

    def onBlkitemPaste(self, idx: int):
        blk_item = self.textblk_item_list[idx]
        text = self.app_clipborad.text()
        cursor = blk_item.textCursor()
        cursor.insertText(text)

    def onTextBlkItemBeginEdit(self, blk_id: int):
        blk_item = self.textblk_item_list[blk_id]
        self.txtblkShapeControl.setBlkItem(blk_item)
        self.canvas.editing_textblkitem = blk_item
        self.formatpanel.set_textblk_item(blk_item)
        self.txtblkShapeControl.startEditing()
        e_trans = self.pairwidget_list[blk_item.idx].e_trans
        self.changeHoveringWidget(e_trans)

    def changeHoveringWidget(self, edit: SourceTextEdit):
        """Delegate to selection_manager."""
        self.selection_manager.change_hovering_widget(edit)

    def onLeftbuttonPressed(self, blk_id: int):
        blk_item = self.textblk_item_list[blk_id]
        self.txtblkShapeControl.setBlkItem(blk_item)

        # Log clicked block's coordinates and flow points
        if hasattr(blk_item, '_left_points') and blk_item._left_points:
            txt = blk_item.toPlainText()[:30] if blk_item else ''
            p = blk_item.pos()
            # LOGGER.debug("[CLICK] blk='%s' idx=%d pos=(%.0f,%.0f) xyxy=%s left=%s right=%s",
            #     txt, blk_id, p.x(), p.y(),
            #     blk_item.blk.xyxy if blk_item.blk else None,
            #     [(round(pt.x(),1), round(pt.y(),1)) for pt in blk_item._left_points],
            #     [(round(pt.x(),1), round(pt.y(),1)) for pt in blk_item._right_points])
        selections: List[TextBlkItem] = self.canvas.selectedItems()
        if len(selections) > 1:
            for item in selections:
                item.oldPos = item.pos()
        self.changeHoveringWidget(self.pairwidget_list[blk_id].e_trans)

    def onTextBlkItemEndEdit(self, blk_id: int):
        self.canvas.editing_textblkitem = None
        self.textblk_item_list[blk_id].setSelected(True)
        self.txtblkShapeControl.endEditing()

    def editingTextItem(self) -> TextBlkItem:
        if self.txtblkShapeControl.isVisible() and self.canvas.editing_textblkitem is not None:
            return self.canvas.editing_textblkitem
        return None

    def savePrevBlkItem(self, blkitem: TextBlkItem):
        self.prev_blkitem = blkitem
        self.prev_textCursor = QTextCursor(self.prev_blkitem.textCursor())

    def is_editting(self):
        blk_item = self.txtblkShapeControl.blk_item
        return blk_item is not None and blk_item.is_editting()

    def onTextBlkItemHoverEnter(self, blk_id: int):
        if self.is_editting():
            return
        blk_item = self.textblk_item_list[blk_id]
        if not blk_item.hasFocus():
            self.txtblkShapeControl.setBlkItem(blk_item)

    def onTextBlkItemMoving(self, item: TextBlkItem):
        self.txtblkShapeControl.updateBoundingRect()

    def onTextBlkItemMoved(self):
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) > 0:
            self.push_undo_command(MoveBlkItemsCommand(selected_blks, self.txtblkShapeControl))
        
    def onTextBlkItemReshaped(self, item: TextBlkItem):
        self.push_undo_command(ReshapeItemCommand(item))

    def onTextBlkItemRotated(self, new_angle: float):
        blk_item = self.txtblkShapeControl.blk_item
        if blk_item:
            self.push_undo_command(RotateItemCommand(blk_item, new_angle, self.txtblkShapeControl))

    def onDeleteBlkItems(self, mode: int = 0, data=None):
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) == 0 and self.txtblkShapeControl.blk_item is not None:
            selected_blks.append(self.txtblkShapeControl.blk_item)
        if len(selected_blks) > 0:
            self.push_undo_command(DeleteBlkItemsCommand(selected_blks, mode, self))

    def onCopyBlkItems(self, data=None):
        """Delegate to clipboard_manager."""
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) == 0 and self.txtblkShapeControl.blk_item is not None:
            selected_blks.append(self.txtblkShapeControl.blk_item)

        self.clipboard_manager.copy_blocks(selected_blks)

    def onPasteBlkItems(self, pos: QPointF = None, data=None):
        """Delegate to clipboard_manager and handle undo."""
        blocks_to_paste = self.clipboard_manager.paste_blocks(pos)

        blkitem_list = []
        pair_widget_list = []

        for blk, pos_x, pos_y in blocks_to_paste:
            blkitem = self.addTextBlock(blk)
            pairw = self.pairwidget_list[-1]
            blkitem_list.append(blkitem)
            pair_widget_list.append(pairw)

        if len(blkitem_list) > 0:
            self.canvas.clearSelection()
            self.push_undo_command(PasteBlkItemsCommand(blkitem_list, pair_widget_list, self))
            if len(blkitem_list) == 1:
                self.formatpanel.set_textblk_item(blkitem_list[0])
            else:
                self.formatpanel.set_textblk_item(multi_select=True)

    def onFormatTextblks(self, fmt: FontFormat = None, data=None):
        if fmt is None:
            fmt = self.formatpanel.global_format
        self.apply_fontformat(fmt)

    def ensure_text_in_block(self, blkitem: TextBlkItem):
        """
        Убедиться, что в блоке есть текст и он отображается
        """
        text = blkitem.toPlainText()
        if not text.strip():
            # Если текст пустой, проверить виджет перевода
            if len(self.pairwidget_list) > blkitem.idx:
                widget_text = self.pairwidget_list[blkitem.idx].e_trans.toPlainText()
                if widget_text.strip():
                    _debug(f"Блок {blkitem.idx}: восстановление текста из виджета")
                    blkitem.setPlainText(widget_text)
                    return True
        return False

    def onAutoLayoutTextblks(self, data=None):
        selected_blks = self.canvas.selected_text_items()
        old_html_lst, old_rect_lst, trans_widget_lst = [], [], []
        
        # Фильтруем только горизонтальные блоки
        selected_blks = [blk for blk in selected_blks if not blk.fontformat.vertical]
        
        if len(selected_blks) > 0:
            LOGGER.info(f"Автоматический layout для {len(selected_blks)} блоков")
            
            for blkitem in selected_blks:
                try:
                    # Убедиться, что в блоке есть текст
                    self.ensure_text_in_block(blkitem)
                    
                    old_html_lst.append(blkitem.toHtml())
                    old_rect_lst.append(blkitem.absBoundingRect(qrect=True))
                    trans_widget_lst.append(self.pairwidget_list[blkitem.idx].e_trans)
                    
                    # Выполнить layout
                    success = self.layout_textblk(blkitem)
                    
                    if not success:
                        LOGGER.warning(f"Layout не удался для блока {blkitem.idx}")
                        # Fallback: оставить исходный текст с текущим размером шрифта
                        
                except Exception as e:
                    LOGGER.error(f"Ошибка в layout для блока {blkitem.idx}: {e}")
                    continue

            # Создать команду отмены
            if old_html_lst:
                self.push_undo_command(AutoLayoutCommand(selected_blks, old_rect_lst, old_html_lst, trans_widget_lst))

    def onResetAngle(self):
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) > 0:
            self.push_undo_command(ResetAngleCommand(selected_blks, self.txtblkShapeControl))

    def onSqueezeBlk(self):
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) > 0:
            self.push_undo_command(SqueezeCommand(selected_blks, self.txtblkShapeControl))

    def onSavePngBlk(self):
        selected_blks = self.canvas.selected_text_items()
        if len(selected_blks) > 0:
            for blkitem in selected_blks:
                x1, y1, x2, y2 = map(int, blkitem.blk.xyxy)
                from PIL import Image
                from pathlib import Path
                im = Image.fromarray(self.imgtrans_proj.img_array[y1:y2, x1:x2])
                im.save(f'{Path(self.imgtrans_proj.current_img).stem}_{blkitem.idx}.png')


    def on_incanvas_selection_changed(self, data=None):
        """Delegate to selection_manager."""
        self.selection_manager.on_incanvas_selection_changed()

    def layout_textblk(self, blkitem: TextBlkItem, text: str = None, mask: np.ndarray = None,
                       bounding_rect: List = None, region_rect: List = None):
        '''
        Auto text layout, vertical writing is not supported yet.
        - auto_textlayout_flag ON:  binary search for max font size fitting in block
        - auto_textlayout_flag OFF: original mask-based layout with global font size
        
        Delegates to TextLayoutManager for pure business logic.
        Updates View (pairwidget) after layout.
        '''
        img = self.imgtrans_proj.img_array
        if img is None:
            return

        # Delegate to TextLayoutManager
        new_text = self.layout_manager.layout_textblk(
            blkitem, text, mask, bounding_rect, region_rect, img_array=img
        )

        # Update View (translation widget) if text changed
        if new_text is not None and len(self.pairwidget_list) > blkitem.idx:
            self.pairwidget_list[blkitem.idx].e_trans.setPlainText(new_text)

        return new_text is not None

    def onEndCreateTextBlock(self, rect: QRectF):
        xyxy = np.array([rect.x(), rect.y(), rect.right(), rect.bottom()])        
        xyxy = np.round(xyxy).astype(np.int32)
        block = TextBlock(xyxy)
        xywh = np.copy(xyxy)
        xywh[[2, 3]] -= xywh[[0, 1]]
        block.set_lines_by_xywh(xywh)
        block.src_is_vertical = self.formatpanel.global_format.vertical
        blk_item = FlowTextBlkItem(block, len(self.textblk_item_list), set_format=False, show_rect=True)
        blk_item.set_fontformat(self.formatpanel.global_format)
        # Initialise flow boundary points from the new rect
        if hasattr(blk_item, '_init_points_from_rect'):
            blk_item._init_points_from_rect(blk_item.absBoundingRect(qrect=True))
        self.push_undo_command(CreateItemCommand(blk_item, self))

    def on_paste2selected_textitems(self):
        blkitems = self.canvas.selected_text_items()
        text = self.app_clipborad.text()

        num_blk = len(blkitems)
        if num_blk < 1:
            return
        
        if num_blk > 1:
            text_list = text.rstrip().split('\n')
            num_text = len(text_list)
            if num_text > 1:
                if num_text > num_blk:
                    text_list = text_list[:num_blk]
                elif num_text < num_blk:
                    text_list = text_list + [text_list[-1]] * (num_blk - num_text)
                text = text_list
        
        etrans = [self.pairwidget_list[blkitem.idx].e_trans for blkitem in blkitems]
        self.push_undo_command(MultiPasteCommand(text, blkitems, etrans))

    def onRotateTextBlkItem(self, item: TextBlock):
        self.push_undo_command(RotateItemCommand(item))
    
    def on_transwidget_focus_in(self, idx: int):
        if self.is_editting():
            textitm = self.editingTextItem()
            textitm.endEdit()
            self.pairwidget_list[textitm.idx].e_trans.setHoverEffect(False)
            self.textEditList.clearAllSelected()

        if idx < len(self.textblk_item_list):
            blk_item = self.textblk_item_list[idx]
            sender = self.sender()
            if isinstance(sender, TransTextEdit):
                blk_item.setCacheMode(QGraphicsItem.CacheMode.NoCache)
            self.canvas.ensure_visible(blk_item)
            self.txtblkShapeControl.setBlkItem(blk_item)

    def on_textedit_redo(self):
        self.canvas.redo_textedit()

    def on_textedit_undo(self):
        self.canvas.undo_textedit()

    def on_show_select_menu(self, pos: QPoint, selected_text: str):
        if pcfg.textselect_mini_menu:
            if not selected_text:
                if self.selectext_minimenu.isVisible():
                    self.selectext_minimenu.hide()
            else:
                self.selectext_minimenu.show()
                self.selectext_minimenu.move(self.mainwindow.mapFromGlobal(pos))
                self.selectext_minimenu.selected_text = selected_text

    def on_block_current_editor(self, block: bool):
        w: SourceTextEdit = self.app.focusWidget()
        if isinstance(w, SourceTextEdit) or isinstance(w, TextBlkItem):
            w.block_all_input = block

    def on_pairw_focusout(self, idx: int):
        if self.selectext_minimenu.isVisible():
            self.selectext_minimenu.hide()
        sender = self.sender()
        if isinstance(sender, TransTextEdit) and idx < len(self.textblk_item_list):
            blk_item = self.textblk_item_list[idx]
            blk_item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def on_push_textitem_undostack(self, num_steps: int, is_formatting: bool):
        blkitem: TextBlkItem = self.sender()
        e_trans = self.pairwidget_list[blkitem.idx].e_trans if not is_formatting else None
        self.push_undo_command(TextItemEditCommand(blkitem, e_trans, num_steps, self.textpanel.formatpanel), update_pushed_step=is_formatting)

    def on_push_edit_stack(self, num_steps: int):
        edit: Union[TransTextEdit, SourceTextEdit] = self.sender()
        is_trans = type(edit) == TransTextEdit
        blkitem = self.textblk_item_list[edit.idx] if is_trans else None
        self.push_undo_command(TextEditCommand(edit, num_steps, blkitem), update_pushed_step=not is_trans)

    def on_propagate_textitem_edit(self, pos: int, added_text: str, joint_previous: bool):
        blk_item: TextBlkItem = self.sender()
        edit = self.pairwidget_list[blk_item.idx].e_trans
        propagate_user_edit(blk_item, edit, pos, added_text, joint_previous)
        self.canvas.push_text_command(command=None, update_pushed_step=True)

    def on_propagate_transwidget_edit(self, pos: int, added_text: str, joint_previous: bool):
        edit: TransTextEdit = self.sender()
        blk_item = self.textblk_item_list[edit.idx]
        if blk_item.isEditing():
            blk_item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        propagate_user_edit(edit, blk_item, pos, added_text, joint_previous)
        self.canvas.push_text_command(command=None, update_pushed_step=True)

    def apply_fontformat(self, fontformat: FontFormat):
        selected_blks = self.canvas.selected_text_items()
        trans_widget_list = []
        for blk in selected_blks:
            trans_widget_list.append(self.pairwidget_list[blk.idx].e_trans)
        if len(selected_blks) > 0:
            self.push_undo_command(ApplyFontformatCommand(selected_blks, trans_widget_list, fontformat))
            if self.formatpanel.global_mode():
                if id(self.formatpanel.active_text_style_format()) != id(fontformat):
                    self.formatpanel.deactivate_style_label()
                self.formatpanel.on_active_textstyle_label_changed()
            else:
                self.formatpanel.set_active_format(fontformat)

    def on_transwidget_selection_changed(self):
        """Delegate to selection_manager."""
        self.selection_manager.on_transwidget_selection_changed()

    def on_textedit_list_focusout(self):
        fw = self.app.focusWidget()
        focusing_edit = isinstance(fw, (SourceTextEdit, TransTextEdit))
        if fw == self.canvas.gv or focusing_edit:
            self.textEditList.clearDrag()
        if focusing_edit:
            self.textEditList.clearAllSelected()

    def on_rearrange_blks(self, mv_map: Tuple[np.ndarray]):
        self.push_undo_command(RearrangeBlksCommand(mv_map, self))

    def updateTextBlkItemIdx(self, sel_ids: set = None):
        """Delegate to block_manager."""
        self.block_manager.update_textblk_item_idx(sel_ids)

    def updateTextBlkList(self):
        """Delegate to block_manager."""
        self.block_manager.update_textblk_list(self.imgtrans_proj)

    def updateTranslation(self):
        for blk_item, transwidget in zip(self.textblk_item_list, self.pairwidget_list):
            transwidget.e_trans.setPlainText(blk_item.blk.translation)
            blk_item.setPlainText(blk_item.blk.translation)
        self.canvas.clear_text_stack()

    def showTextblkItemRect(self, draw_rect: bool):
        for blk_item in self.textblk_item_list:
            blk_item.draw_rect = draw_rect
            blk_item.update()

    def set_blkitems_selection(self, selected: bool, blk_items: List[TextBlkItem] = None):
        """Delegate to selection_manager."""
        self.selection_manager.set_blkitems_selection(selected, blk_items)

    def on_ensure_textitem_svisible(self):
        edit: Union[TransTextEdit, SourceTextEdit] = self.sender()
        self.changeHoveringWidget(edit)
        self.canvas.ensure_visible(self.textblk_item_list[edit.idx])
        self.txtblkShapeControl.setBlkItem(self.textblk_item_list[edit.idx])

    def on_page_replace_one(self):
        self.push_undo_command(PageReplaceOneCommand(self.canvas.search_widget))

    def on_page_replace_all(self):
        self.push_undo_command(PageReplaceAllCommand(self.canvas.search_widget))

    def on_spell_word_clicked(self, word: str, idx: object):
        if idx < len(self.textblk_item_list):
            blk_item = self.textblk_item_list[idx]
            self.canvas.ensure_visible(blk_item)
            self.txtblkShapeControl.setBlkItem(blk_item)

            self.textblk_item_list[idx].setSelected(True)
            # self.canvas.block_selection_signal = False

            # selections: List[TextBlkItem] = self.canvas.selectedItems()
            # if len(selections) > 1:
            #     for item in selections:
            #         item.oldPos = item.pos()
            self.changeHoveringWidget(self.pairwidget_list[idx].e_trans)

            self.pairwidget_list[idx].e_source.highlight_one_word(word, QColor(Qt.blue), QColor(Qt.yellow))

        # self.canvas.block_selection_signal = True
        # matched_indices = []
        # for idx, blk_item in enumerate(self.textblk_item_list):
        #     if word in blk_item.toPlainText():
        #         matched_indices.append(idx)
        #         blk_item.setSelected(True)
        #     else:
        #         blk_item.setSelected(False)

        # self.canvas.block_selection_signal = False

        # # Optional: ensure visible
        # if matched_indices:
        #     self.canvas.ensure_visible(self.textblk_item_list[matched_indices[0]])

    def onWordDeleted(self, word: str):
        self.SpellCheckEngine.onWordDeleted(word)
        self.updateSceneTextitems()

    def get_trans_edit_for_blkitem(self, idx) -> TransTextEdit:
        if 0 <= idx < len(self.pairwidget_list):
            return self.pairwidget_list[idx].e_trans
        return None
