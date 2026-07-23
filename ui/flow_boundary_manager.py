"""
FlowBoundaryManager — извлечённый из FlowTextBlkItem.

Содержит логику управления контрольными точками границ:
- Инициализация из прямоугольника
- Интерполяция границ
- Построение путей
- Добавление/удаление точек
- Сохранение/загрузка из модели

НЕ зависит от View — только от QPointF и QPainterPath.
"""

import logging
import math
from typing import List, Tuple, Optional
from copy import deepcopy

from qtpy.QtCore import QPointF, QRectF
from qtpy.QtGui import QPainterPath

from utils.logger import logger as LOGGER

LOGGER = logging.getLogger('BallonTranslator')

# ── Constants ────────────────────────────────────────────────

DEFAULT_POINTS_PER_SIDE: int = 4
MIN_POINTS_PER_SIDE: int = 3


class FlowBoundaryManager:
    """
    Управление контрольными точками границ flow-блока.
    
    Responsibilities:
    - Инициализация контрольных точек из прямоугольника
    - Интерполяция границ для текстового layout
    - Построение визуальных путей границ
    - Добавление/удаление контрольных точек
    - Сохранение/загрузка из модели (TextBlock)
    """
    
    def __init__(self):
        self.left_points: List[QPointF] = []
        self.right_points: List[QPointF] = []
        self._old_left_points: List[QPointF] = []
        self._old_right_points: List[QPointF] = []
    
    def init_from_rect(self, rect: QRectF) -> bool:
        """
        Инициализирует контрольные точки из прямоугольника.
        
        Args:
            rect: Прямоугольник в item-local координатах
        
        Returns:
            True если точки были инициализированы, False если rect слишком мал
        """
        if rect is None or rect.width() < 10 or rect.height() < 10:
            return False
        
        # Skip if flow points already set
        if self.left_points and self.right_points:
            return False
        
        x0, y0 = rect.x(), rect.y()
        x1, y1 = rect.x() + rect.width(), rect.y() + rect.height()
        
        self.left_points = []
        self.right_points = []
        for i in range(DEFAULT_POINTS_PER_SIDE):
            t = i / (DEFAULT_POINTS_PER_SIDE - 1) if DEFAULT_POINTS_PER_SIDE > 1 else 0.0
            y = y0 + t * (y1 - y0)
            self.left_points.append(QPointF(x0, y))
            self.right_points.append(QPointF(x1, y))
        
        return True
    
    def interpolate_at_y(self, y: float, side: str = 'left') -> float:
        """
        Интерполирует x-координату на заданной y для заданной стороны.
        
        Args:
            y: Y-координата для интерполяции
            side: 'left' или 'right'
        
        Returns:
            x-координата на заданной y
        """
        points = self.left_points if side == 'left' else self.right_points
        return interpolate_boundary(points, y)
    
    def build_path(self, side: str = 'left') -> QPainterPath:
        """
        Строит визуальный путь для заданной стороны.
        
        Args:
            side: 'left' или 'right'
        
        Returns:
            QPainterPath для отрисовки
        """
        points = self.left_points if side == 'left' else self.right_points
        return build_quad_path(points)
    
    def add_point(self, y: float, side: str) -> bool:
        """
        Добавляет контрольную точку на заданной стороне.
        
        Args:
            y: Y-координата для новой точки
            side: 'left' или 'right'
        
        Returns:
            True если точка была добавлена
        """
        points = self.left_points if side == 'left' else self.right_points
        if not points:
            return False
        
        x = interpolate_boundary(points, y)
        new_pt = QPointF(x, y)
        points.append(new_pt)
        points.sort(key=lambda p: p.y())
        return True
    
    def remove_point(self, index: int, side: str) -> bool:
        """
        Удаляет контрольную точку по индексу.
        
        Args:
            index: Индекс точки для удаления
            side: 'left' или 'right'
        
        Returns:
            True если точка была удалена
        """
        points = self.left_points if side == 'left' else self.right_points
        if len(points) <= MIN_POINTS_PER_SIDE:
            return False
        if 0 <= index < len(points):
            points.pop(index)
            return True
        return False
    
    def snapshot(self):
        """Снимает текущее состояние для undo."""
        self._old_left_points = deepcopy(self.left_points)
        self._old_right_points = deepcopy(self.right_points)
    
    def restore(self):
        """Восстанавливает состояние из снимка (undo)."""
        self.left_points = deepcopy(self._old_left_points)
        self.right_points = deepcopy(self._old_right_points)
    
    def save_to_block(self, blk):
        """
        Сохраняет контрольные точки в модель TextBlock.
        
        Args:
            blk: TextBlock для сохранения
        """
        if blk is None:
            return
        blk.left_points = [[p.x(), p.y()] for p in self.left_points]
        blk.right_points = [[p.x(), p.y()] for p in self.right_points]
    
    def load_from_block(self, blk) -> bool:
        """
        Загружает контрольные точки из модели TextBlock.
        
        Args:
            blk: TextBlock для загрузки
        
        Returns:
            True если точки были загружены
        """
        if blk is None:
            return False
        if blk.left_points and blk.right_points:
            self.left_points = [QPointF(p[0], p[1]) for p in blk.left_points]
            self.right_points = [QPointF(p[0], p[1]) for p in blk.right_points]
            return True
        return False
    
    def get_y_range(self) -> Tuple[float, float]:
        """
        Возвращает диапазон Y контрольных точек.
        
        Returns:
            (min_y, max_y) или (0, 0) если нет точек
        """
        if not self.left_points and not self.right_points:
            return 0.0, 0.0
        
        all_ys = [p.y() for p in self.left_points] + [p.y() for p in self.right_points]
        return min(all_ys), max(all_ys)
    
    def get_x_range(self) -> Tuple[float, float]:
        """
        Возвращает диапазон X контрольных точек.
        
        Returns:
            (min_x, max_x) или (0, 0) если нет точек
        """
        if not self.left_points and not self.right_points:
            return 0.0, 0.0
        
        all_xs = [p.x() for p in self.left_points] + [p.x() for p in self.right_points]
        return min(all_xs), max(all_xs)


# ── Helper functions ─────────────────────────────────────────

def interpolate_boundary(points: List[QPointF], y: float) -> float:
    """
    Линейная интерполяция между контрольными точками.
    Возвращает x на заданной y.
    """
    if len(points) < 2:
        return points[0].x() if points else 0.0
    
    # Sort by y
    pts = sorted(points, key=lambda p: p.y())
    
    # Clamp to range
    if y <= pts[0].y():
        return pts[0].x()
    if y >= pts[-1].y():
        return pts[-1].x()
    
    # Find segment and interpolate
    for i in range(len(pts) - 1):
        y0, y1 = pts[i].y(), pts[i + 1].y()
        if y0 <= y <= y1:
            if abs(y1 - y0) < 1e-9:
                return pts[i].x()
            t = (y - y0) / (y1 - y0)
            return pts[i].x() + t * (pts[i + 1].x() - pts[i].x())
    
    return pts[-1].x()


def build_quad_path(points: List[QPointF]) -> QPainterPath:
    """
    Строит линейный путь через все контрольные точки.
    Использует lineTo для совпадения с interpolate_boundary().
    """
    path = QPainterPath()
    if len(points) < 2:
        return path

    pts = sorted(points, key=lambda p: p.y())
    path.moveTo(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    return path
