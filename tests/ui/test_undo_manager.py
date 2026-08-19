"""Tests for UndoManager."""
import os
import pytest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtGui import QUndoCommand
from ui.undo_manager import UndoManager


class TestUndoManager:
    def setup_method(self):
        self.undo_mgr = UndoManager()

    def test_init_creates_stacks(self):
        assert self.undo_mgr._text_undo_stack is not None
        assert self.undo_mgr._draw_undo_stack is not None

    def test_clear_resets_counters(self):
        self.undo_mgr._num_pushed_textstep = 5
        self.undo_mgr.clear()
        assert self.undo_mgr._num_pushed_textstep == 0

    def test_is_dirty_initially_false(self):
        assert not self.undo_mgr.is_dirty()

    def test_mark_clean_resets_state(self):
        self.undo_mgr._saved_text_step = 0
        self.undo_mgr._saved_draw_step = 0
        self.undo_mgr.mark_clean()
        assert not self.undo_mgr.is_dirty()

    def test_get_text_stack(self):
        stack = self.undo_mgr.get_text_stack()
        assert stack is not None

    def test_get_draw_stack(self):
        stack = self.undo_mgr.get_draw_stack()
        assert stack is not None

    def test_clear_text_stack(self):
        self.undo_mgr._num_pushed_textstep = 5
        self.undo_mgr.clear_text_stack()
        assert self.undo_mgr._num_pushed_textstep == 0

    def test_clear_draw_stack(self):
        self.undo_mgr.push_draw_command(QUndoCommand())
        assert self.undo_mgr.get_draw_stack().index() == 1
        self.undo_mgr.push_text_command(QUndoCommand())
        self.undo_mgr.clear_draw_stack()
        assert self.undo_mgr.get_draw_stack().index() == 0
        assert self.undo_mgr.get_text_stack().index() == 1  # текстовый стек не тронут


class TestStackRouting:
    """Текстовые команды (is_text=True) попадают в текстовый стек, команды
    рисования — в стек рисования; undo/redo выбирают правильный стек (task9 bug #1)."""

    def setup_method(self):
        self.undo_mgr = UndoManager()

    def test_text_command_goes_to_text_stack(self):
        cmd = QUndoCommand()
        self.undo_mgr.push_command(cmd, is_text=True)
        assert self.undo_mgr.get_text_stack().index() == 1
        assert self.undo_mgr.get_draw_stack().index() == 0

    def test_draw_command_goes_to_draw_stack(self):
        cmd = QUndoCommand()
        self.undo_mgr.push_command(cmd)
        assert self.undo_mgr.get_draw_stack().index() == 1
        assert self.undo_mgr.get_text_stack().index() == 0

    def test_push_text_command_and_draw_command(self):
        t = QUndoCommand()
        d = QUndoCommand()
        self.undo_mgr.push_text_command(t)
        self.undo_mgr.push_draw_command(d)
        assert self.undo_mgr.get_text_stack().index() == 1
        assert self.undo_mgr.get_draw_stack().index() == 1

    def test_undo_picks_last_pushed_stack_first(self):
        text_cmd = QUndoCommand()
        draw_cmd = QUndoCommand()
        self.undo_mgr.push_command(text_cmd, is_text=True)
        self.undo_mgr.push_command(draw_cmd)
        # Последний push — draw → его undo'им первым
        self.undo_mgr.undo()
        assert self.undo_mgr.get_draw_stack().index() == 0
        assert self.undo_mgr.get_text_stack().index() == 1
        # Затем — текст
        self.undo_mgr.undo()
        assert self.undo_mgr.get_text_stack().index() == 0

    def test_undo_text_only_touches_text_stack(self):
        """Ctrl+Z в редакторе отменяет только текстовые команды."""
        text_cmd = QUndoCommand()
        draw_cmd = QUndoCommand()
        self.undo_mgr.push_command(text_cmd, is_text=True)
        self.undo_mgr.push_command(draw_cmd)
        self.undo_mgr.undo_text()
        assert self.undo_mgr.get_text_stack().index() == 0
        assert self.undo_mgr.get_draw_stack().index() == 1  # draw не тронут

    def test_redo_text_only_touches_text_stack(self):
        text_cmd = QUndoCommand()
        draw_cmd = QUndoCommand()
        self.undo_mgr.push_command(text_cmd, is_text=True)
        self.undo_mgr.push_command(draw_cmd)
        self.undo_mgr.undo_text()
        self.undo_mgr.redo_text()
        assert self.undo_mgr.get_text_stack().index() == 1
        assert self.undo_mgr.get_draw_stack().index() == 1  # draw не тронут

    def test_undo_text_empty_stack_is_noop(self):
        # Пустой текстовый стек — undo_text() не падает
        self.undo_mgr.undo_text()
        self.undo_mgr.redo_text()

    def test_can_undo_either_stack(self):
        assert not self.undo_mgr.can_undo()
        self.undo_mgr.push_command(QUndoCommand(), is_text=True)
        assert self.undo_mgr.can_undo()
        self.undo_mgr.undo()
        assert not self.undo_mgr.can_undo()
        assert self.undo_mgr.can_redo()

    def test_redo_picks_last_pushed_stack_first(self):
        text_cmd = QUndoCommand()
        draw_cmd = QUndoCommand()
        self.undo_mgr.push_command(text_cmd, is_text=True)
        self.undo_mgr.push_command(draw_cmd)
        self.undo_mgr.undo()  # draw
        self.undo_mgr.undo()  # text
        self.undo_mgr.redo()  # последний push был draw
        assert self.undo_mgr.get_draw_stack().index() == 1
        assert self.undo_mgr.get_text_stack().index() == 0
        self.undo_mgr.redo()
        assert self.undo_mgr.get_text_stack().index() == 1


