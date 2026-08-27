"""Undo-маршрутизация команды перевода RunBlkTransCommand (Ctrl+Z в редакторе).

Регрессия: после DI-рефакторинга Canvas.push_undo_command передавал команды
в UndoManager без is_text, поэтому команды перевода (и шрифтовые, и замена,
и move/create/delete блоков) попадали в draw-стек, и Ctrl+Z в редакторе
перевода (undo_text) их не откатывал.

Фикс: классификация по типу ``TextUndoCommand`` + mode-based fallback.
Тесты вызывают РЕАЛЬНЫЕ методы (Canvas / SceneTextManager / ScenePresenter)
unbound-вызовами на лёгких stub'ах и реальный RunBlkTransCommand со stub
canvas — без построения полных виджетов (паттерн репо: _FakeCanvas).
"""
import os
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtGui import QUndoCommand

from ui.canvas import Canvas
from ui.scene_presenter import ScenePresenter
from ui.scenetext_manager import SceneTextManager
from ui.undo_manager import TextUndoCommand, UndoManager


class _MarkedCmd(TextUndoCommand):
    pass


class _PlainCmd(QUndoCommand):
    pass


class _CanvasStub:
    """Минимальный stub, совместимый с реальным Canvas.push_undo_command
    (вызывается unbound: ``Canvas.push_undo_command(stub, ...)``)."""

    def __init__(self, undo_mgr, editor_index=1):
        self._undo_mgr = undo_mgr
        self.editor_index = editor_index
        self.num_pushed_textstep = 0
        self.num_pushed_drawstep = 0
        self.save_states = []

    def textEditMode(self):
        return self.editor_index == 1

    def drawMode(self):
        return self.editor_index == 0

    def setProjSaveState(self, value):
        self.save_states.append(value)


