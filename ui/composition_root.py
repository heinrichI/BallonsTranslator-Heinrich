"""
CompositionRoot — единственная точка сборки приложения.

Создаёт и связывает все компоненты через конструкторное внедрение.

DIContainer / Service Locator удалён (решение A, ARCHITECTURE_REFACTOR_PLAN.md):
в production-коде ``DIContainer.resolve`` не имел ни одного вызывающего места —
сервисы «внедрялись» патчем приватных атрибутов (``canvas._undo_mgr = ...``)
после сборки, а зарегистрированная в контейнере модель теньсялась
класс-уровневым экземпляром в MainWindow. Теперь корень явно создаёт
единственный набор сервисов и передаёт их в MainWindow конструктором.
"""

from typing import Any

from qtpy.QtWidgets import QApplication

from utils.config import ProgramConfig
from utils.proj_imgtrans import ProjImgTrans


class CompositionRoot:
    """Composition root — фабрика сборки приложения.

    Responsibilities:
    - создание сервисов (UndoManager, LayerManager, ClipboardService, ScaleManager);
    - создание единственного экземпляра модели данных (ProjImgTrans);
    - передача всего в MainWindow через конструктор.
    """

    @staticmethod
    def build(
        config: ProgramConfig,
        app: QApplication,
        open_dir: str = '',
        **exec_args: Any,
    ) -> "MainWindow":
        """Собирает все зависимости и возвращает MainWindow.

        Args:
            config: Конфигурация приложения
            app: QApplication
            open_dir: Директория для открытия
            **exec_args: Дополнительные аргументы (прокидываются в MainWindow
                и, в HEADLESS-режиме, в run_batch)

        Returns:
            MainWindow
        """
        from .clipboard_service import ClipboardService
        from .event_bus import EventBus
        from .layer_manager import LayerManager
        from .mainwindow import MainWindow
        from .scale_manager import ScaleManager
        from .undo_manager import UndoManager

        # Синглтон EventBus создаётся один раз в точке сборки.
        EventBus.get_instance()

        # Единственный экземпляр модели данных: раньше он теньсялся
        # класс-уровневым ``MainWindow.imgtrans_proj`` (решение A).
        proj: ProjImgTrans = ProjImgTrans()
        undo_mgr: UndoManager = UndoManager()
        layer_mgr: LayerManager = LayerManager()
        clipboard_svc: ClipboardService = ClipboardService()
        scale_mgr: ScaleManager = ScaleManager()

        return MainWindow(
            app, config,
            open_dir=open_dir,
            proj=proj,
            undo_mgr=undo_mgr,
            layer_mgr=layer_mgr,
            scale_mgr=scale_mgr,
            clipboard_svc=clipboard_svc,
            **exec_args,
        )