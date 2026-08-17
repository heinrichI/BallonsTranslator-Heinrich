"""
Разделяемые Qt-фикстуры для tests/ui.

Все тестовые модули этого каталога раньше имели идентичные копии
фикстур `qapp` / `scene` — теперь единая общая реализация живёт здесь.

Также заботится об окружении до импорта тестовых модулей:
QT_QPA_PLATFORM=offscreen и корень репозитория в sys.path
(pytest.ini/`__init__.py` нет, pytest добавляет в sys.path только
каталог tests/ui, но не корень репозитория).
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from qtpy.QtWidgets import QApplication, QGraphicsScene, QGraphicsView


@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на всю сессию (offscreen)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def scene(qapp):
    """Свежая QGraphicsScene для каждого теста (с view для screen-трансформаций)."""
    s = QGraphicsScene()
    view = QGraphicsView(s)
    view.resize(2000, 2000)
    yield s
    s.clear()
