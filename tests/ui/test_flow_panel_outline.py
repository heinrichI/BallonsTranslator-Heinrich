"""Flow mode: панельное выделение должно работать для операций обводки.

Регрессия «весь текст с обводкой» в Flow mode:

- панель e_trans инициализировалась ``blk_item.toPlainText()`` — а документ
  FlowTextBlkItem содержит soft hyphens (U+00AD) от гифенизации;
- guard в ``TextBlkItem._effective_selection()`` сравнивал
  ``item_text.replace('\\u00ad', '')`` (clean) с ``e_trans.toPlainText()``
  (raw, с hyphens) — для flow-блоков сравнение всегда расходилось,
  панельное выделение отклонялось;
- ``fontformat_commands.wrapper`` видел ``_has_effective_selection() == False``
  и уводил панельную операцию stroke/SRGB в whole-block path — обводка
  ставилась на ВЕСЬ текст блока.

Сейчас панель держит «чистый» текст (TransPairWiring), guard сравнивает обе
стороны в clean-виде, а панельные позиции нормализуются через
``_panel_pos_to_clean`` (legacy-панели с hyphens до перезагрузки страницы
тоже маппятся корректно).
"""
import os
import sys
from typing import List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from qtpy.QtGui import QTextCursor, QTextDocument
from qtpy.QtWidgets import QGraphicsScene, QGraphicsView, QApplication

import ui.shared_widget as SW
from utils.textblock import TextBlock
from utils.fontformat import FontFormat
from ui.flow_textitem import FlowTextBlkItem
from ui.textitem import TextBlkItem
import ui.fontformat_commands as F


TEXT = "Hello world foo bar baz"
# 'Hello' = 0..5, 'world' = 6..11, 'foo' = 12..15 (clean-координаты)


def _make_blk(text: str = TEXT) -> TextBlock:
    blk = TextBlock([0, 0, 400, 200])
    blk.lines = [[[0, 0], [400, 0], [400, 200], [0, 200]]]
    blk.translation = text
    blk.fontformat.size = 24.0
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [0, 0, 400, 200]
    return blk


class _FakeTransEdit:
    """Стенд-ин панели e_trans: текст + выделение, без сигналов.

    ``_effective_selection()`` читает только textCursor()/toPlainText(),
    поэтому эмитить selectionChanged не нужно (и это обходит deadlock
    реального QTextEdit в offscreen-режиме, см. test_panel_stroke_display).
    """

    def __init__(self, text: str) -> None:
        self._doc = QTextDocument()
        self._doc.setPlainText(text)
        self._cursor = QTextCursor(self._doc)

    def toPlainText(self) -> str:
        return self._doc.toPlainText()

    def textCursor(self) -> QTextCursor:
        return self._cursor

    def select_range(self, start: int, end: int) -> None:
        self._cursor.setPosition(start)
        self._cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)


class _FakePairWidget:
    def __init__(self, e_trans) -> None:
        self.e_trans = e_trans


class _FakeStManager:
    def __init__(self, e_trans_map: dict) -> None:
        self.pairwidget_list: List[_FakePairWidget] = []
        for idx, e_trans in sorted(e_trans_map.items()):
            while len(self.pairwidget_list) <= idx:
                self.pairwidget_list.append(_FakePairWidget(None))
            self.pairwidget_list[idx].e_trans = e_trans


class _RunningCanvas:
    """Канвас, выполняющий undo-команды сразу (как реальная канвас):
    fontformat_commands создаёт ЛЕНИВЫЕ команды, без redo() операция
    не применяется."""

    def __init__(self) -> None:
        self.commands: List = []

    def push_undo_command(self, cmd) -> None:
        if cmd is None:
            return
        self.commands.append(cmd)
        cmd.redo()

    def hasFocus(self) -> bool:
        return False

    def setFocus(self) -> None:
        pass


def _install_env(e_trans_map: dict):
    """Устанавливает SW.st_manager/SW.canvas под панельные тесты."""
    prev_stm = SW.st_manager
    prev_canvas = SW.canvas
    SW.st_manager = _FakeStManager(e_trans_map)
    SW.canvas = _RunningCanvas()
    return prev_stm, prev_canvas


def _restore_env(prev_stm, prev_canvas):
    SW.st_manager = prev_stm
    SW.canvas = prev_canvas


@pytest.fixture
def flow_item(scene: QGraphicsScene) -> FlowTextBlkItem:
    """Flow item с гифенизованным документом (текст содержит U+00AD)."""
    item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
    scene.addItem(item)
    assert "\u00ad" in item.document().toPlainText(), \
        "test premise: flow document must contain soft hyphens"
    return item


