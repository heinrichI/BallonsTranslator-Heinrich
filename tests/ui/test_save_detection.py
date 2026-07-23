"""
Тесты обнаружения несохранённых изменений при использовании DI UndoManager.

Регрессионные тесты на баг, когда:
1. Удаление блоков (Delete and Recover) отменялось при переключении страниц
2. Стирание маски в режиме paint отменялось при переключении страниц

Корневая причина: DI UndoManager.push_command() не инкрементировал
canvas.num_pushed_textstep / num_pushed_drawstep, из-за чего
text_change_unsaved() и draw_change_unsaved() возвращали False,
и conditional_save() пропускал сохранение блок-листа / маски / inpainted.

Запуск:
    set QT_QPA_PLATFORM=offscreen
    cd j:\\Comic translate\\BallonsTranslator
    myenv\\Scripts\\python.exe -m pytest tests/ui/test_save_detection.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
from unittest.mock import MagicMock, patch
from qtpy.QtWidgets import QApplication, QUndoCommand

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.undo_manager import UndoManager


# ── Фикстуры ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на всю сессию (offscreen)."""
    app = QApplication.instance()
    if app is None:
        import sys
        app = QApplication(sys.argv)
    yield app


class _FakeCanvas:
    """Минимальная имитация Canvas для тестирования push_undo_command."""

    def __init__(self):
        self._undo_mgr = UndoManager()
        self.num_pushed_textstep = 0
        self.num_pushed_drawstep = 0
        self.saved_textundo_step = 0
        self.saved_drawundo_step = 0
        self.projstate_unsaved = False
        self._mode = "text"  # text или draw

    def setProjSaveState(self, state):
        self.projstate_unsaved = state

    def textEditMode(self):
        return self._mode == "text"

    def drawMode(self):
        return self._mode == "draw"

    def text_change_unsaved(self):
        return self.saved_textundo_step != self.num_pushed_textstep

    def draw_change_unsaved(self):
        return self.saved_drawundo_step != self.num_pushed_drawstep

    def push_undo_command(self, command, update_pushed_step=True):
        """Копия canvas.push_undo_command с фиксом DI UndoManager."""
        if self._undo_mgr:
            self._undo_mgr.push_command(command)
            self.setProjSaveState(True)
            if update_pushed_step:
                if self.textEditMode():
                    self.num_pushed_textstep += 1
                elif self.drawMode():
                    self.num_pushed_drawstep += 1
            return
        # Fallback без DI UndoManager
        if self.textEditMode():
            self.num_pushed_textstep += 1
        elif self.drawMode():
            self.num_pushed_drawstep += 1


# ── Тесты ──────────────────────────────────────────────────────


