"""
UndoManager — менеджер undo/redo.

Выделен из Canvas для слабой связанности.
"""

from typing import Callable, Optional
from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QUndoStack, QUndoCommand


class TextUndoCommand(QUndoCommand):
    """Команда текстового стека: отменяется Ctrl+Z внутри редактора перевода.

    Маркировка обязательна для команд, push которых может произойти вне
    текстового режима (асинхронные финиши: перевод, глобальная замена).
    Синхронные команды текстового режима могут полагаться на mode-fallback
    (``canvas.textEditMode()``) без маркера.
    """


def resolve_is_text(command: Optional[QUndoCommand], is_text: Optional[bool],
                    mode_is_text: Callable[[], bool]) -> bool:
    """Единая точка разрешения маршрутизации undo-команды в стеки.

    Приоритет: явный аргумент > маркер ``TextUndoCommand`` > текущий режим.

    Args:
        command: Команда для push (``None`` — только счётчики).
        is_text: ``True/False`` — принудительный выбор стека (маркер
            игнорируется); ``None`` — авто (маркер, затем режим).
        mode_is_text: callable, возвращающий текущий текстовый режим
            (инжектируется, чтобы функция оставалась чистой и тестируемой).
    """
    if is_text is not None:
        return is_text
    if command is not None and isinstance(command, TextUndoCommand):
        return True
    return mode_is_text()


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

        # Последний стек, куда была добавлена команда (для smart-выбора стека)
        self._last_pushed = None

        # Подключение сигналов
        self._text_undo_stack.indexChanged.connect(self._on_state_changed)
        self._draw_undo_stack.indexChanged.connect(self._on_state_changed)

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

    def push_text_command(self, command: Optional[QUndoCommand] = None, update_step: bool = False):
        """
        Добавляет текстовую команду в текстовый стек undo.

        Маршрутизацию (text/draw) разрешает вызывающий код через
        ``resolve_is_text`` — публичного метода с флагом is_text нет.

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
