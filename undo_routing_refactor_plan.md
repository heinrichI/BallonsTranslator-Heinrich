# Plan — SOLID-рефакторинг undo-маршрутизации (последователь 302d4be6)

## [Overview]

Коммит `302d4be6` починил маршрутизацию undo-команд (текст/draw), но ввёл
механику с несколькими нарушениями поддерживаемости: разрешение `is_text`
дублируется в 4 модулях, контракт «текстовая команда» задан строковым
атрибутом, в публичном API `UndoManager` живёт fat-метод с флагом, а
неожиданная семантика `or`-формулы прячет явный `False` под атрибутом.

**Цель:** при сохранении поведения (все flow-тесты без изменений по
результатам) превратить механику в:
1. разрешение маршрута **в одном месте** (SRP/DRY);
2. **типовой** маркер текстовых команд (LSP/OCP);
3. публичный API `UndoManager` без boolean-флага (ISP);
4. чистые pass-through'ы в `ScenePresenter`/`SceneTextManager` (SRP слоёв).

**Не цель:** менять, *когда* асинхронные команды фиксируют undo-шаг
(см. [Stage 4] — беклог), менять стеки/сигналы/счётчики.

## [Current state]

| # | Проблема | Где |
|---|---|---|
| 1 | Разрешение `is_text` продублировано в 4 местах (смена приоритета = правка 4 файлов) | `undo_manager.py:104` (формула `or`), `canvas.py:1135-1137`, `scene_presenter.py:114-120`, `scenetext_manager.py:462-464` |
| 2 | Контракт «я текстовая» — строковый атрибут: невидим в IDE, без type-safety, молчаливый LSP-сбой у подкласса, забывшего атрибут | 6 меток: `drawing_commands.py:85,94` (в т.ч. инстансная), `fontformat_commands.py:51,69`, `scenetext_manager.py:277`, `textedit_commands.py:469` |
| 3 | `is_text = is_text or bool(getattr(...))`: явный `False` не переопределяет атрибут — неочевидная семантика | `undo_manager.py:104` |
| 4 | Fat-API: публичный `push_command(is_text=...)` при наличии сегрегированных `push_text_command`/`push_draw_command`; асимметрия `update_step` (есть у text-метода, нет у draw-метода) | `undo_manager.py:97,127,141` |
| 5 | Мёртвый второй «mode»: `set_mode`/`get_mode`/`active_stack`/`_mode` — 0 вызовов в продакшене; латентный рассинхрон с `Canvas.textEditMode()` | `undo_manager.py:35-55` |
| 6 | «Прокси с логикой»: Presenter и Manager сами разрешают `is_text`, а не делегируют | `scene_presenter.py:97-121`, `scenetext_manager.py:452-468` |

Важный факт (проверено): в production-пути `UndoManager.push_command`
всегда получает **уже разрешённый** bool — все три прокси (Canvas,
Presenter, Manager) разрешают атрибут/режим до вызова. Формула `or`
срабатывает только при прямых вызовах из тестов. Удаление формулы
поведенчески безопасно для приложения.

## [Stage 1] Единая точка разрешения (SRP/DRY)

Одна чистая функция; режим приходит **инжектированным** callable, а не
читается из внутреннего состояния.

**`ui/undo_manager.py`** (новый модульный код, `QUndoCommand` уже импортирован):

```python
from typing import Callable, Optional

def resolve_is_text(command: Optional[QUndoCommand],
                    is_text: Optional[bool],
                    mode_is_text: Callable[[], bool]) -> bool:
    """Приоритет: явный аргумент > маркер команды > текущий режим.

    - is_text True/False  — принудительный выбор стека (маркер игнорируется);
    - is_text None        — авто: TextUndoCommand (см. [Stage 2]) или режим.
    """
    if is_text is not None:
        return is_text
    if command is not None and isinstance(command, TextUndoCommand):
        return True
    return mode_is_text()
```

Изменения по файлам:

- **`ui/undo_manager.py`**
  - `push_command`: удалить строку `is_text = is_text or bool(getattr(...))`;
    метод принимает честный bool (формула убрана → явный `False` = draw-стек,
    маркер учитывается только в `resolve_is_text` на уровне canvas).
