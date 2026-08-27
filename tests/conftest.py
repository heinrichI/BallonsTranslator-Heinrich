"""
Общие настройки для всего дерева tests/.

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

import pytest

_DYNAMO_EXIT_HOOKS = (
    ("torch._dynamo.utils", "dump_compile_times"),
    ("torch._dynamo.eval_frame", "_log_traced_frames"),
)

for _module_name, _hook_name in _DYNAMO_EXIT_HOOKS:
    logging.getLogger(_module_name).setLevel(logging.WARNING)


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
