"""
ScaleManager — управление масштабом сцены.

Выделен из Canvas для слабой связанности.
"""

from typing import Optional
from qtpy.QtCore import QObject, Signal


class ScaleManager(QObject):
    """
    Управление масштабом сцены.

    Responsibilities:
    - Изменение масштаба
    - Ограничения min/max
    - Сигналы изменения масштаба
    """

    scaleChanged = Signal(float)

    # Ограничения масштаба
    MIN_SCALE = 0.01
    MAX_SCALE = 10.0
    SCALE_SPEED = 0.1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale_factor = 1.0
        self._view = None

    def set_view(self, view):
        """Устанавливает QGraphicsView для масштабирования."""
        self._view = view

    def get_scale(self) -> float:
        """Возвращает текущий масштаб."""
        return self._scale_factor

    def set_scale(self, factor: float) -> None:
        """
        Устанавливает масштаб.

        Args:
            factor: Коэффициент масштаба
        """
        factor = max(self.MIN_SCALE, min(self.MAX_SCALE, factor))
        self._scale_factor = factor

        if self._view is not None:
            self._view.scale(factor, factor)

        self.scaleChanged.emit(factor)

    def zoom_in(self) -> None:
        """Увеличивает масштаб."""
        self.set_scale(self._scale_factor * (1 + self.SCALE_SPEED))

    def zoom_out(self) -> None:
        """Уменьшает масштаб."""
        self.set_scale(self._scale_factor / (1 + self.SCALE_SPEED))

    def zoom_to_fit(self, scene_rect=None) -> None:
        """
        Масштабирует сцену для отображения всех элементов.

        Args:
            scene_rect: Прямоугольник сцены (опционально)
        """
        if self._view is None or scene_rect is None:
            return

        view_rect = self._view.viewport().rect()
        scene_width = scene_rect.width()
        scene_height = scene_rect.height()

        if scene_width == 0 or scene_height == 0:
            return

        scale_x = view_rect.width() / scene_width
        scale_y = view_rect.height() / scene_height
        factor = min(scale_x, scale_y)

        self.set_scale(factor)

    def reset_scale(self) -> None:
        """Сбрасывает масштаб к 100%."""
        self.set_scale(1.0)

    def get_scale_percentage(self) -> int:
        """Возвращает масштаб в процентах."""
        return int(self._scale_factor * 100)
