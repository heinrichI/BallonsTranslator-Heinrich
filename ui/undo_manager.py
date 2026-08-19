"""
UndoManager — менеджер undo/redo.

Выделен из Canvas для слабой связанности.
"""

from typing import Optional
from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QUndoStack, QUndoCommand


class UndoManager(QObject):
    """
    Менеджер undo/redo.

    Responsibilities:
    - Управление стеками команд (текст, рисование)
    - Отслеживание несохранённых изменений
    - Выполнение undo/redo операций
    """

    undoPerformed = Signal()
    redoPerformed = Signal()
    stateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Стеки undo/redo
        self._text_undo_stack = QUndoStack()
        self._draw_undo_stack = QUndoStack()

        # Счётчики шагов
        self._num_pushed_textstep = 0

        # Сохранённые позиции
        self._saved_text_step = 0
        self._saved_draw_step = 0

        # Режим: 'draw' или 'text'
        self._mode = 'draw'

        # Последний стек, куда была добавлена команда (для smart-выбора стека)
        self._last_pushed = None

        # Подключение сигналов
        self._text_undo_stack.indexChanged.connect(self._on_state_changed)
        self._draw_undo_stack.indexChanged.connect(self._on_state_changed)

    @property
    def active_stack(self) -> QUndoStack:
        """Возвращает активный стек undo в зависимости от режима."""
        if self._mode == 'text':
            return self._text_undo_stack
        return self._draw_undo_stack

    def set_mode(self, mode: str):
        """Устанавливает режим: 'text' или 'draw'."""
        self._mode = mode

    def get_mode(self) -> str:
        """Возвращает текущий режим."""
        return self._mode

    def _select_stack(self, can_check: str = 'canUndo') -> QUndoStack:
        """Выбирает стек для undo/redo: приоритет у стека, куда была
        добавлена последняя команда; если он пуст — второй стек."""
        if self._last_pushed == 'text':
            order = (self._text_undo_stack, self._draw_undo_stack)
        else:
            order = (self._draw_undo_stack, self._text_undo_stack)
        for stack in order:
            if getattr(stack, can_check)():
                return stack
        return order[0]

    def undo(self):
        """Отменяет последнюю команду (smart-выбор стека: текст/рисование)."""
        self._select_stack('canUndo').undo()
        self.undoPerformed.emit()

    def redo(self):
        """Повторяет последнюю отменённую команду (smart-выбор стека)."""
        self._select_stack('canRedo').redo()
        self.redoPerformed.emit()

    def undo_text(self):
        """Отменяет последнюю текстовую команду (Ctrl+Z внутри редактора)."""
        self._text_undo_stack.undo()
        self.undoPerformed.emit()

    def redo_text(self):
        """Повторяет последнюю текстовую команду."""
        self._text_undo_stack.redo()
        self.redoPerformed.emit()

    def push_command(self, command: QUndoCommand, update_step: bool = False, is_text: bool = False):
        """
        Добавляет команду в стек undo.

        Args:
            command: Команда для добавления
            update_step: Обновить счётчик шагов
            is_text: True — текстовая команда (стек текста), False — рисование
        """
        if is_text:
            self.push_text_command(command, update_step=update_step)
        else:
            self.push_draw_command(command)

    def push_text_command(self, command: Optional[QUndoCommand] = None, update_step: bool = False):
        """
        Добавляет текстовую команду в стек undo.

        Args:
            command: Команда для добавления (None для пустой команды)
            update_step: Обновить счётчик шагов
        """
        if command is not None:
            self._text_undo_stack.push(command)
            self._last_pushed = 'text'
        if update_step:
            self._num_pushed_textstep += 1
        self.stateChanged.emit()

    def push_draw_command(self, command: QUndoCommand):
        """
        Добавляет команду рисования в стек undo.

        Args:
            command: Команда для добавления
        """
        self._draw_undo_stack.push(command)
        self._last_pushed = 'draw'
        self.stateChanged.emit()

    def clear(self):
        """Очищает все стеки."""
        self._text_undo_stack.clear()
        self._draw_undo_stack.clear()
        self._num_pushed_textstep = 0
        self._last_pushed = None
        self.stateChanged.emit()

    def clear_text_stack(self):
        """Очищает стек текстовых команд."""
        self._text_undo_stack.clear()
        self._num_pushed_textstep = 0
        self.stateChanged.emit()

    def clear_draw_stack(self):
        """Очищает стек команд рисования."""
        self._draw_undo_stack.clear()
        self.stateChanged.emit()

    def is_dirty(self) -> bool:
        """Проверяет, есть ли несохранённые изменения."""
        return (self._text_undo_stack.index() != self._saved_text_step or
                self._draw_undo_stack.index() != self._saved_draw_step)

    def mark_clean(self):
        """Отмечает текущее состояние как сохранённое."""
        self._saved_text_step = self._text_undo_stack.index()
        self._saved_draw_step = self._draw_undo_stack.index()
        self.stateChanged.emit()

    def can_undo(self) -> bool:
        """Проверяет, можно ли выполнить undo (в любом стеке)."""
        return self._text_undo_stack.canUndo() or self._draw_undo_stack.canUndo()

    def can_redo(self) -> bool:
        """Проверяет, можно ли выполнить redo (в любом стеке)."""
        return self._text_undo_stack.canRedo() or self._draw_undo_stack.canRedo()

    def get_text_stack(self) -> QUndoStack:
        """Возвращает стек текстовых команд."""
        return self._text_undo_stack

    def get_draw_stack(self) -> QUndoStack:
        """Возвращает стек команд рисования."""
        return self._draw_undo_stack

    def _on_state_changed(self):
        """Обработчик изменения состояния."""
        self.stateChanged.emit()