- **`ui/canvas.py`** `push_undo_command` (L1119-1160):
  ```python
  if is_text is None:
      is_text = resolve_is_text(command, None, self.textEditMode)
  ```
  Ветка `command is None` (счётчики по режиму) и legacy-фолбэк (без DI)
  не трогаются.
- **`ui/scene_presenter.py`** `push_undo_command` (L97-121):
  - ветка «view имеет push_undo_command» — чистый pass-through (логика уже
    в canvas);
  - legacy-ветка `self._undo_mgr` (view без метода — на практике не
    встречается): `is_text = resolve_is_text(command, is_text,
    lambda: bool(self._view.textEditMode()) if hasattr(self._view, 'textEditMode') else False)`,
    затем `push_command(command, is_text=is_text)`.
- **`ui/scenetext_manager.py`** `push_undo_command` (L452-468):
  ```python
  if self._undo_mgr:
      if is_text is None:
          is_text = resolve_is_text(command, None, self.canvas.textEditMode)
      self._undo_mgr.push_command(command, update_step=update_pushed_step, is_text=is_text)
      self.canvas.setProjSaveState(True)
  else:
      self.canvas.push_undo_command(command, update_pushed_step)
  ```
  (эквивалентно текущему, но формула одна — в helper'е).

Приоритет **строго** как сейчас: явный аргумент > маркер > режим.
Разница против `or`-формулы: явный `False` теперь честно означает draw-стек —
в production это не меняет ни одного push (см. [Current state], факт выше).

## [Stage 2] Маркерный базовый класс `TextUndoCommand` (LSP/OCP)

**Расположение: `ui/undo_manager.py`.** Проверено по импортам:
`undo_manager` не импортирует ни одного ui-модуля (только qtpy), поэтому
`from .undo_manager import TextUndoCommand` в command-файлах не создаёт
цикла:

```python
class TextUndoCommand(QUndoCommand):
    """Команда текстового стека: отменяется Ctrl+Z внутри редактора.

    Маркировка обязательна для команд, push которых может произойти вне
    текстового режима (асинхронные финиши). Синхронные команды текстового
    режима могут полагаться на mode-fallback и маркера не требуют.
    """
```

**Конвертация меток (5 классовых + 1 инстансная → наследование):**

| Сейчас | Станет |
|---|---|
| `drawing_commands.py:85` `RunBlkTransCommand.is_text_command = True` | `class RunBlkTransCommand(TextUndoCommand)` |
| `drawing_commands.py:94` `self.empty_command.is_text_command = True` | **остаётся явный флаг в точке push**: `canvas.push_undo_command(self.empty_command, is_text=True)` — `EmptyCommand` общая с не-текстовыми использованиями, в `TextUndoCommand` её не переводим |
| `fontformat_commands.py:51` `TextStyleUndoCommand` | `class TextStyleUndoCommand(TextUndoCommand)` |
| `fontformat_commands.py:69` `SelectionOutlineUndoCommand` | `class SelectionOutlineUndoCommand(TextUndoCommand)` |
| `scenetext_manager.py:277` `PasteSrcItemsCommand` | `class PasteSrcItemsCommand(TextUndoCommand)` |
| `textedit_commands.py:469` `GlobalRepalceAllCommand` | `class GlobalRepalceAllCommand(TextUndoCommand)` |

Все 6 атрибутов `is_text_command` удаляются; строковый `getattr` исчезает из
кода целиком (заменяется `isinstance` в `resolve_is_text`).

**Намеренно не маркируются** (fix по `implementation_plan.md`):
- геометрические команды (move/reshape/rotate/squeeze/reset-angle и т.д.) —
  mode-fallback; `MoveBlkItemsCommand` зафиксирован flow-тестами в draw-стек;
- 5 команд, уже пушащихся с явным `is_text=True` на сайтах
  (`TextItemEditCommand`, `TextEditCommand`, `ApplyFontformatCommand`,
  `PageReplaceOneCommand`, `PageReplaceAllCommand`) — явный аргумент имеет
  приоритет, маркер им не нужен.

## [Stage 3] Публичный API без флага (ISP) + чистые прокси (SRP слоёв)

**`ui/undo_manager.py`:**
- публичные push-API: `push_text_command(command, update_step)` и
  `push_draw_command(command, update_step)` (у draw-метода добавить
  `update_step: bool = False` для симметрии — сейчас `update_step` игнорирует
  draw-счётчик, которого в UndoManager нет; параметр принимаем, но
  инкрементировать там нечего — счётчик draw живёт в Canvas; это осознанный
  компромисс, чтобы сигнатуры были одинаковы для вызывающих);
- `push_command(command, update_step, is_text)` → приватный
  `_route(command, is_text: bool)` без формулы (используется canvas-фолбэком
  и Presenter-фолбэком); публичного флага в API больше нет.
- Удалить мёртвый код: `_mode`, `set_mode`, `get_mode`, `active_stack`
  (проверено: 0 вызовов в production и тестах).

**`ui/canvas.py`** DI-ветка `push_undo_command`:
```python
resolved = resolve_is_text(command, is_text, self.textEditMode)
if resolved:
    self._undo_mgr.push_text_command(command)
else:
    self._undo_mgr.push_draw_command(command)
self.setProjSaveState(True)
# счётчики — по resolved (уже так в 302d4be6, не менять)
```
`_push_text_command_internal` (canvas.py:1008): `push_command(..., is_text=True)`
→ `push_text_command(command)`.

**`ui/scene_presenter.py` / `ui/scenetext_manager.py`:** чистые
pass-through'ы — разрешение только через `resolve_is_text` (один вызов),
без дублирования цепочки getattr/mode. Для `SceneTextManager` это
поведенчески тождественно: DI-ветка canvas сама делает
`setProjSaveState(True)`, дублирующий вызов в Manager'е при делегировании
не нужен (текущий прямой вызов `push_command` в Manager'е при этом
исчезает — push идёт через canvas).

## [Stage 4] Беклог: undo-шаг в момент действия пользователя (корневая причина)

Асинхронные команды (`RunBlkTransCommand` — push из
`on_blktrans_finished`, mainwindow.py:1343; `GlobalRepalceAllCommand` — из
`on_global_replace_finished`, mainwindow.py:1558) фиксируют undo-шаг в
момент **завершения** фоновой работы, когда режим UI уже не источник
истины — именно поэтому нужны маркеры/явные флаги.

Учебный паттерн: **ленивая команда** — в момент старта действия (режим ещё
текстовый) пушится placeholder-команда в текстовый стек; результат
асинхронной работы подставляется в неё, применяясь в `redo()`; `undo()`
восстанавливает исходное состояние. Тогда:
- mode-fallback становится универсально корректным;
- маркеры/флаги для асинхронных команд уходят;
- undo-история появляется **до** завершения перевода (улучшение UX:
  Ctrl+Z сразу отзывается, а не после).

Ценой: переработка семантики redo (идемпотентность повторного применения,
хранение результата в команде), вложенный `EmptyCommand`-трюк для `mode > 1`
требует отдельного разбора. **Отдельный проект**, после стабилизации
стадий 1–3.

## [Files]

- `ui/undo_manager.py` — helper `resolve_is_text`, `TextUndoCommand`, API
  (Stage 1–3), удаление формулы и мёртвого mode-кода.
- `ui/canvas.py` — `push_undo_command`, `_push_text_command_internal` (Stage 1, 3).
- `ui/scene_presenter.py` — pass-through (Stage 1, 3).
- `ui/scenetext_manager.py` — pass-through + `PasteSrcItemsCommand` (Stage 1, 2, 3).
- `ui/drawing_commands.py` — `RunBlkTransCommand`, явный флаг у вложенного `EmptyCommand` (Stage 2, 3).
- `ui/fontformat_commands.py` — `TextStyleUndoCommand`, `SelectionOutlineUndoCommand` (Stage 2).
- `ui/textedit_commands.py` — `GlobalRepalceAllCommand` (Stage 2).
- `tests/ui/test_undo_manager.py`, `tests/ui/test_blktrans_undo.py`,
  `tests/ui/test_save_detection.py`, `tests/ui/test_global_undo_shortcut.py`,
  `tests/ui/test_flow_block_move_undo.py`,
  `tests/ui/test_flow_block_move_undo_integration.py` — адаптации ([Tests]).

Не затрагиваются: `mainwindow.py` (точки push остаются без изменений —
маршрут определяет тип команды, а не вызывающий код), `implementation_plan.md`.

## [Tests]

**Адаптация (без изменения проверяемого поведения):**
- `test_blktrans_undo.py:77-101` — ассёрты
  `getattr(Cmd, 'is_text_command', False) is True` →
  `issubclass(Cmd, TextUndoCommand)`; ассерт «у `EmptyCommand` атрибута нет»
  → «`EmptyCommand` — не `TextUndoCommand`, а push из
  `RunBlkTransCommand.__init__` ушёл в текстовый стек» (E2E-часть файла
  остаётся и покрывает именно это).
- `test_undo_manager.py:65-223` — прямые `push_command(cmd, is_text=...)` →
  `push_text_command`/`push_draw_command`; тест `_AttrTextCmd` (L156) →
  юнит-тест `resolve_is_text` + тест на `TextUndoCommand`.
- `test_save_detection.py:67,194-231`, `test_global_undo_shortcut.py:180,206`,
  `test_flow_block_move_undo.py:125`,
  `test_flow_block_move_undo_integration.py:102` — замена прямых
  `push_command(...)` на явные stack-методы (semantics 1:1:
  `is_text=True → push_text_command`, иначе → `push_draw_command`).

**Новые:**
- юнит-тесты `resolve_is_text` без Qt-инстансов: приоритет явного аргумента
  (True и False), маркер, fallback на режим, `command=None` → режим.
- регрессионный: «явный `is_text=False` + `TextUndoCommand` → draw-стек»
  (фиксирует новую честную семантику против старой `or`-формулы).

**Обязательный прогон после каждого коммита** (AGENTS.md):
`myenv\Scripts\python.exe -m pytest tests/ -q`.

## [Risks]

1. **Поведенческая эквивалентность.** Приоритет «явный > маркер > режим»
   сохраняется во всех 4 местах; отличие лишь в «явный False + маркер»,
   который в production не встречается (все прокси разрешают до вызова
   `push_command`). Покрытие: E2E-тесты blktrans + полный прогон.
2. **Fix'ы flow-тестов.** `MoveBlkItemsCommand` и другие геометрические
   команды **не** получают `TextUndoCommand` — иначе сломается
   `test_flow_block_move_undo.py:125` (ожидает draw-стек). Страховка: тест
   «MoveBlkItemsCommand не является TextUndoCommand».
3. **Импорт `TextUndoCommand`.** Проверено: `undo_manager` не импортирует
   ui-модули → цикла нет; тем не менее первый коммит проверяется полным
   прогонсом (импорты рисуются при старте Qt-тестов).
4. **Прямые вызовы `push_command` в тестах** — самый большой объём правок
   (≈25 мест). Механическая замена, семантика 1:1.
5. **Stage 3 меняет публичное API `UndoManager`** — если DI-контейнер или
   внешний код держат ссылку на `push_command`, это видно только рантаймом.
   Митигация: grep по репо перед коммитом (известные вызывающие: canvas,
   presenter, manager, тесты) + полный прогон.

## [Rollout]

- **Коммит 1 (Stage 1 + 2):** helper + `TextUndoCommand` + конвертация 5
  классов + удаление формулы/атрибутов + адаптация тестов.
  Поведенчески нейтрален.
- **Коммит 2 (Stage 3):** ISP-фасад `_route`, симметрия `update_step`,
  удаление мёртвого mode-кода, pass-through'ы Presenter/Manager.
- После каждого коммита — полный прогон `myenv\Scripts\python.exe -m pytest tests/ -q`.
- **Stage 4** — отдельный тикет/бэклог после стабилизации.
