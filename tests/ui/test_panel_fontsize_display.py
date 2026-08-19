"""Panel font-size display must follow the LIVE cursor position.

Regression: after changing the size of a selected word (per-range sizes live
in the block document's char formats, setFontSize -> set_cursor_cfmt), the
font-size box kept showing the changed word's size after the cursor moved to
an UNCHANGED word — the box only tracked the block scalar left by the last
size op. The box must show the size under the current cursor:

- selection in the paired editor (e_trans) or on the canvas item -> the
  selection's size (first char's size + '+' when the range is mixed);
- bare cursor in the focused e_trans / editing item / at last endEdit ->
  the char size at that position;
- no live cursor -> the block scalar (previous behavior).

Display-only: C.active_format keeps the block scalar (focus-out copy-back)
and a programmatic box write must never feed back into on_param_changed.

Run:
    myenv/Scripts/python.exe -m pytest tests/ui/test_panel_fontsize_display.py -v
"""
import os
import sys
from typing import Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QFocusEvent, QKeyEvent, QTextCursor, QTextDocument
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication

import ui.shared_widget as SW
from utils.textblock import TextBlock
from utils.fontformat import FontFormat, pt2px
from ui.flow_textitem import FlowTextBlkItem


def _make_item(scene, text="Hello world", idx=0) -> FlowTextBlkItem:
    blk = TextBlock([0, 0, 400, 200])
    blk.lines = [[[0, 0], [400, 0], [400, 200], [0, 200]]]
    blk.translation = text
    blk.fontformat.font_size = pt2px(24.0)
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [0, 0, 400, 200]
    item = FlowTextBlkItem(blk, idx=idx, show_rect=False)
    scene.addItem(item)
    return item


def _select(item, s, e):
    cur = item.textCursor()
    cur.setPosition(s)
    cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
    item.setTextCursor(cur)


def _clear_item_selection(item):
    item.setTextCursor(QTextCursor(item.document()))


def _doc_span(item, panel_start: int, panel_end: int):
    """Item-document offsets covering [panel_start, panel_end) of the
    soft-hyphen-free text (flow documents contain soft hyphens)."""
    text = item.document().toPlainText()
    return (item._panel_pos_to_doc_start(text, panel_start),
            item._panel_pos_to_doc_end(text, panel_end))


def _make_panel(qapp):
    """FontFormatPanel outside the main window (runtime-only hooks stubbed)."""
    import utils.shared as shared
    if not hasattr(shared, 'register_view_widget'):
        shared.register_view_widget = lambda *a, **k: None
    from ui.text_panel import FontFormatPanel
    from utils import config as C
    if C.active_format is None:
        C.active_format = FontFormat()
    return FontFormatPanel(qapp)


class FakeTransEdit(QObject):
    """Text-edit stand-in exposing what the panel and
    TextBlkItem.get_cursor_font_range use from TransTextEdit: the
    selectionChanged signal, textCursor(), toPlainText() and hasFocus().

    A real QTextEdit deadlocks on the offscreen platform when a Python
    slot runs inside the synchronous C++ emit of setTextCursor, so the
    selection is changed here by updating the document cursor and emitting
    the Python signal the way Qt would.
    """
    selectionChanged = Signal(object)  # type: ignore[attr-defined]

    def __init__(self, text: str) -> None:
        super().__init__()
        self._doc = QTextDocument()
        self._doc.setPlainText(text)
        self._cursor = QTextCursor(self._doc)
        self._has_focus = False

    def toPlainText(self) -> str:
        return self._doc.toPlainText()

    def textCursor(self) -> QTextCursor:
        return self._cursor

    def hasFocus(self) -> bool:
        return self._has_focus

    def select_range(self, start: int, end: Optional[int] = None) -> None:
        """Emulate the user changing the selection in the editor (a user
        interaction always leaves focus in the editor)."""
        self._cursor.setPosition(start)
        if end is not None:
            self._cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._has_focus = True
        self.selectionChanged.emit(self._cursor)

    def clear_focus(self) -> None:
        self._has_focus = False


class _FakePairWidget:
    def __init__(self, e_trans: object = None) -> None:
        self.e_trans = e_trans


class _FakeStManager:
    def __init__(self) -> None:
        self.pairwidget_list: List[_FakePairWidget] = []


