"""
MainPresenter — Presenter для MainWindow.

Выделяет бизнес-логику из MainWindow (MVP: Model > Presenter > View).
"""

from typing import Optional, TYPE_CHECKING
from qtpy.QtCore import QObject
import os.path as osp

from utils.logger import logger as LOGGER
from utils.config import pcfg
from .event_bus import EventBus, Events

if TYPE_CHECKING:
    from .mainwindow import MainWindow
    from utils.proj_imgtrans import ProjImgTrans


class MainPresenter(QObject):
    """
    Presenter для MainWindow — бизнес-логика.

    Responsibilities:
    - Навигация по страницам
    - Сохранение проекта
    - Pipeline перевода
    - Управление проектом
    """

    def __init__(self, model: 'ProjImgTrans', view: 'MainWindow', event_bus: EventBus):
        super().__init__()
        self._model = model
        self._view = view
        self._event_bus = event_bus
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        """Подписка на события EventBus."""
        self._event_bus.subscribe(Events.UNDO, self._on_undo)
        self._event_bus.subscribe(Events.REDO, self._on_redo)

    def open_project(self, dir_path: str):
        """Открывает проект из директории."""
        try:
            self._view.opening_dir = True
            self._model.load(dir_path)
            self._view.st_manager.clearSceneTextitems()
            self._view.titleBar.setTitleContent(osp.basename(dir_path))
            self._view.updatePageList()
            self._view.opening_dir = False
            self._event_bus.publish(Events.PROJECT_OPENED, dir_path)
        except Exception as e:
            self._view.opening_dir = False
            from utils.message import create_error_dialog
            create_error_dialog(e, self._view.tr('Failed to load project ') + dir_path)

    def save_current_page(self, update_scene_text=True, save_proj=True,
                          restore_interface=False, save_rst_only=False,
                          keep_exist_as_backup=False):
        """Сохраняет текущую страницу."""
        self._view.saveCurrentPage(
            update_scene_text=update_scene_text,
            save_proj=save_proj,
            restore_interface=restore_interface,
            save_rst_only=save_rst_only,
            keep_exist_as_backup=keep_exist_as_backup
        )

    def on_page_changed(self, page_idx: int):
        """Обработчик смены страницы."""
        self._view.pageListCurrentItemChanged()

    def _on_undo(self, data=None):
        """Обработчик undo."""
        if hasattr(self._view, 'canvas'):
            self._view.canvas.undo()

    def _on_redo(self, data=None):
        """Обработчик redo."""
        if hasattr(self._view, 'canvas'):
            self._view.canvas.redo()

    def manual_save(self):
        """Ручное сохранение."""
        if self._view.leftBar.imgTransChecker.isChecked() \
            and self._model.directory is not None:
            LOGGER.debug('Manually saving...')
            self.save_current_page(update_scene_text=True, save_proj=True,
                                  restore_interface=True, save_rst_only=False)
