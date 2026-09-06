"""
Тесты: авторазмер шрифта после применения пресета из панели сохранённых шрифтов.

Вариант B: рефит живёт внутри ApplyFontformatCommand.redo(refit=True), поэтому
подогнанный размер шрифта принадлежит тому же undo-шагу, что и смена шрифта, и
redo симметрично повторяет рефит. Дегенеративный ReshapeItemCommand
подавляется флагом item._reshape_suppressed проверяемым в
SceneTextManager.onTextBlkItemReshaped.

Запуск (offscreen):
    cd j:\\Comic translate\\BallonsTranslator
    myenv\\Scripts\\python.exe -m pytest tests/ui/test_preset_font_autosize.py -v
"""

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtGui import QUndoStack

from utils.textblock import TextBlock
from utils.config import pcfg
from utils.fontformat import FontFormat
from ui.textitem import TextBlkItem
from ui.flow_textitem import FlowTextBlkItem
from ui.textedit_commands import ApplyFontformatCommand
from ui.scenetext_manager import SceneTextManager


# ── Helpers ───────────────────────────────────────────────────

def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_plain_item(scene, xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    blk = _make_blk(xyxy, text, font_size)
    item = TextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _make_flow_item(scene, xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    blk = _make_blk(xyxy, text, font_size)
    item = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _preset_font(font_size_px=60.0):
    fmt = FontFormat()
    fmt.font_family = "Arial"
    fmt.font_size = font_size_px
    return fmt


class FakeEdit:
    idx = 0

    def document(self):
        class _Doc:
            def clearUndoRedoStacks(self):
                pass
        return _Doc()


@pytest.fixture(autouse=True)
def _restore_pcfg():
    orig_flag = pcfg.let_fntsize_flag
    yield
    pcfg.let_fntsize_flag = orig_flag
# ── T1: flat shrink when preset larger than block ─────────────

class TestFlatShrink:
    def test_preset_larger_shrinks_flat(self, scene):
        pcfg.let_fntsize_flag = 0
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        item = _make_plain_item(scene, xyxy=(0, 0, 305, 92), text=text, font_size=14.0)
        item._auto_font_adjust = True
        fmt = _preset_font(font_size_px=60.0)

        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))

        final = item.get_fontformat().font_size
        assert final < fmt.font_size, (
            f"Flat block did not shrink on refit: preset={fmt.font_size:.1f}px final={final:.1f}px"
        )
        assert final >= 5.0, f"Font shrank below floor: {final:.1f}px"


# ── T2: global-size flag disables refit ───────────────────────

class TestGlobalSizeFlag:
    def test_flag_ok_preset_size_untouched(self, scene):
        pcfg.let_fntsize_flag = 1
        item = _make_plain_item(scene, xyxy=(0, 0, 305, 92),
                                text="Some long text that would overflow but must not auto-fit",
                                font_size=10.0)
        item._auto_font_adjust = True
        fmt = _preset_font(font_size_px=60.0)

        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))

        assert item.get_fontformat().font_size == fmt.font_size, (
            "let_fntsize_flag=1 must leave preset size untouched, "
            f"got {item.get_fontformat().font_size:.1f}px"
        )


# ── T3: per-block font lock disables refit ────────────────────

class TestFontLocked:
    def test_locked_untouched(self, scene):
        pcfg.let_fntsize_flag = 0
        item = _make_plain_item(scene, xyxy=(0, 0, 305, 92),
                                text="Some long text that would overflow but must not auto-fit",
                                font_size=10.0)
        item._auto_font_adjust = True
        item._font_size_locked = True
        fmt = _preset_font(font_size_px=60.0)

        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))

        assert item.get_fontformat().font_size == fmt.font_size, (
            "Locked block must not be auto-refitted, "
            f"got {item.get_fontformat().font_size:.1f}px"
        )
# ── T4: flow block refits against control points ──────────────

class TestFlowRefit:
    def test_flow_preset_refits_and_fits(self, scene):
        pcfg.let_fntsize_flag = 0
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        item = _make_flow_item(scene, xyxy=(0, 0, 305, 92), text=text, font_size=24.0)
        item._auto_font_adjust = True
        item._update_flow_layout()

        # Target geometry from control points (default rect points).
        ys = [p.y() for p in item._left_points] + [p.y() for p in item._right_points]
        xs = [p.x() for p in item._left_points] + [p.x() for p in item._right_points]
        target_h = max(ys) - min(ys)
        target_w = max(xs) - min(xs)

        fmt = _preset_font(font_size_px=120.0)
        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))

        final = item.get_fontformat().font_size
        assert final < fmt.font_size, (
            f"Flow block did not shrink on refit: preset={fmt.font_size:.1f}px final={final:.1f}px"
        )
        # Text fits within the boundary control points.
        assert item.layout.shrink_width <= target_w + 1, (
            f"Flow text overflowed width: {item.layout.shrink_width:.1f} > {target_w:.1f}"
        )
        assert item.layout.shrink_height <= target_h + 1, (
            f"Flow text overflowed height: {item.layout.shrink_height:.1f} > {target_h:.1f}"
        )