class _FakeCanvas:
    """Records push_undo_command calls: if the feedback loop fired (the
    refresh's programmatic setCurrentText re-triggered on_param_changed),
    an undo command would be pushed here."""

    def __init__(self) -> None:
        self.undo_pushes: List[object] = []

    def push_undo_command(self, cmd) -> None:
        self.undo_pushes.append(cmd)
        # The real canvas pushes onto a QUndoStack, which runs cmd.redo()
        # immediately (TextStyleUndoCommand applies lazily).
        if cmd is not None:
            cmd.redo()

    def hasFocus(self) -> bool:
        return False

    def setFocus(self) -> None:
        pass


def _wire_pairwidgets(mapping: Dict[int, object]) -> object:
    """Point SW.st_manager at a fake manager whose
    pairwidget_list[i].e_trans follows *mapping*. Returns the previous
    SW.st_manager so tests can restore it."""
    stm = _FakeStManager()
    for idx, e_trans in mapping.items():
        while len(stm.pairwidget_list) <= idx:
            stm.pairwidget_list.append(_FakePairWidget())
        stm.pairwidget_list[idx].e_trans = e_trans
    prev = SW.st_manager
    SW.st_manager = stm
    return prev


def _make_sized_item(scene):
    """'Hello world' with panel 'Hello' (5 chars) sized 30pt while the rest
    stays 24pt; the block scalar now tracks the last op (30pt) — exactly the
    state left by the user's size change."""
    item = _make_item(scene)
    s, e = _doc_span(item, 0, 5)
    _select(item, s, e)
    item.setFontSize(30.0, set_selected=True, restore_cursor=True)
    _clear_item_selection(item)
    assert item.get_fontformat().size_pt == 30.0
    return item


class TestGetCursorFontSize:
    """Item level: get_cursor_font_size() reports the live cursor's size."""

    def test_no_live_cursor_returns_none(self, qapp, scene):
        item = _make_sized_item(scene)
        prev_stm, prev_canvas = SW.st_manager, SW.canvas
        SW.st_manager, SW.canvas = None, None
        try:
            assert item.get_cursor_font_size() is None
        finally:
            SW.st_manager, SW.canvas = prev_stm, prev_canvas

    def test_selection_reports_uniform_size(self, qapp, scene):
        item = _make_sized_item(scene)
        s, e = _doc_span(item, 5, 11)  # "world" — never resized
        _select(item, s, e)
        assert item.get_cursor_font_size() == (24.0, False)
        s, e = _doc_span(item, 0, 5)  # "Hello" — resized to 30
        _select(item, s, e)
        assert item.get_cursor_font_size() == (30.0, False)

    def test_mixed_selection_reports_plus(self, qapp, scene):
        item = _make_sized_item(scene)
        doc = item.document()
        _select(item, 0, doc.rootFrame().lastPosition())
        # first char is 30pt, range also contains 24pt chars -> mixed
        assert item.get_cursor_font_size() == (30.0, True)

    def test_bare_cursor_after_endedit_reports_char_size(self, qapp, scene):
        """Canvas workflow: the user ends editing with a BARE cursor on an
        unchanged word — the display must show THAT word's size, not the
        block scalar left by the size op."""
        item = _make_sized_item(scene)
        prev_stm, prev_canvas = SW.st_manager, SW.canvas
        SW.st_manager, SW.canvas = None, None
        try:
            s, e = _doc_span(item, 5, 11)  # "world"
            cur = item.textCursor()
            cur.setPosition(s + 2)
            item.setTextCursor(cur)
            item.endEdit()  # saves _last_cursor_state (bare cursor)
            assert item.get_cursor_font_size() == (24.0, False)
            # move the bare cursor into the resized word
            cur = item.textCursor()
            cur.setPosition(2)
            item.setTextCursor(cur)
            item.endEdit()
            assert item.get_cursor_font_size() == (30.0, False)
        finally:
            SW.st_manager, SW.canvas = prev_stm, prev_canvas


