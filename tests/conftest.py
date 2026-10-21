"""
Общие настройки для всего дерева tests/.

STRICT-режим текстовых инвариантов (BTRANS_STRICT_TEXT_SYNC): в тестах
рассогласование панели / документа item / blk.translation обязано быть
падением, а не молчаливым re-sync'ом — иначе тест «починил» текст и стал
зелёным (PLAN_panel_edit_propagation.md §5.3).

Затухание atexit-дампов torch._dynamo ("TorchDynamo compilation metrics",
"TorchDynamo attempted to trace the following frames"):
оба хука регистрируются без условия при импорте (torch/_dynamo/utils.py:444,
torch/_dynamo/eval_frame.py:389) и пишут при завершении процесса — когда
pytest уже закрыл потоки, поэтому консольный handler (ColoredLogger из
utils/logger.py) улетает в ValueError: I/O operation on closed file.

Два уровня защиты:
1. Уровень листовых логгеров поднимается до WARNING ещё до импорта torch.
   Именно листовых: application делает `logging.setLoggerClass(ColoredLogger)`,
   и ColoredLogger.__init__ прописывает каждому НОВОМУ логгеру явный INFO —
   уровень родительских логгеров тогда игнорируется. До импорта torch
   логгеров ещё нет, `getLogger` создаёт их, и при импорте torch просто
   переиспользует (уровень проверяется в момент emit).
2. Session-фикстура снимает atexit-хуки целиком — надёжный уровень: даже
   если уровни будут переопределены приложением, дампы просто не
   выполнятся.
"""
import atexit
import importlib
import logging
import os
import sys

os.environ.setdefault("BTRANS_STRICT_TEXT_SYNC", "1")

import pytest

# pytest (без pytest.ini/__init__.py) добавляет в sys.path только каталог
# conftest, поэтому корень репозитория поднимает сам conftest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui import text_coords as TC

_DYNAMO_EXIT_HOOKS = (
    ("torch._dynamo.utils", "dump_compile_times"),
    ("torch._dynamo.eval_frame", "_log_traced_frames"),
)

for _module_name, _hook_name in _DYNAMO_EXIT_HOOKS:
    logging.getLogger(_module_name).setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def _isolate_text_diagnostics():
    """Дедупликация `[SYNC]`-логов и счётчик сессии — состояние процесса.
    Тесты не должны наследовать его друг у друга: иначе лог рассогласования
    «исчезает» в зависимости от порядка запуска."""
    TC.reset_dedup()
    TC.reset_trip_counts()
    yield


@pytest.fixture(autouse=True, scope="session")
def _silence_torch_dynamo_atexit():
    """Снимает atexit-хуки torch._dynamo (дампы compile-metrics и
    traced-frames): в тестах это только шум после закрытия потоков.

    К запуску первой фикстуры все тестовые модули уже собраны
    (импортированы), так что если где-то в пакете импортирован torch,
    соответствующие модули torch._dynamo уже доступны.
    """
    for module_name, hook_name in _DYNAMO_EXIT_HOOKS:
        try:
            hook = getattr(importlib.import_module(module_name), hook_name)
        except ImportError:
            continue
        atexit.unregister(hook)
    yield