# ── T5: redo-symmetry — redo re-fits (NOT preset size) ────────

class TestRedoSymmetry:
    def test_undo_redo_reapplies_refit(self, scene):
        pcfg.let_fntsize_flag = 0
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        item = _make_plain_item(scene, xyxy=(0, 0, 305, 92), text=text, font_size=14.0)
        item._auto_font_adjust = True
        old_size = item.get_fontformat().font_size
        fmt = _preset_font(font_size_px=60.0)

        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))
        after_apply = item.get_fontformat().font_size
        assert after_apply < fmt.font_size, "apply must shrink"

        stack.undo()
        assert item.get_fontformat().font_size == pytest.approx(old_size), (
            "undo must restore original font size"
        )

        stack.redo()
        after_redo = item.get_fontformat().font_size
        assert after_redo < fmt.font_size, (
            "redo must re-fit size (Variant B), not leave preset size"
        )
        assert after_redo == pytest.approx(after_apply, abs=0.01), (
            "redo refit should match the initial apply refit"
        )

    def test_redo_refits_to_resized_geometry(self, scene):
        """Redo after undo captures the CURRENT block size — refit must track
        resizing done between undo and redo (Variant A loses the refit)."""
        pcfg.let_fntsize_flag = 0
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        item = _make_plain_item(scene, xyxy=(0, 0, 305, 92), text=text, font_size=14.0)
        item._auto_font_adjust = True
        fmt = _preset_font(font_size_px=60.0)

        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))
        after_apply = item.get_fontformat().font_size

        stack.undo()
        # User enlarges the block between undo and redo → redo must fit to the
        # new (larger) geometry, so the font can be larger than the first fit.
        item.set_size(500, 400)
        item._auto_font_adjust = True

        stack.redo()
        after_redo = item.get_fontformat().font_size
        assert after_redo < fmt.font_size
        # Larger block → refit allows a size at least as big as the first one.
        assert after_redo >= after_apply * 0.9, (
            "redo after enlarging the block should fit to the larger geometry"
        )


# ── T6: single undo step, no degenerate ReshapeItemCommand ────

class TestSingleUndoStep:
    def test_no_reshape_command_pushed(self, scene):
        pcfg.let_fntsize_flag = 0
        text = "БЫСТРЕЕ---БЫСТРЕЕ---БЫСТРЕЕ-- БЫСТРЕЕ-ПОКА ДИАНА ПОКРЫВАЕТ ЗАГАДОЧНУЮ КНИГУ"
        item = _make_flow_item(scene, xyxy=(0, 0, 305, 92), text=text, font_size=24.0)
        item._auto_font_adjust = True
        item._update_flow_layout()

        # Mimic SceneTextManager.onTextBlkItemReshaped as the reshaped consumer:
        # it must SKIP the suppressed signal during refit, so no command is pushed.
        pushed = []
        def on_reshaped(blk_item):
            if getattr(blk_item, "_reshape_suppressed", False):
                return
            pushed.append(blk_item)
        item.reshaped.connect(on_reshaped)

        fmt = _preset_font(font_size_px=90.0)
        stack = QUndoStack()
        stack.push(ApplyFontformatCommand([item], [FakeEdit()], fmt, refit=True))

        assert pushed == [], (
            "refit must raise no ReshapeItemCommand (reshaped suppressed)"
        )
        assert stack.count() == 1, (
            "exactly one command (the apply) should be on the stack"
        )


# ── T7: no selection → no-op, no crash ────────────────────────

class TestNoSelection:
    def test_empty_selection_noop(self):
        pcfg.let_fntsize_flag = 0
        m = types.SimpleNamespace()
        m.canvas = types.SimpleNamespace()
        m.canvas.selected_text_items = lambda: []
        m.pairwidget_list = []
        m.pushed = None

        def push(self, cmd, is_text=False):
            self.pushed = cmd
        m.push_undo_command = types.MethodType(push, m)

        # refit=True with empty selection → nothing pushed, no exception.
        SceneTextManager.apply_fontformat(m, _preset_font(font_size_px=60.0), refit=True)
        assert m.pushed is None

    def test_preset_handler_wires_refit_and_refreshes(self):
        """_on_preset_font_applied must call apply_fontformat(refit=True) and
        refresh the size display."""
        fmt = _preset_font(font_size_px=60.0)
        calls = {"apply": [], "refresh": 0}
        m = types.SimpleNamespace()
        m.calls = calls

        def apply(self, fontformat, refit=False):
            calls["apply"].append((fontformat, refit))

        # Handler accesses self.formatpanel.refresh_size_display().
        panel = types.SimpleNamespace()

        def refresh():
            calls["refresh"] += 1
        panel.refresh_size_display = refresh

        m.apply_fontformat = types.MethodType(apply, m)
        m.formatpanel = panel

        SceneTextManager._on_preset_font_applied(m, fmt)
        assert calls["apply"] == [(fmt, True)], "preset handler must pass refit=True"
        assert calls["refresh"] == 1, "preset handler must refresh size display"