class _BlkTransCanvasStub(_CanvasStub):
    """Canvas stub для RunBlkTransCommand: роутинг через реальный
    Canvas.push_undo_command + массивы для ветки inpaint (mode > 1)."""

    def push_undo_command(self, command, update_pushed_step=True, is_text=None):
        Canvas.push_undo_command(self, command,
                                 update_pushed_step=update_pushed_step, is_text=is_text)

    def get_inpainted_array(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def get_mask_array(self):
        return np.zeros((8, 8), dtype=np.uint8)


class TestCommandMarking:
    """Маркировка типов TextUndoCommand (план [Classes])."""

    def test_run_blk_trans_command_marked(self, qapp):
        from ui.drawing_commands import RunBlkTransCommand
        assert issubclass(RunBlkTransCommand, TextUndoCommand)

    def test_empty_command_class_not_marked(self, qapp):
        """EmptyCommand не помечен: у точки push явный is_text=True (mode > 1)."""
        from ui.drawing_commands import EmptyCommand
        assert not issubclass(EmptyCommand, TextUndoCommand)

    def test_paste_src_items_command_marked(self, qapp):
        from ui.scenetext_manager import PasteSrcItemsCommand
        assert issubclass(PasteSrcItemsCommand, TextUndoCommand)

    def test_fontformat_commands_marked(self, qapp):
        from ui.fontformat_commands import (
            SelectionOutlineUndoCommand,
            TextStyleUndoCommand,
        )
        assert issubclass(TextStyleUndoCommand, TextUndoCommand)
        assert issubclass(SelectionOutlineUndoCommand, TextUndoCommand)

    def test_textedit_commands_refined_marking(self, qapp):
        """Помечен только асинхронный GlobalRepalceAllCommand (push из
        on_global_replace_finished); остальные 12 классов идут через
        mode-based fallback (или уже пушатся с явным is_text=True)."""
        import ui.textedit_commands as m
        marked = ['GlobalRepalceAllCommand']
        unmarked = [
            'MoveBlkItemsCommand', 'ApplyFontformatCommand', 'ReshapeItemCommand',
            'RotateItemCommand', 'AutoLayoutCommand', 'SqueezeCommand',
            'ResetAngleCommand', 'TextItemEditCommand', 'TextEditCommand',
            'PageReplaceOneCommand', 'PageReplaceAllCommand', 'MultiPasteCommand',
        ]
        for name in marked:
            assert issubclass(getattr(m, name), TextUndoCommand), name
        for name in unmarked:
            assert not issubclass(getattr(m, name), TextUndoCommand), name


class TestCanvasDiRouting:
    """Реальный Canvas.push_undo_command (unbound на stub'е), DI-режим."""

    def test_marked_command_goes_to_text_stack_in_text_mode(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=1)
        Canvas.push_undo_command(stub, _MarkedCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_marked_command_goes_to_text_stack_even_in_draw_mode(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=0)
        Canvas.push_undo_command(stub, _MarkedCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_unmarked_command_follows_text_mode(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=1)
        Canvas.push_undo_command(stub, _PlainCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_unmarked_command_follows_draw_mode(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=0)
        Canvas.push_undo_command(stub, _PlainCmd())
        assert mgr.get_draw_stack().index() == 1
        assert mgr.get_text_stack().index() == 0

    def test_explicit_is_text_overrides_mode(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=0)  # draw-режим
        Canvas.push_undo_command(stub, _PlainCmd(), is_text=True)
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_counters_follow_routing_decision(self, qapp):
        """Счётчики canvas идут за фактическим стеком, а не за mode
        (исправление расхождения «текстовый счётчик растёт, команда в draw-стеке»)."""
        # text-режим, немаркированная команда → текстовый счётчик
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=1)
        Canvas.push_undo_command(stub, _PlainCmd())
        assert (stub.num_pushed_textstep, stub.num_pushed_drawstep) == (1, 0)

        # draw-режим + маркированная команда → команда и счётчик в тексте
        mgr2 = UndoManager()
        stub2 = _CanvasStub(mgr2, editor_index=0)
        Canvas.push_undo_command(stub2, _MarkedCmd())
        assert (stub2.num_pushed_textstep, stub2.num_pushed_drawstep) == (1, 0)
        assert mgr2.get_text_stack().index() == 1

    def test_none_command_only_updates_counters(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=1)
        Canvas.push_undo_command(stub, None)
        assert stub.num_pushed_textstep == 1
        assert mgr.get_text_stack().index() == 0
        assert mgr.get_draw_stack().index() == 0

    def test_save_state_marked_unsaved(self, qapp):
        mgr = UndoManager()
        stub = _CanvasStub(mgr, editor_index=1)
        Canvas.push_undo_command(stub, _MarkedCmd())
        assert stub.save_states == [True]


class TestBlkTransUndo:
    """Сценарий бага: запуск перевода (mode=2) → Ctrl+Z в редакторе перевода.

    mode=2: __init__ сам пушит empty_command (inpaint-снимок), затем
    mainwindow.py:1343 пушит внешнюю RunBlkTransCommand. Обе команды должны
    попасть в текстовый стек и откатываться undo_text().
    """

    def test_run_blk_trans_command_lands_in_text_stack(self, qapp):
        from ui.drawing_commands import RunBlkTransCommand

        mgr = UndoManager()
        stub = _BlkTransCanvasStub(mgr, editor_index=1)  # текстовый режим

        # __init__ с mode=2 пушит empty_command (instance-маркирован)
        cmd = RunBlkTransCommand(stub, [], [], mode=2)
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

        # внешняя команда (class-маркирован) — как mainwindow.py:1343
        Canvas.push_undo_command(stub, cmd)
        assert mgr.get_text_stack().index() == 2
        assert mgr.get_draw_stack().index() == 0

        # Ctrl+Z в редакторе перевода: canvas.undo_textedit() → undo_text()
        mgr.undo_text()
        assert mgr.get_text_stack().index() == 1
        mgr.undo_text()
        assert mgr.get_text_stack().index() == 0
        assert mgr.get_draw_stack().index() == 0

    def test_run_blk_trans_command_text_stack_even_in_draw_mode(self, qapp):
        from ui.drawing_commands import RunBlkTransCommand

        mgr = UndoManager()
        stub = _BlkTransCanvasStub(mgr, editor_index=0)  # атрибут приоритетнее режима
        cmd = RunBlkTransCommand(stub, [], [], mode=2)
        Canvas.push_undo_command(stub, cmd)
        assert mgr.get_text_stack().index() == 2
        assert mgr.get_draw_stack().index() == 0

    def test_mode1_no_empty_command(self, qapp):
        """mode=1 (без inpaint): empty_command не создаётся, только внешняя команда."""
        from ui.drawing_commands import RunBlkTransCommand

        mgr = UndoManager()
        stub = _BlkTransCanvasStub(mgr, editor_index=1)
        cmd = RunBlkTransCommand(stub, [], [], mode=1)
        assert cmd.empty_command is None
        assert mgr.get_text_stack().index() == 0
        Canvas.push_undo_command(stub, cmd)
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0


class _StmStub:
    """Stub для реального SceneTextManager.push_undo_command (unbound)."""

    def __init__(self, undo_mgr, text_mode):
        self._undo_mgr = undo_mgr
        self.canvas = SimpleNamespace(
            textEditMode=lambda: text_mode,
            setProjSaveState=lambda value: None,
        )


class TestStManagerRouting:
    """Реальный SceneTextManager.push_undo_command (unbound на stub'е)."""

    def test_auto_marked_command_to_text_stack_in_draw_mode(self, qapp):
        mgr = UndoManager()
        stub = _StmStub(mgr, text_mode=False)
        SceneTextManager.push_undo_command(stub, _MarkedCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_auto_unmarked_follows_text_mode(self, qapp):
        mgr = UndoManager()
        stub = _StmStub(mgr, text_mode=True)
        SceneTextManager.push_undo_command(stub, _PlainCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_auto_unmarked_follows_draw_mode(self, qapp):
        mgr = UndoManager()
        stub = _StmStub(mgr, text_mode=False)
        SceneTextManager.push_undo_command(stub, _PlainCmd())
        assert mgr.get_draw_stack().index() == 1
        assert mgr.get_text_stack().index() == 0

    def test_explicit_is_text_false_kept_in_draw_when_unmarked(self, qapp):
        mgr = UndoManager()
        stub = _StmStub(mgr, text_mode=True)
        SceneTextManager.push_undo_command(stub, _PlainCmd(), is_text=False)
        assert mgr.get_draw_stack().index() == 1
        assert mgr.get_text_stack().index() == 0

    def test_explicit_false_overrides_marker(self, qapp):
        """Новая семантика: явный is_text=False переопределяет маркер
        TextUndoCommand (ранее формула 'is_text or attr' держала команду в
        текстовом стеке даже при явном False)."""
        mgr = UndoManager()
        stub = _StmStub(mgr, text_mode=False)
        SceneTextManager.push_undo_command(stub, _MarkedCmd(), is_text=False)
        assert mgr.get_draw_stack().index() == 1
        assert mgr.get_text_stack().index() == 0


class TestPresenterRouting:
    """Реальный ScenePresenter.push_undo_command (unbound на stub'е)."""

    def test_delegates_to_view(self, qapp):
        mgr = UndoManager()
        view = _CanvasStub(mgr, editor_index=0)  # has push_undo_command
        stub = SimpleNamespace(_view=view, _undo_mgr=mgr)
        ScenePresenter.push_undo_command(stub, _PlainCmd())
        assert mgr.get_draw_stack().index() == 1
        assert mgr.get_text_stack().index() == 0

    def test_delegates_explicit_is_text_to_view(self, qapp):
        mgr = UndoManager()
        view = _CanvasStub(mgr, editor_index=0)
        stub = SimpleNamespace(_view=view, _undo_mgr=mgr)
        ScenePresenter.push_undo_command(stub, _PlainCmd(), is_text=True)
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_fallback_classifies_by_attribute(self, qapp):
        mgr = UndoManager()
        view = SimpleNamespace(textEditMode=lambda: False)  # без push_undo_command
        stub = SimpleNamespace(_view=view, _undo_mgr=mgr)
        ScenePresenter.push_undo_command(stub, _MarkedCmd())
        assert mgr.get_text_stack().index() == 1
        assert mgr.get_draw_stack().index() == 0

    def test_fallback_unmarked_follows_view_mode(self, qapp):
        mgr = UndoManager()
        view = SimpleNamespace(textEditMode=lambda: True)
        stub = SimpleNamespace(_view=view, _undo_mgr=mgr)
        ScenePresenter.push_undo_command(stub, _PlainCmd())
        assert mgr.get_text_stack().index() == 1

    def test_fallback_no_mode_info_goes_to_draw(self, qapp):
        mgr = UndoManager()
        view = SimpleNamespace()  # ни push_undo_command, ни textEditMode
        stub = SimpleNamespace(_view=view, _undo_mgr=mgr)
        ScenePresenter.push_undo_command(stub, _PlainCmd())
        assert mgr.get_draw_stack().index() == 1