class TestPanelUndoChain:
    """Реальная цепочка Ctrl+Z в панели: TextEditCommand → текстовый стек →
    undo_text() откатывает текст редактора (task9 bug #1)."""

    def test_trans_edit_undo_via_text_stack(self, qapp):
        from qtpy.QtGui import QTextCursor
        from ui.textedit_area import TransTextEdit
        from ui.textedit_commands import TextEditCommand

        mgr = UndoManager()
        edit = TransTextEdit(0, None)
        edit.setPlainText('hello world')
        edit.moveCursor(QTextCursor.MoveOperation.End)
        edit.insertPlainText('!')  # один undo-шаг

        # Как делает scenetext_manager.on_push_edit_stack: is_text=True
        cmd = TextEditCommand(edit, 1, None)
        mgr.push_command(cmd, update_step=True, is_text=True)
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

        # Как делает canvas.undo_textedit() в DI-режиме: mgr.undo_text()
        mgr.undo_text()
        assert edit.toPlainText() == 'hello world'

        mgr.redo_text()
        assert edit.toPlainText() == 'hello world!'

    def test_global_undo_after_panel_edit(self, qapp):
        """Глобальный Ctrl+Z после правки в панели откатывает именно её."""
        from qtpy.QtGui import QTextCursor
        from ui.textedit_area import TransTextEdit
        from ui.textedit_commands import TextEditCommand

        mgr = UndoManager()
        edit = TransTextEdit(0, None)
        edit.setPlainText('abc')
        edit.moveCursor(QTextCursor.MoveOperation.End)
        edit.insertPlainText('d')
        mgr.push_command(TextEditCommand(edit, 1, None), is_text=True)

        draw_cmd = QUndoCommand()
        mgr.push_command(draw_cmd)  # например, штрих рисования после правки

        mgr.undo()  # глобальный Ctrl+Z → последний push = draw
        assert mgr.get_draw_stack().index() == 0
        mgr.undo()  # следующий → текстовая правка
        assert edit.toPlainText() == 'abc'
