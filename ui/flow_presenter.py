"""
FlowPresenter — MVP Presenter для flow-блока.

Медиатор между TextBlock (Model) и IFlowBlockView (Interface).
Следует принципу Dependency Inversion: Presenter зависит от Interface, не от View.

Pattern:
  Model < Presenter > View (Interface) < View (PyQt)
"""

import logging
from typing import Optional, Tuple, List

from qtpy.QtCore import QPointF, QRectF

from utils.logger import logger as LOGGER
from utils.fontformat import FontFormat, pt2px
from .view_interfaces import IFlowBlockView

LOGGER = logging.getLogger('BallonTranslator')


class FlowPresenter:
    """
    MVP Presenter для flow-блока.

    Responsibilities:
    - Связывает Model (TextBlock) и View Interface (IFlowBlockView)
    - Управляет контрольными точками границ
    - Обрабатывает события от View и обновляет Model

    Правило: Presenter зависит от View Interface, не от конкретного View.
    """

    def __init__(self, model, view: IFlowBlockView, boundary_manager=None):
        """
        Args:
            model: TextBlock — модель данных
            view: IFlowBlockView — интерфейс View для отображения
            boundary_manager: FlowBoundaryManager — менеджер границ
        """
        self._model = model
        self._view = view
        self._boundary_manager = boundary_manager
        self._connected = False

    def connect_signals(self):
        """Подключает сигналы View к обработчикам Presenter."""
        if self._connected:
            return

        # View signals → Presenter handlers
        if hasattr(self._view, 'reshaped'):
            self._view.reshaped.connect(self._on_reshaped)

        self._connected = True

    def disconnect_signals(self):
        """Отключает сигналы View от обработчиков Presenter."""
        if not self._connected:
            return

        if hasattr(self._view, 'reshaped'):
            try:
                self._view.reshaped.disconnect(self._on_reshaped)
            except:
                pass

        self._connected = False

    # ── View → Model (события от View) ──────────────────────

    def _on_reshaped(self):
        """Обработчик: блок был изменён в View → обновляем Model."""
        if self._model is None or self._view is None:
            return

        # Сохраняем контрольные точки в Model
        if hasattr(self._view, '_left_points') and hasattr(self._view, '_right_points'):
            self._model.left_points = [[p.x(), p.y()] for p in self._view._left_points]
            self._model.right_points = [[p.x(), p.y()] for p in self._view._right_points]

        LOGGER.debug("[FlowPresenter] reshaped: saving control points to model")

    # ── Model → View (загрузка данных) ───────────────────────

    def load_from_model(self):
        """Загружает данные из Model и говорит View показать."""
        if self._model is None or self._view is None:
            return

        # Загружаем контрольные точки из Model
        if self._model.left_points and self._model.right_points:
            left = [QPointF(p[0], p[1]) for p in self._model.left_points]
            right = [QPointF(p[0], p[1]) for p in self._model.right_points]

            if hasattr(self._view, '_left_points'):
                self._view._left_points = left
                self._view._right_points = right

        # Загружаем базовые данные
        if self._model.translation:
            self._view.setPlainText(self._model.translation)

        if self._model.fontformat:
            self._view.setFontSize(self._model.fontformat.size_pt)

    def sync_to_model(self):
        """Синхронизирует данные из View обратно в Model."""
        if self._model is None or self._view is None:
            return

        # Текст
        self._model.translation = self._view.toPlainText()

        # Контрольные точки
        if hasattr(self._view, '_left_points') and hasattr(self._view, '_right_points'):
            self._model.left_points = [[p.x(), p.y()] for p in self._view._left_points]
            self._model.right_points = [[p.x(), p.y()] for p in self._view._right_points]

    # ── Presenter → Model (команды) ──────────────────────────

    def add_control_point(self, y: float, side: str):
        """Добавляет контрольную точку."""
        if self._boundary_manager:
            self._boundary_manager.add_point(y, side)

            # Обновляем View
            if self._view and hasattr(self._view, '_update_flow_layout'):
                self._view._update_flow_layout()

    def remove_control_point(self, index: int, side: str):
        """Удаляет контрольную точку."""
        if self._boundary_manager:
            self._boundary_manager.remove_point(index, side)

            # Обновляем View
            if self._view and hasattr(self._view, '_update_flow_layout'):
                self._view._update_flow_layout()

    def get_control_points(self) -> Tuple[List[QPointF], List[QPointF]]:
        """Возвращает контрольные точки."""
        if self._boundary_manager:
            return self._boundary_manager.left_points, self._boundary_manager.right_points
        return [], []

    def set_control_points(self, left: List[QPointF], right: List[QPointF]):
        """Устанавливает контрольные точки."""
        if self._boundary_manager:
            self._boundary_manager.left_points = left
            self._boundary_manager.right_points = right

            # Обновляем View
            if self._view and hasattr(self._view, '_update_flow_layout'):
                self._view._update_flow_layout()

    # ── Presenter → View (инструкции) ────────────────────────

    def update_layout(self):
        """Говорит View: обновить layout."""
        if self._view and hasattr(self._view, '_update_flow_layout'):
            self._view._update_flow_layout()

    def repaint(self):
        """Говорит View: перерисоваться."""
        if self._view:
            self._view.update()
