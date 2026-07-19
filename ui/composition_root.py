"""
CompositionRoot — точка сборки всех зависимостей.

Создает и связывает все компоненты приложения.
"""

from typing import Optional
from qtpy.QtWidgets import QApplication

from utils.config import ProgramConfig
from utils.proj_imgtrans import ProjImgTrans
from .di_container import DIContainer


class CompositionRoot:
    """
    Composition Root — фабрика сборки приложения.

    Responsibilities:
    - Создание сервисов
    - Регистрация в DI контейнере
    - Сборка графа зависимостей
    """

    @staticmethod
    def build(
        config: ProgramConfig,
        app: QApplication,
        open_dir: str = '',
        **exec_args
    ):
        """
        Собирает все зависимости и возвращает MainWindow.

        Args:
            config: Конфигурация приложения
            app: QApplication
            open_dir: Директория для открытия
            **exec_args: Дополнительные аргументы

        Returns:
            MainWindow
        """
        from utils import shared
        from .event_bus import EventBus

        # Очищаем контейнер
        DIContainer.reset()

        # Создаем EventBus
        event_bus = EventBus.get_instance()
        DIContainer.register(EventBus, event_bus)

        # Создаем ProjImgTrans (Model)
        proj = ProjImgTrans()
        DIContainer.register(ProjImgTrans, proj)

        # Создаем сервисы
        from .undo_manager import UndoManager
        from .layer_manager import LayerManager
        from .clipboard_service import ClipboardService
        from .scale_manager import ScaleManager

        undo_mgr = UndoManager()
        layer_mgr = LayerManager()
        clipboard_svc = ClipboardService()
        scale_mgr = ScaleManager()

        # Регистрируем сервисы
        DIContainer.register(UndoManager, undo_mgr)
        DIContainer.register(LayerManager, layer_mgr)
        DIContainer.register(ClipboardService, clipboard_svc)
        DIContainer.register(ScaleManager, scale_mgr)

        # Создаем MainWindow (Canvas создаётся внутри setupUi())
        from .mainwindow import MainWindow
        main_window = MainWindow(app, config, open_dir=open_dir, **exec_args)

        # Устанавливаем DI-сервисы на Canvas после создания
        if hasattr(main_window, 'canvas'):
            main_window.canvas._undo_mgr = undo_mgr
            main_window.canvas._layer_mgr = layer_mgr
            main_window.canvas._scale_mgr = scale_mgr
            main_window.canvas._clipboard_svc = clipboard_svc

        # Устанавливаем DI-сервисы на SceneTextManager после создания
        if hasattr(main_window, 'st_manager'):
            main_window.st_manager._undo_mgr = undo_mgr

        return main_window

    @staticmethod
    def reset():
        """Сбрасывает контейнер (для тестов)."""
        DIContainer.reset()
