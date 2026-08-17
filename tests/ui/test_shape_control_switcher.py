"""
Tests for ShapeControlSwitcher (dual shape-control) and the flow-mode toggle wiring.

Run with:
    set QT_QPA_PLATFORM=offscreen
    cd j:\Comic translate\BallonsTranslator
    myenv\Scripts\python.exe -m pytest tests/ui/test_shape_control_switcher.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsPixmapItem, QMenu
from qtpy.QtCore import QPointF, QPoint, Qt, QRectF
from qtpy.QtTest import QTest
from types import SimpleNamespace, MethodType
from unittest.mock import MagicMock

from utils.textblock import TextBlock
from ui.textitem import TextBlkItem
from ui.flow_textitem import FlowTextBlkItem
from ui.texteditshapecontrol import TextBlkShapeControl
from ui.flow_shapecontrol import FlowShapeControl
from ui.shape_control_switcher import ShapeControlSwitcher
import ui.scenetext_manager as stm_mod


# (фикстуры qapp/scene — tests/ui/conftest.py)

def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_flow_item(scene, idx=0, **kwargs):
    blk = _make_blk(**kwargs)
    blk.is_flow_mode = True
    item = FlowTextBlkItem(blk, idx=idx, show_rect=False)
    scene.addItem(item)
    return item


def _make_normal_item(scene, idx=0, **kwargs):
    blk = _make_blk(**kwargs)
    blk.is_flow_mode = False
    item = TextBlkItem(blk, idx=idx, show_rect=True)
    scene.addItem(item)
    return item


# ── ShapeControlSwitcher ──────────────────────────────────────

class TestShapeControlSwitcher:

    def _make_switcher(self, scene):
        base = QGraphicsRectItem()
        scene.addItem(base)
        flow_ctrl = FlowShapeControl(None)
        legacy_ctrl = TextBlkShapeControl(None)
        flow_ctrl.setParentItem(base)
        legacy_ctrl.setParentItem(base)
        canvas = SimpleNamespace(scale_factor=1.0)
        sw = ShapeControlSwitcher(flow_ctrl, legacy_ctrl, canvas)
        return sw, flow_ctrl, legacy_ctrl

    def test_flow_item_uses_flow_control(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        item = _make_flow_item(scene)
        sw.setBlkItem(item)
        assert sw._active is flow_ctrl
        assert flow_ctrl.blk_item is item
        assert item.under_ctrl is True

    def test_normal_item_switches_to_legacy_control(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        flow_item = _make_flow_item(scene)
        sw.setBlkItem(flow_item)
        normal_item = _make_normal_item(scene)
        sw.setBlkItem(normal_item)
        assert sw._active is legacy_ctrl
        assert legacy_ctrl.blk_item is normal_item
        assert flow_ctrl.blk_item is None  # old control released
        assert flow_item.under_ctrl is False
        assert normal_item.under_ctrl is True

    def test_none_keeps_current_control(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        normal_item = _make_normal_item(scene)
        sw.setBlkItem(normal_item)
        sw.setBlkItem(None)
        assert sw._active is legacy_ctrl
        assert legacy_ctrl.blk_item is None

    def test_switch_back_to_flow_control(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        normal_item = _make_normal_item(scene)
        flow_item = _make_flow_item(scene)
        sw.setBlkItem(normal_item)
        sw.setBlkItem(flow_item)
        assert sw._active is flow_ctrl
        assert flow_ctrl.blk_item is flow_item
        assert legacy_ctrl.blk_item is None

    def test_method_delegation(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        normal_item = _make_normal_item(scene)
        sw.setBlkItem(normal_item)
        assert sw.isVisible() == legacy_ctrl.isVisible()
        assert sw.blk_item is normal_item
        sw.updateBoundingRect()  # must not raise
        sw.updateScale(1.0)
        sw.startEditing()
        sw.endEditing()

    def test_legacy_handleContextMenu_finds_normal_item(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        normal_item = _make_normal_item(scene)
        sw.setBlkItem(normal_item)
        # Plain QGraphicsScene has no build_context_menu/exec_context_menu, so
        # showNormalContextMenu returns without showing a blocking menu.
        assert legacy_ctrl.handleContextMenu(QPointF(50, 50), QPoint(50, 50)) is True
        assert normal_item.isSelected()

    def test_legacy_handleContextMenu_misses_empty_area(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        _make_normal_item(scene)
        sw.setBlkItem(None)
        assert legacy_ctrl.handleContextMenu(QPointF(9000, 9000), QPoint(9000, 9000)) is False

    def test_flow_handleContextMenu_ignores_normal_item(self, scene):
        sw, flow_ctrl, legacy_ctrl = self._make_switcher(scene)
        normal_item = _make_normal_item(scene)
        sw.setBlkItem(normal_item)
        # Active control is legacy; the flow control must not claim normal blocks.
        assert flow_ctrl.handleContextMenu(QPointF(50, 50), QPoint(50, 50)) is False


# ── Menu helper ───────────────────────────────────────────────

class TestToggleFlowMenu:

    def test_injectToggleFlowMenu_prepends_action(self, scene, qapp):
        item = _make_normal_item(scene)
        menu = QMenu()
        menu.addAction("Copy")
        item.injectToggleFlowMenu(menu)
        assert menu.actions()[0].text() == "Toggle Flow Mode"
        assert menu.actions()[1].isSeparator()
        assert menu.actions()[2].text() == "Copy"

    def test_injectToggleFlowMenu_emits_signal(self, scene, qapp):
        item = _make_normal_item(scene)
        emitted = []
        item.toggle_flow_mode_requested.connect(lambda idx: emitted.append(idx))
        menu = QMenu()
        item.injectToggleFlowMenu(menu)
        menu.actions()[0].trigger()
        assert emitted == [0]


# ── Persistence (is_flow_mode round-trip) ────────────────────

class TestIsFlowModePersistence:

    def _roundtrip(self, blk):
        import json
        from utils.proj_imgtrans import TextBlkEncoder
        s = json.dumps(blk, cls=TextBlkEncoder)
        d = json.loads(s)
        return TextBlock(**d)

    def test_normal_mode_roundtrips(self):
        blk = _make_blk()
        blk.is_flow_mode = False
        restored = self._roundtrip(blk)
        assert restored.is_flow_mode is False

    def test_flow_mode_roundtrips(self):
        blk = _make_blk()
        blk.is_flow_mode = True
        restored = self._roundtrip(blk)
        assert restored.is_flow_mode is True

    def test_old_project_without_key_defaults_to_flow(self):
        blk = _make_blk()
        import json
        from utils.proj_imgtrans import TextBlkEncoder
        d = json.loads(json.dumps(blk, cls=TextBlkEncoder))
        d.pop('is_flow_mode', None)
        restored = TextBlock(**d)
        assert restored.is_flow_mode is True


# ── Toggle wiring (SceneTextManager fakes) ────────────────────

def _fake_manager_with_item(scene, item=None):
    """Build a SimpleNamespace SceneTextManager fake holding one real block item."""
    if item is None:
        item = _make_normal_item(scene)
    fake_self = SimpleNamespace(
        textblk_item_list=[item],
        canvas=SimpleNamespace(
            remove_item=lambda item: None,
            add_item_to_text_layer=lambda item: None,
            editing_textblkitem=None,
        ),
        txtblkShapeControl=MagicMock(),
    )
    for name in [
        "onTextBlkItemBeginEdit", "onTextBlkItemEndEdit", "onTextBlkItemHoverEnter",
        "onLeftbuttonPressed", "onTextBlkItemMoving", "onTextBlkItemMoved",
        "onTextBlkItemReshaped", "onTextBlkItemRotated", "on_push_textitem_undostack",
        "on_textedit_undo", "on_textedit_redo", "on_propagate_textitem_edit",
        "onTextBlkItemSizeChanged", "onBlkitemPaste", "toggle_block_flow_mode",
    ]:
        setattr(fake_self, name, MagicMock())
    # Bind the real reconnect method so toggle wiring is exercised end-to-end.
    fake_self._reconnect_block_signals = MethodType(
        stm_mod.SceneTextManager._reconnect_block_signals, fake_self)
    return fake_self


class TestToggleBlockFlowMode:

    def test_normal_to_flow(self, scene):
        fake_self = _fake_manager_with_item(scene)
        stm_mod.SceneTextManager.toggle_block_flow_mode(fake_self, 0)
        new_item = fake_self.textblk_item_list[0]
        assert isinstance(new_item, FlowTextBlkItem)
        assert new_item.blk.is_flow_mode is True
        fake_self.txtblkShapeControl.setBlkItem.assert_called_with(new_item)

    def test_flow_to_normal_to_flow_roundtrip(self, scene):
        fake_self = _fake_manager_with_item(scene)  # starts as normal TextBlkItem
        stm_mod.SceneTextManager.toggle_block_flow_mode(fake_self, 0)
        flow_item = fake_self.textblk_item_list[0]
        assert isinstance(flow_item, FlowTextBlkItem)
        assert flow_item.blk.is_flow_mode is True

        stm_mod.SceneTextManager.toggle_block_flow_mode(fake_self, 0)
        normal_item = fake_self.textblk_item_list[0]
        assert isinstance(normal_item, TextBlkItem) and not isinstance(normal_item, FlowTextBlkItem)
        assert normal_item.blk.is_flow_mode is False
        # draw_rect is preserved from the source item (not forced on)
        assert normal_item.draw_rect is True

    def test_toggle_does_not_force_draw_rect(self, scene):
        # A flow block with show_rect=False must convert to a normal block
        # whose border is NOT permanently forced on (the orange frame).
        flow_item = _make_flow_item(scene)
        assert flow_item.draw_rect is False
        fake_self = _fake_manager_with_item(scene, item=flow_item)
        stm_mod.SceneTextManager.toggle_block_flow_mode(fake_self, 0)
        normal_item = fake_self.textblk_item_list[0]
        assert isinstance(normal_item, TextBlkItem) and not isinstance(normal_item, FlowTextBlkItem)
        assert normal_item.draw_rect is False

    def test_reconnect_block_signals_wires_toggle(self, scene):
        fake_self = _fake_manager_with_item(scene)
        stm_mod.SceneTextManager._reconnect_block_signals(fake_self, fake_self.textblk_item_list[0])
        item = fake_self.textblk_item_list[0]
        item.toggle_flow_mode_requested.emit(item.idx)
        fake_self.toggle_block_flow_mode.assert_called_once_with(item.idx)

    def test_toggle_out_of_range_is_noop(self, scene):
        fake_self = _fake_manager_with_item(scene)
        stm_mod.SceneTextManager.toggle_block_flow_mode(fake_self, 99)  # must not raise
        assert isinstance(fake_self.textblk_item_list[0], TextBlkItem)


# ── Click-to-select (canvas-like stacking) ────────────────────

class TestClickSelection:
    """Clicks must select the clicked block and clear the previous selection,
    even when the active shape control covers the block."""

    @pytest.fixture
    def canvas_like(self, qapp):
        scene = QGraphicsScene()
        view = QGraphicsView(scene)
        view.resize(1000, 600)
        view.setSceneRect(QRectF(0, 0, 1000, 600))
        view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        view.show()
        app = QApplication.instance()
        app.processEvents()

        # Mimic real canvas stacking: baseLayer -> textLayer (added BEFORE the
        # controls, so the controls end up on top of the blocks).
        base = QGraphicsRectItem()
        scene.addItem(base)
        text_layer = QGraphicsPixmapItem()
        text_layer.setParentItem(base)
        flow_ctrl = FlowShapeControl(None)
        legacy_ctrl = TextBlkShapeControl(None)
        flow_ctrl.setParentItem(base)
        legacy_ctrl.setParentItem(base)
        sw = ShapeControlSwitcher(flow_ctrl, legacy_ctrl, SimpleNamespace(scale_factor=1.0))

        blk_a = _make_blk(xyxy=(0, 0, 200, 100))
        blk_a.is_flow_mode = True
        item_a = FlowTextBlkItem(blk_a, 0, show_rect=False)
        scene.addItem(item_a)
        item_a.setParentItem(text_layer)

        blk_b = _make_blk(xyxy=(300, 0, 500, 100))
        blk_b.is_flow_mode = False
        item_b = TextBlkItem(blk_b, 1, show_rect=True)
        scene.addItem(item_b)
        item_b.setParentItem(text_layer)

        def click(x, y, modifier=Qt.KeyboardModifier.NoModifier):
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifier, QPoint(x, y))
            QApplication.instance().processEvents()

        return SimpleNamespace(scene=scene, view=view, sw=sw, item_a=item_a, item_b=item_b, click=click)

    def test_click_flow_block_clears_previous_selection(self, canvas_like):
        # Normal block B selected; hover activates flow control over A, then click A.
        canvas_like.sw.setBlkItem(canvas_like.item_b)
        canvas_like.item_b.setSelected(True)
        canvas_like.sw.setBlkItem(canvas_like.item_a)
        canvas_like.click(100, 50)
        assert canvas_like.item_a.isSelected() is True
        assert canvas_like.item_b.isSelected() is False

    def test_click_normal_block_selects(self, canvas_like):
        # Flow block A selected; click normal block B (covered by legacy control).
        canvas_like.sw.setBlkItem(canvas_like.item_a)
        canvas_like.item_a.setSelected(True)
        canvas_like.sw.setBlkItem(canvas_like.item_b)
        canvas_like.click(400, 50)
        assert canvas_like.item_b.isSelected() is True
        assert canvas_like.item_a.isSelected() is False

    def test_ctrl_click_keeps_multi_selection(self, canvas_like):
        canvas_like.sw.setBlkItem(canvas_like.item_a)
        canvas_like.item_a.setSelected(True)
        canvas_like.item_b.setSelected(True)
        canvas_like.click(100, 50, Qt.KeyboardModifier.ControlModifier)
        assert canvas_like.item_a.isSelected() is True
        assert canvas_like.item_b.isSelected() is True