class TestFlowPanelSelection:
    """Панельное выделение → stroke/SRGB только на диапазоне, а не на весь блок."""

    def test_hyphenated_panel_selection_stroke_range_only(self, qapp, flow_item):
        """Сценарий из репорта, 1:1 по wiring: текст панели =
        item.toPlainText() (с soft hyphens, как было до фикса в
        TransPairWiring). Выделение 'world' в панели, stroke 0.5 →
        обводка ТОЛЬКО на слове, блок-скаляр не трогаем."""
        panel = _FakeTransEdit(flow_item.toPlainText())
        prev = _install_env({0: panel})
        try:
            # 'world' в hyphen-тексте: те же индексы, что в документе
            # (панельный текст == документному тексту flow item)
            panel.select_range(7, 12)
            assert flow_item._effective_selection() is not None, \
                "panel selection must not be rejected for flow blocks"

            act = FontFormat()
            F.ffmt_change_stroke_width('stroke_width', 0.5, act, False,
                                       [flow_item], set_focus=True)

            # whole-block fallback НЕ должен сработать
            assert flow_item.fontformat.stroke_width == 0.0
            # диапазон — в документных координатах ('w'..='d' в doc с hyphen)
            assert flow_item.blk.outline_ranges == [[7, 12, 0.5, [0, 0, 0]]]
            groups = flow_item._stroke_groups()
            assert len(groups) == 1
            (spans,) = groups.values()
            assert spans == [(7, 12)]
        finally:
            _restore_env(*prev)

    def test_clean_panel_selection_stroke_range_only(self, qapp, flow_item):
        """Панель с «чистым» текстом (новый wiring): позиции — clean-смещения,
        маппинг через soft hyphens приводит к тем же документным координатам."""
        panel = _FakeTransEdit(flow_item.toPlainText().replace("\u00ad", ""))
        prev = _install_env({0: panel})
        try:
            panel.select_range(6, 11)  # 'world' в clean-тексте
            assert flow_item._effective_selection() is not None

            act = FontFormat()
            F.ffmt_change_stroke_width('stroke_width', 0.5, act, False,
                                       [flow_item], set_focus=True)

            assert flow_item.fontformat.stroke_width == 0.0
            assert flow_item.blk.outline_ranges == [[7, 12, 0.5, [0, 0, 0]]]
            (spans,) = list(flow_item._stroke_groups().values())
            assert spans == [(7, 12)]
        finally:
            _restore_env(*prev)

    def test_clean_panel_selection_srgb_updates_range_color(self, qapp, flow_item):
        """Смена цвета обводки по панельному выделению меняет цвет диапазона,
        не трогая блок-скаляр и ширину."""
        panel = _FakeTransEdit(flow_item.toPlainText().replace("\u00ad", ""))
        prev = _install_env({0: panel})
        try:
            panel.select_range(6, 11)
            act = FontFormat()
            F.ffmt_change_stroke_width('stroke_width', 0.5, act, False,
                                       [flow_item], set_focus=True)
            assert flow_item.blk.outline_ranges == [[7, 12, 0.5, [0, 0, 0]]]

            act = FontFormat()
            F.ffmt_change_srgb('srgb', (255, 0, 0), act, False,
                               [flow_item], set_focus=True)

            assert flow_item.blk.outline_ranges == [[7, 12, 0.5, [255, 0, 0]]]
            assert flow_item.fontformat.stroke_width == 0.0
        finally:
            _restore_env(*prev)

    def test_normal_panel_selection_stroke_unchanged(self, qapp, scene):
        """Контроль: normal-блок (без hyphens) ведёт себя как раньше."""
        item = TextBlkItem(_make_blk(), idx=0, show_rect=False)
        scene.addItem(item)
        panel = _FakeTransEdit(item.toPlainText())
        prev = _install_env({0: panel})
        try:
            panel.select_range(6, 11)  # 'world' (clean == doc)
            assert item._effective_selection() == (6, 11)

            act = FontFormat()
            F.ffmt_change_stroke_width('stroke_width', 0.5, act, False,
                                       [item], set_focus=True)

            assert item.fontformat.stroke_width == 0.0
            assert item.blk.outline_ranges == [[6, 11, 0.5, [0, 0, 0]]]
            (spans,) = list(item._stroke_groups().values())
            assert spans == [(6, 11)]
        finally:
            _restore_env(*prev)


