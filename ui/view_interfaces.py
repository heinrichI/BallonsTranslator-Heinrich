"""
View Interfaces for MVP pattern.

Defines abstract interfaces that Views must implement.
Presenters depend ONLY on these interfaces, NOT on concrete View classes.

Pattern:
  Model < Presenter > View (Interface) < View (PyQt)

Rules:
- View Interface has NO Qt dependencies (only signals/methods)
- View (PyQt) implements the View Interface
- Presenter depends on View Interface, not on concrete View
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class ITextBlockView(ABC):
    """
    Interface for TextBlkItem (View).
    
    Defines the contract between TextBlockPresenter and TextBlkItem.
    """

    @abstractmethod
    def toPlainText(self) -> str:
        """Return plain text content."""
        pass

    @abstractmethod
    def toHtml(self) -> str:
        """Return HTML content."""
        pass

    @abstractmethod
    def setPlainText(self, text: str):
        """Set plain text content."""
        pass

    @abstractmethod
    def setHtml(self, html: str):
        """Set HTML content."""
        pass

    @abstractmethod
    def setFontSize(self, size_pt: float):
        """Set font size in points."""
        pass

    @abstractmethod
    def setFontFamily(self, family: str):
        """Set font family."""
        pass

    @abstractmethod
    def setAlignment(self, alignment: int):
        """Set text alignment."""
        pass

    @abstractmethod
    def setVertical(self, vertical: bool):
        """Set vertical writing mode."""
        pass

    @abstractmethod
    def setSelected(self, selected: bool):
        """Set selection state."""
        pass

    @abstractmethod
    def isSelected(self) -> bool:
        """Return True if selected."""
        pass

    @abstractmethod
    def startEdit(self):
        """Start editing mode."""
        pass

    @abstractmethod
    def endEdit(self):
        """End editing mode."""
        pass

    @abstractmethod
    def is_editting(self) -> bool:
        """Return True if in editing mode."""
        pass

    @abstractmethod
    def set_fontformat(self, fontformat):
        """Set font format."""
        pass

    @abstractmethod
    def get_fontformat(self):
        """Get font format."""
        pass

    @property
    @abstractmethod
    def fontformat(self):
        """Get font format property."""
        pass

    @property
    @abstractmethod
    def idx(self) -> int:
        """Get block index."""
        pass


class ISceneView(ABC):
    """
    Interface for Canvas (View).
    
    Defines the contract between ScenePresenter and Canvas.
    """

    @abstractmethod
    def selected_text_items(self, sort: bool = True) -> list:
        """Return list of selected text items."""
        pass

    @abstractmethod
    def clearSelection(self):
        """Clear all selections."""
        pass

    @abstractmethod
    def push_undo_command(self, command):
        """Push command to undo stack."""
        pass

    @abstractmethod
    def textEditMode(self) -> bool:
        """Return True if in text edit mode."""
        pass

    @abstractmethod
    def textblock_mode(self) -> bool:
        """Return True if in textblock mode."""
        pass

    @property
    @abstractmethod
    def editing_textblkitem(self):
        """Get currently editing text block item."""
        pass

    @editing_textblkitem.setter
    @abstractmethod
    def editing_textblkitem(self, value):
        """Set currently editing text block item."""
        pass

    @property
    @abstractmethod
    def textLayer(self):
        """Get text layer."""
        pass

    @property
    @abstractmethod
    def gv(self):
        """Get graphics view."""
        pass

    @property
    @abstractmethod
    def scale_factor(self) -> float:
        """Get scale factor."""
        pass

    @property
    @abstractmethod
    def imgtrans_proj(self):
        """Get image translation project."""
        pass

    @property
    @abstractmethod
    def clipboard_blks(self) -> list:
        """Get clipboard blocks."""
        pass

    @abstractmethod
    def removeItem(self, item):
        """Remove item from scene."""
        pass

    @abstractmethod
    def text_change_unsaved(self) -> bool:
        """Return True if there are unsaved text changes."""
        pass

    @abstractmethod
    def clear_text_stack(self):
        """Clear text undo stack."""
        pass

    @abstractmethod
    def undo_textedit(self):
        """Undo text edit."""
        pass

    @abstractmethod
    def redo_textedit(self):
        """Redo text edit."""
        pass

    @abstractmethod
    def push_text_command(self, command=None, update_pushed_step: bool = False):
        """Push text command."""
        pass


class IFlowBlockView(ITextBlockView):
    """
    Interface for FlowTextBlkItem (View).
    
    Extends ITextBlockView with flow-specific methods.
    """

    @abstractmethod
    def get_control_points(self):
        """Get control points for flow layout."""
        pass

    @abstractmethod
    def set_control_points(self, left_points, right_points):
        """Set control points for flow layout."""
        pass

    @abstractmethod
    def save_flow_points(self):
        """Save flow points to model."""
        pass

    @abstractmethod
    def _init_points_from_rect(self, rect):
        """Initialize flow points from rectangle."""
        pass

    @property
    @abstractmethod
    def _left_points(self) -> list:
        """Get left boundary points."""
        pass

    @property
    @abstractmethod
    def _right_points(self) -> list:
        """Get right boundary points."""
        pass

    @abstractmethod
    def absBoundingRect(self, qrect: bool = False):
        """Get absolute bounding rectangle."""
        pass

    @abstractmethod
    def updateBlkFormat(self):
        """Update block format."""
        pass
