"""
ClipboardManager - handles copy/paste operations for text blocks.

Extracted from SceneTextManager to follow SRP (Single Responsibility Principle).
This class handles clipboard-related operations.
"""

import copy
from typing import List, Optional

from qtpy.QtCore import QObject, QPointF
from qtpy.QtGui import QClipboard

from .textitem import TextBlkItem, TextBlock
from .textedit_area import TransPairWidget

from utils.logger import logger as LOGGER

QUIET_UI = True


def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)


class ClipboardManager(QObject):
    """
    Handles copy/paste operations for text blocks.

    Responsibilities:
    - Copying selected blocks to clipboard
    - Pasting blocks from clipboard
    - Pasting text to selected blocks
    """

    def __init__(self, app, canvas, block_manager, clipboard_service=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.canvas = canvas
        self.block_manager = block_manager
        self._clipboard_svc = clipboard_service

    @property
    def app_clipboard(self) -> QClipboard:
        """Get the application clipboard."""
        return self.app.clipboard()

    def copy_blocks(self, selected_blks: List[TextBlkItem]) -> List[TextBlock]:
        """
        Copy selected blocks to clipboard.

        Args:
            selected_blks: List of selected TextBlkItem objects

        Returns:
            List of copied TextBlock objects
        """
        if len(selected_blks) == 0:
            return []

        # Sync text list if there are unsaved changes
        if self.canvas.text_change_unsaved():
            self.block_manager.update_textblk_list(self.canvas.imgtrans)

        # Calculate center position for relative positioning
        pos = selected_blks[0].blk.bounding_rect()
        pos_x = int(pos[0] + pos[2] / 2)
        pos_y = int(pos[1] + pos[3] / 2)

        # Copy blocks and build text list
        blocks = []
        textlist = []
        for blkitem in selected_blks:
            blk = copy.deepcopy(blkitem.blk)
            blk.adjust_pos(-pos_x, -pos_y)
            blocks.append(blk)
            textlist.append(blkitem.toPlainText().strip())

        # Store in ClipboardService
        if self._clipboard_svc:
            self._clipboard_svc.copy_blocks(blocks)

        # Copy text to system clipboard
        textlist = '\n'.join(textlist)
        self.app_clipboard.setText(textlist, QClipboard.Mode.Clipboard)

        return blocks

    def paste_blocks(self, pos: QPointF) -> List[TextBlkItem]:
        """
        Paste blocks from clipboard at the given position.

        Args:
            pos: Position to paste at (in screen coordinates)

        Returns:
            List of pasted TextBlkItem objects
        """
        if pos is None:
            pos_x, pos_y = 0, 0
        else:
            pos_x, pos_y = pos.x(), pos.y()
            pos_x = int(pos_x / self.canvas.scale_factor)
            pos_y = int(pos_y / self.canvas.scale_factor)

        blkitem_list = []

        # Get blocks from ClipboardService
        source_blocks = self._clipboard_svc.paste_blocks() if self._clipboard_svc else []

        for blk in source_blocks:
            blk = copy.deepcopy(blk)
            blk.adjust_pos(pos_x, pos_y)
            blkitem_list.append((blk, pos_x, pos_y))

        return blkitem_list

    def paste_text_to_selected(self, text: str, num_blocks: int) -> List[str]:
        """
        Prepare text for pasting to multiple selected blocks.

        Args:
            text: Text to paste
            num_blocks: Number of selected blocks

        Returns:
            List of text strings, one per block
        """
        if num_blocks <= 0:
            return []

        if num_blocks == 1:
            return [text]

        # Split text by newlines for multi-block paste
        text_list = text.rstrip().split('\n')
        num_text = len(text_list)

        if num_text > 1:
            if num_text > num_blocks:
                text_list = text_list[:num_blocks]
            elif num_text < num_blocks:
                text_list = text_list + [text_list[-1]] * (num_blocks - num_text)

        return text_list
