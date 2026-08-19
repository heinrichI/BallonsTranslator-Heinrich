"""
Undo/Redo Ctrl+Z/Ctrl+Y — механизм через QAction титлбара
(StandardKey.Undo/Redo, контекст WindowShortcut) + smart UndoManager.

Регрессия (сломано в fa7fa61, откатлено): глобальный QShortcut в MainWindow
с маршрутизацией фокуса `_undo_target()` перехватывал Ctrl+Z и, в зависимости
от фокуса, гнал его в текстовый стек или не обрабатывал вообще → после
переноса блока «ничего не происходит».

Текущее поведение (как в 24f458d):
- Ctrl+Z/Ctrl+Y → TitleBar.undoAction/redoAction (mainwindowbars.py) →
  MainWindow.on_undo/on_redo → canvas.undo()/redo() → smart-стек
  UndoManager (стек последней добавленной команды);
- внутри редактора перевода — его собственный keyPressEvent (undo_signal).

Run:
    myenv/Scripts/python.exe -m pytest tests/ui/test_global_undo_shortcut.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QAction, QMenu, QMainWindow, QPushButton

from ui.flow_textitem import FlowTextBlkItem
from ui.textedit_commands import ApplyFontformatCommand, MoveBlkItemsCommand
from ui.textedit_area import TransTextEdit
from ui.undo_manager import UndoManager
from utils.fontformat import FontFormat
from utils.textblock import TextBlock


def _make_blk(text="Hello world"):
    blk = TextBlock([0, 0, 400, 200])
    blk.lines = [[[0, 0], [400, 0], [400, 200], [0, 200]]]
    blk.translation = text
    blk._bounding_rect = [0, 0, 400, 200]
    return blk


class FakeEdit:
    idx = 0

    def document(self):
        class _Doc:
            def clearUndoRedoStacks(self):
                pass
        return _Doc()


class FakeShapeCtrl:
    """Мини-дабл TextBlkShapeControl для MoveBlkItemsCommand."""
    blk_item = None

    def updateBoundingRect(self):
        pass


class TestCtrlZDeliveryViaWindowAction:
    """Ctrl+Z/Ctrl+Y доставляются через QAction с StandardKey-шорткатом
    (контекст WindowShortcut) — именно так они подключены в TitleBar
    (mainwindowbars.py: undoAction/redoAction в editMenu)."""

    def _make_window(self, qapp):
        """QMainWindow + меню с QAction Undo/Redo, как в TitleBar."""
        calls = []
        win = QMainWindow()
        win.show()
        btn = QPushButton("Apply")
        win.setCentralWidget(btn)
        menu = QMenu(win)
        undo_action = QAction("Undo", win)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(lambda: calls.append("undo_action"))
        redo_action = QAction("Redo", win)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(lambda: calls.append("redo_action"))
        menu.addActions([undo_action, redo_action])
        win.menuBar().addMenu(menu)
        win.activateWindow()
        qapp.processEvents()
        return win, btn, calls

    def test_ctrl_z_with_button_focus_fires_action(self, qapp):
        """Сценарий «Apply text style, фокус на кнопке, Ctrl+Z»: шорткат
        WindowShortcut срабатывает, хотя фокус на кнопке."""
        win, btn, calls = self._make_window(qapp)
        btn.setFocus()
        qapp.processEvents()

        QTest.keyClick(btn, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()

        assert calls == ["undo_action"]

    def test_ctrl_y_with_button_focus_fires_redo_action(self, qapp):
        win, btn, calls = self._make_window(qapp)
        btn.setFocus()
        qapp.processEvents()

        QTest.keyClick(btn, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()

        assert calls == ["redo_action"]

    def test_ctrl_z_in_trans_editor_goes_to_editor(self, qapp):
        """Фокус в редакторе перевода: Ctrl+Z обрабатывает сам редактор
        (undo_signal), шорткат окна не дублирует."""
        calls = []
        win = QMainWindow()
        win.show()
        editor = TransTextEdit(0, None)
        win.setCentralWidget(editor)
        editor.undo_signal.connect(lambda: calls.append("editor_keypress"))
        menu = QMenu(win)
        undo_action = QAction("Undo", win)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(lambda: calls.append("undo_action"))
        menu.addAction(undo_action)
        win.menuBar().addMenu(menu)
        editor.setFocus()
        win.activateWindow()
        qapp.processEvents()

        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()

        assert calls == ["editor_keypress"]


class TestNoGlobalCtrlZShortcutInMainWindow:
    """Гард-тест: глобальный QShortcut Ctrl+Z/Ctrl+Y с маршрутизацией
    `_undo_target()` в MainWindow не должен появляться повторно — именно он
    ломал undo переноса блоков (конфликт с QAction титлбара + маршрутизация
    по фокусу)."""

    def test_no_global_undo_shortcut_in_mainwindow_source(self):
        src_path = os.path.join(ROOT, "ui", "mainwindow.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "StandardKey.Undo" not in src, (
            "Глобальный QShortcut Ctrl+Z в MainWindow запрещён: undo идёт "
            "через QAction TitleBar (mainwindowbars.py) -> on_undo -> canvas.undo()"
        )
        assert "StandardKey.Redo" not in src, (
            "Глобальный QShortcut Ctrl+Y в MainWindow запрещён: redo идёт "
            "через QAction TitleBar (mainwindowbars.py) -> on_redo -> canvas.redo()"
        )
        assert "_undo_target" not in src, (
            "Маршрутизация _undo_target() удалена: она направляла Ctrl+Z "
            "в текстовый стек/в никуда в зависимости от фокуса"
        )


class TestMoveCommandSmartUndo:
    """E2E (регрессия из-за которой откатывали шорткат): перенос блока →
    MoveBlkItemsCommand в draw-стек → smart-undo возвращает позицию."""

    def test_move_flow_block_undo_redo_cycle(self, qapp, scene):
        item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
        scene.addItem(item)
        old_pos = QPointF(100, 200)
        new_pos = QPointF(250, 320)
        item.setPos(old_pos)
        item.oldPos = old_pos
        item.setPos(new_pos)

        mgr = UndoManager()
        cmd = MoveBlkItemsCommand([item], FakeShapeCtrl())
        # scenetext_manager.onTextBlkItemMoved: push без is_text -> draw-стек
        mgr.push_command(cmd, is_text=False)
        assert mgr.get_draw_stack().index() == 1

        mgr.undo()
        assert item.pos() == old_pos

        mgr.redo()
        assert item.pos() == new_pos


class TestApplyTextStyleGlobalUndo:
    """E2E (первоначальный баг файла): Apply text style → push(is_text=True)
    → smart-undo откатывает стиль, redo возвращает."""

    def test_apply_style_smart_undo_cycle(self, qapp, scene):
        item = FlowTextBlkItem(_make_blk(), idx=0, show_rect=False)
        scene.addItem(item)
        old_fmt = item.get_fontformat()

        new_fmt = FontFormat()
        new_fmt.font_size = old_fmt.font_size + 10
        new_fmt.bold = True

        mgr = UndoManager()
        cmd = ApplyFontformatCommand([item], [FakeEdit()], new_fmt)
        # scenetext_manager.apply_fontformat: push_undo_command(cmd, is_text=True)
        mgr.push_command(cmd, is_text=True)
        assert mgr.get_text_stack().index() == 1
        assert item.get_fontformat().bold is True

        mgr.undo()
        assert mgr.get_text_stack().index() == 0
        assert item.get_fontformat().font_size == old_fmt.font_size
        assert item.get_fontformat().bold is False

        mgr.redo()
        assert item.get_fontformat().bold is True
        assert item.get_fontformat().font_size == new_fmt.font_size
