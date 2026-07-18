"""
CanvasUndoManager — управление undo/redo для Canvas.

Извлечён из Canvas для уменьшения размера класса.
"""

from typing import Optional
from qtpy.QtGui import QUndoStack, QUndoCommand


class CanvasUndoManager:
    """
    Управляет стеками undo/redo для Canvas.

    Responsibilities:
    - Управление стеками команд (текст, рисование)
    - Отслеживание несохранённых изменений
    - Выполнение undo/redo операций
    """

    def __init__(self, canvas):
        """
        Args:
            canvas: Canvas — графическая сцена
        """
        self.canvas = canvas

        # Стеки undo/redo
        self._text_undo_stack = QUndoStack()
        self._draw_undo_stack = QUndoStack()

        # Счётчики шагов
        self._num_pushed_textstep = 0
        self._num_pushed_drawstep = 0

        # Сохранённые позиции
        self._saved_textstep = 0
        self._saved_drawstep = 0

        # Подключение сигналов
        self._text_undo_stack.indexChanged.connect(self._on_textstack_changed)
        self._draw_undo_stack.indexChanged.connect(self._on_drawstack_changed)

    @property
    def active_undo_stack(self) -> QUndoStack:
        """Возвращает активный стек undo."""
        if self.canvas.textEditMode():
            return self._text_undo_stack
        return self._draw_undo_stack

    def push_undo_command(self, command: QUndoCommand, update_pushed_step: bool = False):
        """
        Добавляет команду в стек undo.

        Args:
            command: Команда для добавления
            update_pushed_step: Обновить счётчик шагов
        """
        self.active_undo_stack.push(command)
        if update_pushed_step:
            self._num_pushed_textstep += 1

    def push_draw_command(self, command: QUndoCommand):
        """
        Добавляет команду рисования в стек undo.

        Args:
            command: Команда для добавления
        """
        self._draw_undo_stack.push(command)

    def push_text_command(self, command: Optional[QUndoCommand] = None, update_pushed_step: bool = False):
        """
        Добавляет текстовую команду в стек undo.

        Args:
            command: Команда для добавления (None для пустой команды)
            update_pushed_step: Обновить счётчик шагов
        """
        if command is not None:
            self._text_undo_stack.push(command)
        if update_pushed_step:
            self._num_pushed_textstep += 1

    def undo(self):
        """Отменяет последнюю команду."""
        self.active_undo_stack.undo()

    def redo(self):
        """Повторяет последнюю отменённую команду."""
        self.active_undo_stack.redo()

    def undo_textedit(self):
        """Отменяет последнюю текстовую команду."""
        self._text_undo_stack.undo()

    def redo_textedit(self):
        """Повторяет последнюю отменённую текстовую команду."""
        self._text_undo_stack.redo()

    def clear_text_stack(self):
        """Очищает стек текстовых команд."""
        self._text_undo_stack.clear()
        self._num_pushed_textstep = 0

    def clear_draw_stack(self):
        """Очищает стек команд рисования."""
        self._draw_undo_stack.clear()
        self._num_pushed_drawstep = 0

    def clear_all(self):
        """Очищает все стеки."""
        self.clear_text_stack()
        self.clear_draw_stack()

    def update_saved_undostep(self):
        """Обновляет сохранённые позиции undo."""
        self._saved_textstep = self._text_undo_stack.index()
        self._saved_drawstep = self._draw_undo_stack.index()

    def text_change_unsaved(self) -> bool:
        """Проверяет, есть ли несохранённые текстовые изменения."""
        return self._text_undo_stack.index() != self._saved_textstep

    def draw_change_unsaved(self) -> bool:
        """Проверяет, есть ли несохранённые изменения рисования."""
        return self._draw_undo_stack.index() != self._saved_drawstep

    def has_unsaved_changes(self) -> bool:
        """Проверяет, есть ли любые несохранённые изменения."""
        return self.text_change_unsaved() or self.draw_change_unsaved()

    def prepare_close(self):
        """Подготовка к закрытию — очистка стеков."""
        self._text_undo_stack.clear()
        self._draw_undo_stack.clear()

    def _on_textstack_changed(self):
        """Обработчик изменения стека текстовых команд."""
        # Обновляем UI если нужно
        pass

    def _on_drawstack_changed(self):
        """Обработчик изменения стека команд рисования."""
        # Обновляем UI если нужно
        pass