class TestPanelPosMapping:
    """Юнит-тесты маппинга панельных позиций → координаты item-документа."""

    ITEM = "Hel\xadlo world"      # doc flow: hyphen между l и o в 'Hello'
    PANEL_LEGACY = "Hel\xadlo world"  # legacy-панель: текст с hyphens
    PANEL_CLEAN = "Hello world"       # новая панель: чистый текст

    def test_panel_pos_to_clean(self):
        f = TextBlkItem._panel_pos_to_clean
        assert f(self.PANEL_CLEAN, 4) == 4          # clean-панель: тождественно
        assert f(self.PANEL_LEGACY, 7) == 6         # 'w' (hyphen до него не считается)
        assert f(self.PANEL_LEGACY, 3) == 3         # позиция в hyphen-зоне
        assert f(self.PANEL_LEGACY, 999) == len(self.PANEL_CLEAN)  # clamp
        assert f(self.PANEL_LEGACY, -5) == 0        # clamp вниз

    def test_doc_start_hyphenated_panel_is_identity(self):
        """Legacy-панель (текст == документу): панельные позиции == doc."""
        f = TextBlkItem._panel_pos_to_doc_start
        assert f(self.ITEM, 7, self.PANEL_LEGACY) == 7   # start 'w'
        e = TextBlkItem._panel_pos_to_doc_end
        assert e(self.ITEM, 12, self.PANEL_LEGACY) == 12  # end 'world'

    def test_doc_start_clean_panel_maps_through_hyphens(self):
        """Чистая панель: clean-позиция 'w' (6) → doc 7."""
        f = TextBlkItem._panel_pos_to_doc_start
        e = TextBlkItem._panel_pos_to_doc_end
        assert f(self.ITEM, 6, self.PANEL_CLEAN) == 7
        assert e(self.ITEM, 11, self.PANEL_CLEAN) == 12   # 'world' целиком
        assert f(self.ITEM, 0, self.PANEL_CLEAN) == 0
        assert e(self.ITEM, 5, self.PANEL_CLEAN) == 6     # 'Hello' (hyphen вне спана)

    def test_doc_start_without_panel_text_defaults_to_clean_offsets(self):
        """Без panel_text (как вызывали раньше) pos — clean-смещение."""
        f = TextBlkItem._panel_pos_to_doc_start
        e = TextBlkItem._panel_pos_to_doc_end
        assert f(self.ITEM, 6) == 7
        assert e(self.ITEM, 11) == 12


class TestTranslationCleanliness:
    """blk.translation не должен получать soft hyphens (P3)."""

    def test_update_textblk_list_strips_soft_hyphens(self, qapp, scene):
        from ui.block_manager import BlockManager

        class _Canvas:
            def removeItem(self, *a): pass

        class _TextList:
            def removeWidget(self, *a): pass

        class _TransPair:
            def __init__(self, panel_text):
                class _E:
                    @staticmethod
                    def toPlainText():
                        return "source text"
                self.e_source = _E()
                # боевой wiring: панель держит clean-текст (transpair_wiring.py:48)
                class _P:
                    @staticmethod
                    def toPlainText():
                        return panel_text
                self.e_trans = _P()

        class _Proj:
            def current_block_list(self):
                return []

        item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
        scene.addItem(item)
        assert "\u00ad" in item.toPlainText()

        bm = BlockManager(_Canvas(), _TextList())
        bm.textblk_item_list = [item]
        bm.pairwidget_list = [_TransPair(TEXT)]
        bm.update_textblk_list(_Proj())

        assert item.blk.translation == TEXT
        assert "\u00ad" not in item.blk.translation


class TestToggleFlowModeClearsOutlineRanges:
    """Вариант 3: при смене режима координаты ranges становятся невалидны —
    очищаем, чтобы обводка не «уплывала» на другие символы."""

    def _make_fake_self(self, item) -> object:
        import types

        class _Canvas:
            editing_textblkitem = None

            def remove_item(self, item): pass

            def add_item_to_text_layer(self, item): pass

        class _ShapeControl:
            def setBlkItem(self, item): pass

        self = types.SimpleNamespace()
        self.textblk_item_list = [item]
        self.canvas = _Canvas()
        self._reconnect_block_signals = lambda item: None
        self.txtblkShapeControl = _ShapeControl()
        self.select_single = lambda item: None
        return self

    def test_flow_to_normal_toggle_clears_ranges(self, qapp):
        from ui.scenetext_manager import SceneTextManager

        item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
        item.blk.outline_ranges = [[7, 12, 0.5, [0, 0, 0]]]
        item.blk.fontformat.stroke_width = 0.4
        self_ = self._make_fake_self(item)

        SceneTextManager.toggle_block_flow_mode(self_, 0)

        assert self_.textblk_item_list[0] is not item
        assert isinstance(self_.textblk_item_list[0], TextBlkItem)
        assert not isinstance(self_.textblk_item_list[0], FlowTextBlkItem)
        assert item.blk.outline_ranges == []
        # block-level stroke сохраняется (координат не зависит)
        assert self_.textblk_item_list[0].fontformat.stroke_width == 0.4

    def test_normal_to_flow_toggle_clears_ranges(self, qapp):
        from ui.scenetext_manager import SceneTextManager

        item = TextBlkItem(_make_blk(), idx=0, show_rect=False)
        item.blk.outline_ranges = [[6, 11, 0.5, [0, 0, 0]]]
        self_ = self._make_fake_self(item)

        SceneTextManager.toggle_block_flow_mode(self_, 0)

        assert isinstance(self_.textblk_item_list[0], FlowTextBlkItem)
        assert item.blk.outline_ranges == []

    def test_toggle_without_ranges_is_noop_for_stroke(self, qapp):
        from ui.scenetext_manager import SceneTextManager

        item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
        # Ставим на МОДЕЛЬ: новый item строит fontformat из blk.fontformat
        item.blk.fontformat.stroke_width = 0.3
        self_ = self._make_fake_self(item)

        SceneTextManager.toggle_block_flow_mode(self_, 0)

        assert self_.textblk_item_list[0].fontformat.stroke_width == 0.3
        assert self_.textblk_item_list[0].blk.outline_ranges == []