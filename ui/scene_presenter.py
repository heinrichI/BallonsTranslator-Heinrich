"""
ScenePresenter — MVP Presenter для сцены.

Медиатор между TextBlock[] (Model) и ISceneView (Interface).
Следует принципу Dependency Inversion: Presenter зависит от Interface, не от View.

Pattern:
  Model < Presenter > View (Interface) < View (PyQt)
"""

import logging
from typing import List, Optional, Any

from utils.logger import logger as LOGGER
from utils.textblock import TextBlock
from .view_interfaces import ISceneView
from .event_bus import EventBus, Events

LOGGER = logging.getLogger('BallonTranslator')


class ScenePresenter:
    """
    MVP Presenter для сцены.

    Responsibilities:
    - Связывает Model (TextBlock[]) и View Interface (ISceneView)
    - Обрабатывает события от View и обновляет Model
    - Загружает данные из Model и говорит View показать
    - Предоставляет доступ к DI сервисам (UndoManager, LayerManager)
    - Интегрирован с EventBus для декомпозиции связей

    Правило: Presenter зависит от View Interface, не от конкретного View.
    """

    def __init__(self, model_list: List[TextBlock], view: ISceneView,
                 undo_manager=None, layer_manager=None):
        """
        Args:
            model_list: List[TextBlock] — список блоков модели
            view: ISceneView — интерфейс View для отображения
            undo_manager: IUndoManager — менеджер undo/redo (опционально)
            layer_manager: ILayerManager — менеджер слоёв (опционально)
        """
        self._model_list = model_list
        self._view = view
        self._undo_mgr = undo_manager
        self._layer_mgr = layer_manager
        self._connected = False
        self._event_bus = EventBus.get_instance()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        """Подписывается на события EventBus."""
        self._event_bus.subscribe(Events.DELETE_TEXT_BLOCKS, self._on_delete_blocks)
        self._event_bus.subscribe(Events.COPY_TEXT_BLOCKS, self._on_copy_blocks)
        self._event_bus.subscribe(Events.PASTE_TEXT_BLOCKS, self._on_paste_blocks)

    def _on_delete_blocks(self, data=None):
        """Обработчик события удаления блоков."""
        LOGGER.debug("[ScenePresenter] delete_blocks event received")

    def _on_copy_blocks(self, data=None):
        """Обработчик события копирования блоков."""
        LOGGER.debug("[ScenePresenter] copy_blocks event received")

    def _on_paste_blocks(self, data=None):
        """Обработчик события вставки блоков."""
        LOGGER.debug("[ScenePresenter] paste_blocks event received")

    def connect_signals(self):
        """Подключает сигналы View к обработчикам Presenter."""
        if self._connected:
            return

        # View signals → Presenter handlers
        if hasattr(self._view, 'incanvas_selection_changed'):
            self._view.incanvas_selection_changed.connect(self._on_selection_changed)

        self._connected = True

    def disconnect_signals(self):
        """Отключает сигналы View от обработчиков Presenter."""
        if not self._connected:
            return

        if hasattr(self._view, 'incanvas_selection_changed'):
            try:
                self._view.incanvas_selection_changed.disconnect(self._on_selection_changed)
            except:
                pass

        self._connected = False

    # ── DI Service Access ──────────────────────────────────────

    def push_undo_command(self, command: Any, update_pushed_step: bool = True):
        """Добавляет команду в стек undo через DI UndoManager."""
        if self._undo_mgr:
            self._undo_mgr.push_command(command)
        elif hasattr(self._view, 'push_undo_command'):
            self._view.push_undo_command(command, update_pushed_step)

    def add_item_to_text_layer(self, item: Any):
        """Добавляет элемент на текстовый слой через DI LayerManager."""
        if self._layer_mgr:
            self._layer_mgr.add_item_to_text_layer(item)
        elif hasattr(self._view, 'add_item_to_text_layer'):
            self._view.add_item_to_text_layer(item)

    # ── View → Model (события от View) ──────────────────────

    def _on_selection_changed(self):
        """Обработчик: выделение изменилось в View → обновляем Model state."""
        if self._view is None:
            return

        selected = self._view.selected_text_items()
        LOGGER.debug("[Presenter] selection changed: %d items", len(selected))

    # ── Model → View (загрузка данных) ───────────────────────

    def load_all_blocks(self):
        """Загружает все блоки из Model и говорит View показать."""
        if self._view is None:
            return

        for idx, block in enumerate(self._model_list):
            self._view.add_block_view(idx)

    def clear_all_blocks(self):
        """Очищает все блоки в View."""
        if self._view is None:
            return

        for idx in range(len(self._model_list) - 1, -1, -1):
            self._view.remove_block_view(idx)

    # ── Presenter → Model (команды) ──────────────────────────

    def add_block(self, rect=None) -> int:
        """Добавляет новый блок в Model."""
        block = TextBlock([0, 0, 0, 0])
        if rect:
            block.xyxy = [int(rect.x()), int(rect.y()),
                         int(rect.right()), int(rect.bottom())]

        self._model_list.append(block)
        idx = len(self._model_list) - 1

        # Говорим View создать визуальный элемент
        if self._view:
            self._view.add_block_view(idx)

        return idx

    def delete_block(self, idx: int):
        """Удаляет блок из Model."""
        if 0 <= idx < len(self._model_list):
            del self._model_list[idx]

            # Говорим View удалить визуальный элемент
            if self._view:
                self._view.remove_block_view(idx)

    def get_block_text(self, idx: int) -> str:
        """Возвращает текст блока из Model."""
        if 0 <= idx < len(self._model_list):
            return self._model_list[idx].translation or ''
        return ''

    def set_block_text(self, idx: int, text: str):
        """Устанавливает текст блока в Model."""
        if 0 <= idx < len(self._model_list):
            self._model_list[idx].translation = text

    def get_block_count(self) -> int:
        """Возвращает количество блоков."""
        return len(self._model_list)

    # ── Presenter → View (инструкции) ────────────────────────

    def select_block(self, idx: int):
        """Говорит View: выделить блок."""
        if self._view:
            self._view.select_block(idx)

    def deselect_block(self, idx: int):
        """Говорит View: снять выделение с блока."""
        if self._view:
            self._view.deselect_block(idx)

    def ensure_block_visible(self, idx: int):
        """Говорит View: сделать блок видимым."""
        if self._view:
            self._view.ensure_block_visible(idx)
