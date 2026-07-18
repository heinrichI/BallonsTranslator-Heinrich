"""
SelectionManager - manages selection state between canvas and text edit list.

Extracted from SceneTextManager to follow SRP (Single Responsibility Principle).
This class handles selection synchronization and state management.
"""

from typing import List, Optional

from qtpy.QtCore import QObject, Signal

from .textitem import TextBlkItem
from .textedit_area import TransTextEdit, SourceTextEdit, TransPairWidget

from utils.logger import logger as LOGGER

QUIET_UI = True


def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)


class SelectionManager(QObject):
    """
    Manages selection state between canvas and text edit list.

    Responsibilities:
    - Synchronize selection between canvas and text edit list
    - Track selected blocks
    - Handle selection changes
    """

    selection_changed = Signal(list)  # emitted with list of selected indices

    def __init__(self, canvas, textEditList, block_manager, formatpanel, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.textEditList = textEditList
        self.block_manager = block_manager
        self.formatpanel = formatpanel

        # Hovering widget state
        self.hovering_transwidget: Optional[SourceTextEdit] = None

    def on_incanvas_selection_changed(self):
        """
        Handle selection changes in the canvas.
        Synchronizes selection state with the text edit list.
        """
        if self.canvas.textEditMode():
            textitems = self.canvas.selected_text_items()
            self.textEditList.set_selected_list([t.idx for t in textitems])

            if len(textitems) == 1:
                self.formatpanel.set_textblk_item(textitems[-1])
            else:
                self.formatpanel.set_textblk_item(multi_select=bool(textitems))

            self.selection_changed.emit([t.idx for t in textitems])

    def on_transwidget_selection_changed(self):
        """
        Handle selection changes in the trans widget list.
        Synchronizes selection state with the canvas.
        """
        selitems = self.canvas.selected_text_items()
        selset = {pw.idx: pw for pw in self.textEditList.checked_list}

        self.canvas.block_selection_signal = True
        for blkitem in selitems:
            if blkitem.idx not in selset:
                blkitem.setSelected(False)
            else:
                selset.pop(blkitem.idx)

        # Select blocks that are in the text edit list but not in canvas
        for idx in selset:
            if idx < len(self.block_manager.textblk_item_list):
                self.block_manager.textblk_item_list[idx].setSelected(True)

        self.canvas.block_selection_signal = False

    def set_blkitems_selection(
        self,
        selected: bool,
        blk_items: Optional[List[TextBlkItem]] = None
    ):
        """
        Set selection state for block items.

        Args:
            selected: Whether to select or deselect
            blk_items: List of blocks to select/deselect, or None for all
        """
        self.canvas.block_selection_signal = True

        if blk_items is None:
            blk_items = self.block_manager.textblk_item_list

        for blk_item in blk_items:
            blk_item.setSelected(selected)

        self.canvas.block_selection_signal = False
        self.on_incanvas_selection_changed()

    def change_hovering_widget(self, edit: Optional[SourceTextEdit]):
        """
        Change the currently hovering widget with hover effect.

        Args:
            edit: The new hovering widget, or None to clear
        """
        # Disconnect old widget's destroyed signal
        if self.hovering_transwidget is not None and self.hovering_transwidget != edit:
            try:
                self.hovering_transwidget.destroyed.disconnect(self._on_widget_destroyed)
            except (TypeError, RuntimeError):
                pass
            self.hovering_transwidget.setHoverEffect(False)

        self.hovering_transwidget = edit

        if edit is not None:
            # Connect to widget's destroyed signal for automatic cleanup
            edit.destroyed.connect(self._on_widget_destroyed)

            if 0 <= edit.idx < len(self.block_manager.pairwidget_list):
                pw = self.block_manager.pairwidget_list[edit.idx]
                h = pw.height()

                from utils import shared
                if shared.USE_PYSIDE6:
                    self.textEditList.ensureWidgetVisible(pw, ymargin=h)
                else:
                    self.textEditList.ensureWidgetVisible(pw, yMargin=h)

                edit.setHoverEffect(True)

    def _on_widget_destroyed(self):
        """Called when the hovered widget is destroyed by Qt."""
        self.hovering_transwidget = None

    def get_hovering_widget(self) -> Optional[SourceTextEdit]:
        """Get the currently hovering widget."""
        return self.hovering_transwidget

    def clear_hovering(self):
        """Clear the hovering widget state."""
        if self.hovering_transwidget is not None:
            try:
                self.hovering_transwidget.destroyed.disconnect(self._on_widget_destroyed)
            except (TypeError, RuntimeError):
                pass
            self.hovering_transwidget.setHoverEffect(False)
            self.hovering_transwidget = None