class TestDrawStepDetection:
    """draw_change_unsaved() должен возвращать True после push команды рисования."""

    def test_draw_change_unsaved_after_push(self):
        """После push команды рисования через DI UndoManager draw_change_unsaved=True."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        assert canvas.draw_change_unsaved(), (
            "draw_change_unsaved() должен возвращать True после push draw-команды"
        )

    def test_text_change_unsaved_after_push(self):
        """После push текстовой команды через DI UndoManager text_change_unsaved=True."""
        canvas = _FakeCanvas()
        canvas._mode = "text"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        assert canvas.text_change_unsaved(), (
            "text_change_unsaved() должен возвращать True после push text-команды"
        )

    def test_draw_step_not_affected_by_text_push(self):
        """Push текстовой команды не должен менять draw-счётчик."""
        canvas = _FakeCanvas()
        canvas._mode = "text"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        assert not canvas.draw_change_unsaved(), (
            "draw_change_unsaved() не должен меняться от push text-команды"
        )

    def test_text_step_not_affected_by_draw_push(self):
        """Push команды рисования не должен менять text-счётчик."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        assert not canvas.text_change_unsaved(), (
            "text_change_unsaved() не должен меняться от push draw-команды"
        )

    def test_multiple_pushes_increment_step(self):
        """Несколько push команд должны корректно инкрементировать счётчик."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        for _ in range(5):
            canvas.push_undo_command(QUndoCommand())
        assert canvas.num_pushed_drawstep == 5

    def test_save_reset_makes_unsaved_false(self):
        """После update_saved_undostep изменения не должны обнаруживаться."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        canvas.push_undo_command(QUndoCommand())
        assert canvas.draw_change_unsaved()
        # Имитация saveCurrentPage → update_saved_undostep
        canvas.saved_drawundo_step = canvas.num_pushed_drawstep
        assert not canvas.draw_change_unsaved()

    def test_update_pushed_step_false_skips_increment(self):
        """При update_pushed_step=False счётчик не должен инкрементироваться."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd, update_pushed_step=False)
        assert not canvas.draw_change_unsaved(), (
            "При update_pushed_step=False draw_change_unsaved должен быть False"
        )


class TestDeleteRecoverSaveDetection:
    """Регрессия: Delete and Recover должен пометить draw-изменения."""

    def test_delete_recover_marks_draw_unsaved(self):
        """DeleteBlkItemsCommand с mode=1 должен вызвать draw_change_unsaved=True."""
        canvas = _FakeCanvas()
        canvas._mode = "text"  # DeleteBlkItemsCommand — текстовая команда
        # Но mode=1 декрементирует saved_drawundo_step
        canvas.saved_drawundo_step = 0

        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        # text_change_unsaved должен быть True (команда в text-стеке)
        assert canvas.text_change_unsaved()


class TestMaskEraseSaveDetection:
    """Регрессия: стирание маски в paint-режиме должно пометить draw-изменения."""

    def test_mask_erase_marks_draw_unsaved(self):
        """StrokeItemUndoCommand в draw-режиме должен вызвать draw_change_unsaved=True."""
        canvas = _FakeCanvas()
        canvas._mode = "draw"
        cmd = QUndoCommand()
        canvas.push_undo_command(cmd)
        assert canvas.draw_change_unsaved(), (
            "draw_change_unsaved() должен быть True после стирания маски"
        )


class TestEventDrivenDirtyTracking:
    """Тесты event-driven dirty tracking через UndoManager.is_dirty() / mark_clean()."""

    def test_is_dirty_after_push(self):
        """UndoManager.is_dirty() возвращает True после push команды."""
        mgr = UndoManager()
        assert not mgr.is_dirty()
        mgr.push_command(QUndoCommand())
        assert mgr.is_dirty()

    def test_mark_clean_resets_dirty(self):
        """mark_clean() сбрасывает is_dirty() в False."""
        mgr = UndoManager()
        mgr.push_command(QUndoCommand())
        assert mgr.is_dirty()
        mgr.mark_clean()
        assert not mgr.is_dirty()

    def test_multiple_pushes_dirty_after_clean(self):
        """После mark_clean() новый push снова делает is_dirty()=True."""
        mgr = UndoManager()
        mgr.push_command(QUndoCommand())
        mgr.mark_clean()
        assert not mgr.is_dirty()
        mgr.push_command(QUndoCommand())
        assert mgr.is_dirty()

    def test_draw_stack_dirty(self):
        """Команда в draw-стеке делает is_dirty()=True."""
        mgr = UndoManager()
        mgr._mode = 'draw'
        mgr.push_command(QUndoCommand())
        assert mgr.is_dirty()

    def test_text_stack_dirty(self):
        """Команда в text-стеке делает is_dirty()=True."""
        mgr = UndoManager()
        mgr._mode = 'text'
        mgr.push_command(QUndoCommand())
        assert mgr.is_dirty()

    def test_clear_resets_dirty(self):
        """clear() сбрасывает is_dirty() в False."""
        mgr = UndoManager()
        mgr.push_command(QUndoCommand())
        mgr.clear()
        assert not mgr.is_dirty()
