"""
ClipboardService — сервис буфера обмена для текстовых блоков.

Выделен из Canvas для слабой связанности.
"""

from typing import List, Optional
import copy

from qtpy.QtCore import QObject, QPointF


class ClipboardService(QObject):
    """
    Сервис буфера обмена для текстовых блоков.

    Responsibilities:
    - Копирование блоков
    - Вставка блоков
    - Управление буфером
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks: List = []
        self._text_buffer: str = ''

    def copy_blocks(self, blocks: List) -> None:
        """
        Копирует блоки в буфер.

        Args:
            blocks: Список TextBlock для копирования
        """
        self._blocks = [copy.deepcopy(b) for b in blocks]

    def paste_blocks(self, pos: Optional[QPointF] = None) -> List:
        """
        Вставляет блоки из буфера.

        Args:
            pos: Позиция для вставки (опционально)

        Returns:
            Список скопированных блоков
        """
        if not self._blocks:
            return []

        result = []
        for block in self._blocks:
            new_block = copy.deepcopy(block)
            if pos is not None:
                new_block.adjust_pos(int(pos.x()), int(pos.y()))
            result.append(new_block)

        return result

    def has_blocks(self) -> bool:
        """Проверяет, есть ли блоки в буфере."""
        return len(self._blocks) > 0

    def get_block_count(self) -> int:
        """Возвращает количество блоков в буфере."""
        return len(self._blocks)

    def clear(self) -> None:
        """Очищает буфер."""
        self._blocks.clear()
        self._text_buffer = ''

    def set_text(self, text: str) -> None:
        """Устанавливает текст в буфер."""
        self._text_buffer = text

    def get_text(self) -> str:
        """Возвращает текст из буфера."""
        return self._text_buffer
