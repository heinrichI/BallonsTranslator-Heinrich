"""Panel stroke display must reflect the SELECTION outline, not the block scalar.

Regression: after setting outline 0 on a selected part (block stroke 0.1),
the panel's stroke-width box still showed 0.1 while the text rendered with 0.

Extended: the display must also follow selection changes made in the paired
translation editor (e_trans) WITHOUT a block switch, and the display refresh
must never feed back into on_param_changed (format mutation / undo push).
"""
import copy
import os
import sys
from typing import Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QTextCursor, QTextDocument

from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from ui.flow_textitem import FlowTextBlkItem
import ui.shared_widget as SW


def _make_item(scene, text="Hello world", idx=0) -> FlowTextBlkItem:
    blk = TextBlock([0, 0, 400, 200])
    blk.lines = [[[0, 0], [400, 0], [400, 200], [0, 200]]]
    blk.translation = text
    blk.fontformat.size = 24.0
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


def _doc_span(item, panel_start: int, panel_end: int) -> Tuple[int, int]:
    """Item-document offsets covering [panel_start, panel_end) of the
    soft-hyphen-free text (the item document may contain soft hyphens, so
    outline ranges must be set in item-document coordinates)."""
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
    """Text-edit stand-in exposing only what the panel and
    TextBlkItem._effective_selection use from TransTextEdit: the
    selectionChanged signal (connect/disconnect/emit), textCursor() and
    toPlainText().

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

    def toPlainText(self) -> str:
        return self._doc.toPlainText()

    def textCursor(self) -> QTextCursor:
        return self._cursor

    def select_range(self, start: int, end: Optional[int] = None) -> None:
        """Emulate the user changing the selection in the editor."""
        self._cursor.setPosition(start)
        if end is not None:
            self._cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.selectionChanged.emit(self._cursor)


class _FakePairWidget:
    def __init__(self, e_trans: object = None) -> None:
        self.e_trans = e_trans


class _FakeStManager:
    def __init__(self) -> None:
        self.pairwidget_list: List[_FakePairWidget] = []


class _FakeCanvas:
    """Records push_undo_command calls: if the feedback loop fired (the
    refresh's programmatic setValue re-triggered on_param_changed), an undo
    command would be pushed here."""

    def __init__(self) -> None:
        self.undo_pushes: List[object] = []

    def push_undo_command(self, cmd) -> None:
        self.undo_pushes.append(cmd)

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


class TestPanelStrokeDisplay:
    def test_panel_shows_selection_width_not_block_scalar(self, qapp, scene):
        from utils import config as C

        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.1
        _select(item, 0, 5)
        item.setStrokeWidth(0.0, set_selected=True)
        assert item.blk.outline_ranges == [[0, 5, 0.0, [0, 0, 0]]]

        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            # box shows the selection's outline (0.0), not the block scalar (0.1)
            assert panel.strokeWidthBox.value() == 0.0
            # C.active_format must keep the block scalar — focus-out
            # copy-back deep-copies it into item.fontformat
            assert C.active_format.stroke_width == 0.1
        finally:
            panel.deleteLater()

    def test_panel_shows_block_scalar_without_selection(self, qapp, scene):
        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.3
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.strokeWidthBox.value() == 0.3
        finally:
            panel.deleteLater()

    def test_copy_back_does_not_clobber_block_scalar(self, qapp, scene):
        """Focus-out copy-back (set_textblk_item(None)) must not write the
        displayed selection value (0.0) into the block scalar (0.1)."""
        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.1
        _select(item, 0, 5)
        item.setStrokeWidth(0.0, set_selected=True)

        panel = _make_panel(qapp)
        try:
            if panel.global_format is None:  # set by mainwindow at runtime
                panel.global_format = FontFormat()
            panel.set_textblk_item(item)
            assert panel.strokeWidthBox.value() == 0.0
            # simulate focus leaving the whole panel
            panel.set_textblk_item(None)
            assert item.fontformat.stroke_width == 0.1
            assert item.blk.outline_ranges == [[0, 5, 0.0, [0, 0, 0]]]
        finally:
            panel.deleteLater()

    def test_panel_follows_e_trans_selection_changes(self, qapp, scene):
        """Changing the selection in the paired editor (no block switch)
        must update the stroke box/picker to the NEW selection's outline,
        and revert to the block scalars when the selection no longer has
        an outline (or is cleared)."""
        from utils import config as C

        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.1
        # Two spans with different outlines, set via canvas selection
        # exactly like the user would (in item-document coordinates):
        span_a = _doc_span(item, 0, 5)    # "Hello"
        span_b = _doc_span(item, 5, 11)   # "world"
        _select(item, *span_a)
        item.set_selection_outline(0.0, [0, 0, 0])
        _select(item, *span_b)
        item.set_selection_outline(0.5, [255, 0, 0])
        _clear_item_selection(item)
        ranges0 = copy.deepcopy(item.blk.outline_ranges)
        assert len(ranges0) == 2

        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            # No effective selection: block scalar.
            assert panel.strokeWidthBox.value() == 0.1
            # User selects "Hello" in the paired editor -> span A outline.
            e_trans.select_range(0, 5)
            assert panel.strokeWidthBox.value() == 0.0
            assert panel.strokeColorPicker.rgb() == (0, 0, 0)
            # User switches to "world" -> span B outline.
            e_trans.select_range(5, 11)
            assert panel.strokeWidthBox.value() == 0.5
            assert panel.strokeColorPicker.rgb() == (255, 0, 0)
            # User collapses the selection -> no outline -> block scalar.
            e_trans.select_range(3)
            assert panel.strokeWidthBox.value() == 0.1
            assert panel.strokeColorPicker.rgb() == tuple(item.fontformat.stroke_color())
            # Display-only: nothing was written to the format.
            assert item.blk.outline_ranges == ranges0
            assert item.fontformat.stroke_width == 0.1
            assert C.active_format.stroke_width == 0.1
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_refresh_cannot_feed_back_when_box_has_focus(self, qapp, scene):
        """Programmatic strokeWidthBox.setValue re-triggers editTextChanged
        -> SizeComboBox.on_text_changed -> param_changed -> on_param_changed
        when the box has focus. During a display refresh the
        _updating_stroke_display flag must swallow that, so the format (and
        the undo stack) stay untouched."""
        from utils import config as C

        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.1
        span_a = _doc_span(item, 0, 5)
        _select(item, *span_a)
        item.set_selection_outline(0.2, [0, 0, 0])
        _clear_item_selection(item)
        ranges0 = copy.deepcopy(item.blk.outline_ranges)

        e_trans = FakeTransEdit(item.document().toPlainText().replace('\xad', ''))
        prev_stm = _wire_pairwidgets({item.idx: e_trans})
        fake_canvas = _FakeCanvas()
        prev_canvas = SW.canvas
        SW.canvas = fake_canvas
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item)
            assert panel.strokeWidthBox.value() == 0.1
            # Simulate the only situation where the feedback loop can fire:
            # the stroke box has focus at the moment the refresh writes the
            # new value (user typing in the box while the selection is
            # changed programmatically).
            orig_has_focus = panel.strokeWidthBox.hasFocus
            panel.strokeWidthBox.hasFocus = lambda: True
            try:
                e_trans.select_range(0, 5)
            finally:
                panel.strokeWidthBox.hasFocus = orig_has_focus
            # Display followed the selection...
            assert panel.strokeWidthBox.value() == 0.2
            # ...without re-applying it to the format: without the flag the
            # re-emitted param_changed would run ffmt_change_stroke_width
            # and push an undo command onto the canvas.
            assert fake_canvas.undo_pushes == []
            assert item.blk.outline_ranges == ranges0
            assert C.active_format.stroke_width == 0.1
        finally:
            SW.canvas = prev_canvas
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_updating_flag_suppresses_on_param_changed(self, qapp, scene):
        """While _updating_stroke_display is set, on_param_changed must not
        apply anything to C.active_format / the item."""
        from utils import config as C

        item = _make_item(scene, text="Hello world")
        item.fontformat.stroke_width = 0.1
        panel = _make_panel(qapp)
        try:
            if panel.global_format is None:  # set by mainwindow at runtime
                panel.global_format = FontFormat()
            panel.set_textblk_item(item)
            before_width = C.active_format.stroke_width
            before_srgb = list(C.active_format.srgb)
            panel._updating_stroke_display = True
            try:
                panel.on_param_changed('stroke_width', 9.9)
                panel.on_param_changed('srgb', (1, 2, 3))
            finally:
                panel._updating_stroke_display = False
            assert C.active_format.stroke_width == before_width
            assert list(C.active_format.srgb) == before_srgb
            assert item.blk.outline_ranges == []
            assert item.fontformat.stroke_width == 0.1
        finally:
            panel.deleteLater()

    def test_block_switch_disconnects_previous_editor(self, qapp, scene):
        """Switching blocks must disconnect the previous block's e_trans:
        a stale editor must not update the panel, and connections must not
        accumulate on the editor of the (re-)selected block."""
        item1 = _make_item(scene, text="Hello world", idx=0)
        item2 = _make_item(scene, text="Second block", idx=1)
        item1.fontformat.stroke_width = 0.1
        item2.fontformat.stroke_width = 0.3

        e1 = FakeTransEdit("Hello world")
        e2 = FakeTransEdit("Second block")
        prev_stm = _wire_pairwidgets({0: e1, 1: e2})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item1)
            assert panel._stroke_sel_edit is e1
            panel.set_textblk_item(item2)
            assert panel._stroke_sel_edit is e2
            # e1 is no longer connected: its selection change must not
            # touch the panel.
            e1.select_range(0, 5)
            assert panel.strokeWidthBox.value() == 0.3

            # No accumulation: after item1 -> item2 -> item1 -> item2 the
            # handler must run exactly once per e2 emission.
            panel.set_textblk_item(item1)
            panel.set_textblk_item(item2)
            sets: List[float] = []
            orig_set_value = panel.strokeWidthBox.setValue
            panel.strokeWidthBox.setValue = lambda v: (
                sets.append(v), orig_set_value(v))[1]
            try:
                e2.select_range(0, 5)  # "Second" — no outline -> fallback
            finally:
                panel.strokeWidthBox.setValue = orig_set_value
            assert sets == [0.3]  # exactly one handler invocation
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

class TestDeletedEditor:
    """The paired e_trans C++ object can be destroyed out from under the
    panel (a page switch deletes the pair widgets while the panel and
    pairwidget_list keep Python references). Any later block switch must
    not raise RuntimeError.

    Regression: plain click on a block raised
    'wrapped C/C++ object of type TransTextEdit has been deleted' from
    selectionChanged.disconnect in _disconnect_stroke_selection_editor."""

    def test_block_switch_after_editor_deletion(self, qapp, scene):
        from PyQt6 import sip

        item1 = _make_item(scene, text="Hello world", idx=0)
        item2 = _make_item(scene, text="Second block", idx=1)
        item1.fontformat.stroke_width = 0.1
        item2.fontformat.stroke_width = 0.3

        e1 = FakeTransEdit("Hello world")
        e2 = FakeTransEdit("Second block")
        prev_stm = _wire_pairwidgets({0: e1, 1: e2})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item1)
            assert panel._stroke_sel_edit is e1

            # Page switch: the pair widgets' native objects are destroyed,
            # the Python wrappers in pairwidget_list stay around.
            sip.delete(e1)

            # Plain click on another block -> selection change -> panel
            # switch: the disconnect of the DEAD editor must not raise.
            panel.set_textblk_item(item2)
            assert panel._stroke_sel_edit is e2

            # Switching BACK: _get_stroke_selection_editor must report the
            # dead editor instead of crashing on connect.
            panel.set_textblk_item(item1)
            assert panel._stroke_sel_edit is None
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()

    def test_deleted_current_editor_not_reconnected(self, qapp, scene):
        from PyQt6 import sip

        item1 = _make_item(scene, text="Hello world", idx=0)
        e1 = FakeTransEdit("Hello world")
        prev_stm = _wire_pairwidgets({0: e1})
        panel = _make_panel(qapp)
        try:
            panel.set_textblk_item(item1)
            assert panel._stroke_sel_edit is e1
            sip.delete(e1)
            # The destroyed signal must clear the reference proactively,
            # at the moment of deletion — not only on the next switch
            # (that would mean the backstop, not the cleanup path, worked).
            assert panel._stroke_sel_edit is None
            # Re-selecting the same block must not connect the dead editor.
            panel.set_textblk_item(item1)
            assert panel._stroke_sel_edit is None
        finally:
            SW.st_manager = prev_stm
            panel.deleteLater()
