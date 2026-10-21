"""
BlockManager - manages textblk_item_list and pairwidget_list.

Extracted from SceneTextManager to follow SRP (Single Responsibility Principle).
This class handles block CRUD operations and list management.
"""

from typing import List, Optional, Set
from qtpy.QtCore import QObject, Signal

from .textitem import TextBlkItem, TextBlock
from .text_sync import write_model_text, write_clean_text
from . import text_coords as TC
from .flow_textitem import FlowTextBlkItem
from .textedit_area import TransPairWidget, TextEditListScrollArea
from utils.fontformat import FontFormat

from utils.logger import logger as LOGGER

QUIET_UI = True


def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)


class BlockManager(QObject):
    """
    Manages the list of text block items and their associated pair widgets.

    Responsibilities:
    - Adding new text blocks
    - Deleting text blocks
    - Recovering text blocks (undo/redo)
    - Updating block indices
    - Syncing blocks with the data model
    """

    block_added = Signal(int)  # emitted when a block is added (idx)
    block_removed = Signal(int)  # emitted when a block is removed (idx)

    def __init__(self, canvas, textEditList: TextEditListScrollArea, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.textEditList = textEditList

        # Core data structures
        self.textblk_item_list: List[TextBlkItem] = []
        self.pairwidget_list: List[TransPairWidget] = []

    def add_textblk_item(self, textblk_item: TextBlkItem) -> TextBlkItem:
        """
        Add a TextBlkItem to the list and wire its signals.

        Returns:
            The added TextBlkItem
        """
        self.textblk_item_list.append(textblk_item)
        self.canvas.add_item_to_text_layer(textblk_item)

        # Wire signals - these will be connected to the appropriate handlers
        # by the SceneTextManager that owns this BlockManager
        return textblk_item

    def delete_textblk_item_list(
        self,
        blkitem_list: List[TextBlkItem],
        p_widget_list: List[TransPairWidget]
    ) -> bool:
        """
        Delete blocks from the lists and remove from canvas.

        Returns:
            True if selection changed, False otherwise
        """
        selection_changed = False
        for blkitem, p_widget in zip(blkitem_list, p_widget_list):
            if blkitem.isSelected():
                selection_changed = True
            self.canvas.removeItem(blkitem)
            self.textblk_item_list.remove(blkitem)
            self.pairwidget_list.remove(p_widget)
            self.textEditList.removeWidget(p_widget)

        self.update_textblk_item_idx()
        return selection_changed

    def recover_textblk_item_list(
        self,
        blkitem_list: List[TextBlkItem],
        p_widget_list: List[TransPairWidget]
    ):
        """
        Recover (re-add) blocks to the lists (for undo/redo).
        """
        self.canvas.block_selection_signal = True
        for blkitem, p_widget in zip(blkitem_list, p_widget_list):
            self.textblk_item_list.insert(blkitem.idx, blkitem)
            self.canvas.add_item_to_text_layer(blkitem)
            self.pairwidget_list.insert(p_widget.idx, p_widget)
            self.textEditList.insertPairWidget(p_widget, p_widget.idx)
        self.update_textblk_item_idx()
        self.canvas.block_selection_signal = False

    def update_textblk_item_idx(self, sel_ids: Optional[Set[int]] = None):
        """
        Update indices of all text block items and their pair widgets.

        Args:
            sel_ids: If provided, only update items with these indices
        """
        for ii, blk_item in enumerate(self.textblk_item_list):
            if sel_ids is not None and ii not in sel_ids:
                continue
            blk_item.idx = ii
            if ii < len(self.pairwidget_list):
                self.pairwidget_list[ii].updateIndex(ii)

        cl = self.textEditList.checked_list
        if len(cl) != 0:
            cl.sort(key=lambda x: x.idx)

    def update_textblk_list(self, imgtrans_proj):
        """
        Sync block items with the data model (imgtrans_proj.current_block_list).
        """
        cbl = imgtrans_proj.current_block_list()
        if cbl is None:
            return

        cbl.clear()
        for blk_item, trans_pair in zip(self.textblk_item_list, self.pairwidget_list):
            # I7 (последняя линия перед save): панель — канал ввода, поэтому
            # её текст и текст item обязаны описывать одно и то же. После
            # фикса (этим PR) любой штатный переписчик (auto-layout,
            # paste, updateTranslation) пишет и в панель тоже, так что
            # расхождение здесь — порча, а не «панель отстала»: item
            # пере-синкается по панели, и в проект-файл уходит текст
            # пользователя, а не испорченное зеркало (§5.2, §6).
            panel = getattr(trans_pair, 'e_trans', None)
            if panel is not None:
                item_text = blk_item.toPlainText()
                ok, reason = TC.texts_match(item_text, panel.toPlainText())
                if not ok:
                    LOGGER.error(
                        "[SYNC] I7 pre-save MISMATCH blk idx=%s: %s\n"
                        "  panel : %r\n  item  : %r\n"
                        "  hint: item пере-синкается по панели (канал ввода); "
                        "в проект-файл сохраняется текст панели "
                        "(см. PLAN_panel_edit_propagation.md §5.2 I7)",
                        blk_item.idx, reason, panel.toPlainText(),
                        item_text)
                    write_clean_text(blk_item, panel.toPlainText(),
                                     where=f"update_textblk_list blk idx={blk_item.idx}",
                                     keep_undo=True)
            if not blk_item.document().isEmpty():
                blk_item.blk.rich_text = blk_item.toHtml()
                # FlowTextBlkItem содержит в документе soft hyphens (U+00AD)
                # — сохраняем чистый текст без них (инвариант I2).
                write_model_text(blk_item.blk, blk_item.toPlainText(),
                                 where="update_textblk_list")
            else:
                blk_item.blk.rich_text = ''
                blk_item.blk.translation = ''
            blk_item.blk.text = [trans_pair.e_source.toPlainText()]
            blk_item.sync_coordinates()
            blk_item.updateBlkFormat()

            # Save flow points if supported
            if hasattr(blk_item, 'save_flow_points'):
                blk_item.save_flow_points()

            cbl.append(blk_item.blk)

    def clear_all(self):
        """Clear all block items and pair widgets."""
        # Save flow points before clearing
        for blkitem in self.textblk_item_list:
            if hasattr(blkitem, 'save_flow_points'):
                blkitem.save_flow_points()

        # Remove from canvas
        for blkitem in self.textblk_item_list:
            self.canvas.removeItem(blkitem)

        self.textblk_item_list.clear()

        # Remove pair widgets from the list
        for textwidget in self.pairwidget_list:
            self.textEditList.removeWidget(textwidget)
        self.pairwidget_list.clear()

        self.textEditList.clearAllSelected()

    def get_block(self, idx: int) -> Optional[TextBlkItem]:
        """Get a block item by index."""
        if 0 <= idx < len(self.textblk_item_list):
            return self.textblk_item_list[idx]
        return None

    def get_pair_widget(self, idx: int) -> Optional[TransPairWidget]:
        """Get a pair widget by index."""
        if 0 <= idx < len(self.pairwidget_list):
            return self.pairwidget_list[idx]
        return None

    @property
    def block_count(self) -> int:
        """Return the number of block items."""
        return len(self.textblk_item_list)