class TestPanelFontSizeDisplay:
    """Panel level: the font-size box follows the live cursor."""

    def test_box_keeps_block_scalar_without_live_cursor(self, qapp, scene):
        item = _make_sized_item(scene)
        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            # No selection, no focus in e_trans, no last cursor -> block scalar.
            assert panel.fontsizebox.fcombobox.currentText() == "30"
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_box_follows_e_trans_selection_to_unchanged_word(self, qapp, scene):
        """The reported bug: after resizing 'Hello', selecting 'world' in
        the paired editor must show 24 (its real size), not 30 (the block
        scalar left by the op)."""
        item = _make_sized_item(scene)
        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.fontsizebox.fcombobox.currentText() == "30"
            # User selects "world" in the paired editor.
            e_trans.select_range(5, 11)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
            # Back to "Hello".
            e_trans.select_range(0, 5)
            assert panel.fontsizebox.fcombobox.currentText() == "30"
            # Mixed range -> first char's size + '+' (up/down then use
            # rel_font_size scaling).
            e_trans.select_range(0, 11)
            assert panel.fontsizebox.fcombobox.currentText() == "30+"
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_box_follows_bare_cursor_in_focused_editor(self, qapp, scene):
        item = _make_sized_item(scene)
        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            # Click into "world" (bare cursor, editor gains focus).
            e_trans.select_range(7)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
            # Click into "Hello".
            e_trans.select_range(2)
            assert panel.fontsizebox.fcombobox.currentText() == "30"
            # Focus left the editor (e.g. back to the canvas) and no
            # selection: the stale editor cursor must not drive the display.
            e_trans.clear_focus()
            panel._refresh_font_size_display()
            assert panel.fontsizebox.fcombobox.currentText() == "30"
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_box_follows_last_canvas_cursor_after_block_switch(self, qapp, scene):
        """Canvas workflow: the user ends editing with a bare cursor on
        'world'; switching back to the block (or any refresh) must show
        24, not the 30 left by the size op."""
        item = _make_sized_item(scene)
        s, e = _doc_span(item, 5, 11)
        cur = item.textCursor()
        cur.setPosition(s + 2)
        item.setTextCursor(cur)
        item.endEdit()

        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_focusin_on_box_refreshes_display(self, qapp, scene):
        """Canvas cursor moves emit no signal: when the user focuses the
        size box, the display must refresh (eventFilter FocusIn)."""
        item = _make_sized_item(scene)
        s, e = _doc_span(item, 5, 11)
        cur = item.textCursor()
        cur.setPosition(s + 2)
        item.setTextCursor(cur)
        item.endEdit()

        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
            # Simulate the user clicking into the size box.
            box = panel.fontsizebox.fcombobox
            app = QApplication.instance()
            app.sendEvent(box, QFocusEvent(QFocusEvent.Type.FocusIn))
            # The display is still correct (no regression in the refresh path
            # itself); the value is unchanged because the cursor did not move.
            assert box.currentText() == "24"
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_refresh_cannot_feed_back_when_box_has_focus(self, qapp, scene):
        """Programmatic setCurrentText re-triggers editTextChanged ->
        SizeComboBox.on_text_changed -> param_changed -> on_param_changed
        when the box has focus. The _updating_stroke_display flag must
        swallow it, so the format (and the undo stack) stay untouched."""
        from utils import config as C

        item = _make_sized_item(scene)
        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        fake_canvas = _FakeCanvas()
        prev_canvas = SW.canvas
        SW.canvas = fake_canvas
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.fontsizebox.fcombobox.currentText() == "30"
            scalar_before = item.fontformat.font_size
            # The box has focus at the moment the refresh writes the value.
            box = panel.fontsizebox.fcombobox
            orig_has_focus = box.hasFocus
            box.hasFocus = lambda: True
            try:
                e_trans.select_range(5, 11)
            finally:
                box.hasFocus = orig_has_focus
            # Display followed the selection...
            assert box.currentText() == "24"
            # ...without re-applying it: no undo push, no format mutation.
            assert fake_canvas.undo_pushes == []
            assert item.fontformat.font_size == scalar_before
            assert C.active_format.font_size == scalar_before
        finally:
            SW.canvas = prev_canvas
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_after_panel_size_op_box_follows_cursor(self, qapp, scene):
        """End-to-end: resize 'Hello' via the panel (canvas selection),
        then move the cursor to 'world' in the paired editor — the box
        must end at 24, not the 30 just applied."""
        item = _make_item(scene)
        s, e = _doc_span(item, 0, 5)  # canvas selection of "Hello"
        _select(item, s, e)

        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        fake_canvas = _FakeCanvas()
        prev_canvas = SW.canvas
        SW.canvas = fake_canvas
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
            # User types 30 in the size box (canvas selection active).
            panel.on_param_changed('font_size', 30.0)
            assert item.get_fontformat().size_pt == 30.0
            assert len(fake_canvas.undo_pushes) == 1
            assert panel.fontsizebox.fcombobox.currentText() == "30"
            # User now clicks "world" in the paired editor.
            e_trans.select_range(5, 11)
            assert panel.fontsizebox.fcombobox.currentText() == "24"
        finally:
            SW.canvas = prev_canvas
            SW.st_manager = prev_stm
            panel.deleteLater()
