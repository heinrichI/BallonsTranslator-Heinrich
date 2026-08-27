# Implementation Plan — Ctrl+Z не откатывает перевод текстового блока

## [Overview]

Починить undo перевода текстового блока: после запуска перевода нажатие Ctrl+Z в редакторе перевода (TransTextEdit) не возвращает предыдущий перевод.

**Первопричина (подтверждена кодом и git-историей):** до DI-рефакторинга `Canvas.push_undo_command()` выбирал стек по `textEditMode()` (см. `git show 57ce777~1:ui/canvas.py:933-939`) — команда перевода попадала в текстовый стек. После рефакторинга DI-ветка `Canvas.push_undo_command` (canvas.py:1131) вызывает `UndoManager.push_command(command)` с дефолтным `is_text=False`, поэтому `RunBlkTransCommand` (push из mainwindow.py:1343) уходит в **draw-стек**. Тот же дефект в DI-ветке `Canvas._push_text_command_internal` (canvas.py:1008). А Ctrl+Z внутри редактора перевода идёт по цепочке `SourceTextEdit.keyPressEvent (textedit_area.py:260-283, undo_signal на :66) → подключение transpair_wiring.py:62 → SceneTextManager.on_textedit_undo (scenetext_manager.py:1225) → canvas.undo_textedit() (canvas.py:1035) → UndoManager.undo_text()` — только **текстовый стек**. Команды перевода там нет — откат не происходит.

Тот же корень ломает: шрифтовые команды (`fontformat_commands.py:177`, единственный push-сайт `TextStyleUndoCommand`/`SelectionOutlineUndoCommand`), глобальную замену (`mainwindow.py:1558`), вставку исходников (`mainwindow.py:1669`), все 12 команд через `SceneTextManager.push_undo_command` (scenetext_manager.py:450, дефолт `is_text=False`: move/create/delete/reshape/rotate/paste/reorder/auto-layout/squeeze/reset-angle/multi-paste) и `ScenePresenter.push_undo_command` (scene_presenter.py:97 — параметра `is_text` нет вовсе).

**Подход (выбран пользователем: «полное + маркировка»):**
1. классификация команд в `UndoManager` по атрибуту `is_text_command`;
2. восстановление mode-based маршрутизации в `Canvas.push_undo_command` и auto-режима в `SceneTextManager.push_undo_command` / `ScenePresenter.push_undo_command`;
3. явная маркировка текстовых команд атрибутом `is_text_command = True` (список в [Classes]);
4. счётчики шагов canvas в DI-ветке ведутся по **фактическому** решению маршрутизации (а не по `textEditMode()`) — устраняет расхождение «счётчик текста растёт, а команда в draw-стеке».

## [Types]

- Новая конвенция: опциональный атрибут `is_text_command: bool` у наследников `QUndoCommand`.
  - `is_text_command = True` — текстовая команда (текстовый стек) независимо от режима;
  - атрибут отсутствует — режимозависимая команда (стек выбирается по `canvas.textEditMode()`, как до рефакторинга);
  - `is_text_command = False` (явно) — draw-стек.
- Семантика `is_text` (формула плана: `is_text = is_text or attr`): `is_text=True` (явно) — текстовый стек; `is_text=False` (явно) — draw-стек, но **не снимает** class-маркировку `is_text_command = True`; атрибут — страховка от «демаркации» в рантайме.
- `SceneTextManager.push_undo_command(..., is_text=None)`: `None` — авто (атрибут, иначе mode), `True` — текстовый стек, `False` — draw-стек.
- `Canvas.push_undo_command(..., is_text=None)` — та же семантика.

## [Classes]

Маркируются `is_text_command = True`:

`ui/textedit_commands.py`:
- `GlobalRepalceAllCommand` (L468) — **асинхронный** push из `on_global_replace_finished` (mainwindow.py:1558): к моменту push режим мог смениться, поэтому страховочная маркировка (как у `RunBlkTransCommand`).

Остальные 12 классов — **намеренно не маркируются**:
- 5 уже пушатся с явным `is_text=True` на сайтах (scenetext_manager.py: `TextItemEditCommand` L1254, `TextEditCommand` L1260, `ApplyFontformatCommand` L1282, `PageReplaceOneCommand` L1335, `PageReplaceAllCommand` L1338);
- 7 синхронных (move/reshape/rotate/squeeze/reset-angle/auto-layout/multi-paste) покрывает mode-based fallback: в реальном приложении они пушатся только в текстовом режиме (`editor_index == 1`; flow-блоки тоже живут в текстовом режиме).
  Важно: `MoveBlkItemsCommand` нельзя маркировать — тесты `tests/ui/test_flow_block_move_undo.py` и `test_flow_block_move_undo_integration.py` фиксируют его попадание в draw-стек на уровне менеджера (`push_command(is_text=False)`), а smart-undo на уровне canvas при этом работает.

`ui/fontformat_commands.py`:
- `TextStyleUndoCommand` (L50)
- `SelectionOutlineUndoCommand` (L66)

`ui/scenetext_manager.py`:
- `PasteSrcItemsCommand` (L276)

`ui/drawing_commands.py`:
- `RunBlkTransCommand` (L84) — class-атрибут;
- `EmptyCommand` (L79) — **не** помечается на уровне класса: instance-атрибут `self.empty_command.is_text_command = True` в ветке `mode > 1` (L89-91).
  ⚠️ Второй, не связанный класс `EmptyCommand` в `scenetext_manager.py:92` (мёртвый код) — не путать.

**Не маркируются** (осознанно остаются на mode-based fallback — пушатся только в текстовом режиме, их закрывает фикс роутинга canvas):
- `CreateItemCommand`, `DeleteBlkItemsCommand`, `PasteBlkItemsCommand`, `RearrangeBlksCommand` (scenetext_manager.py:71/97/247/292)
- `MoveByKeyCommand` (canvas.py:37, push на canvas.py:547)

## [Files]

- `ui/undo_manager.py` — модифицировать `push_command()` (L97): атрибутная классификация.
- `ui/canvas.py` — модифицировать `push_undo_command()` (L1119; DI-ветка L1131) и `_push_text_command_internal()` (L1001; DI-ветка L1008); счётчики — по решению маршрутизации.
- `ui/scenetext_manager.py` — модифицировать `push_undo_command()` (L450): `is_text=None`-авто, учёт `update_pushed_step`; пометить `PasteSrcItemsCommand` (L276).
- `ui/scene_presenter.py` — модифицировать `push_undo_command()` (L97): добавить `is_text`, та же классификация в fallback-ветке.
- `ui/textedit_commands.py` — пометить `GlobalRepalceAllCommand` (см. [Classes]).
- `ui/fontformat_commands.py` — пометить `TextStyleUndoCommand`, `SelectionOutlineUndoCommand`.
- `ui/drawing_commands.py` — пометить `RunBlkTransCommand`, instance-атрибут для его `empty_command`.
- `ui/mainwindow.py` — **без изменений** (строки 1343/1558/1669 чинятся классификацией).
- `tests/ui/test_undo_manager.py` — расширить (атрибутная классификация).
- `tests/ui/test_blktrans_undo.py` — новый файл тестов.

## [Functions]

1. `UndoManager.push_command(command, update_step=False, is_text=False)` (ui/undo_manager.py:97): в начале добавить `is_text = is_text or bool(getattr(command, 'is_text_command', False))`. Остальное без изменений.
2. `Canvas.push_undo_command(command, update_pushed_step=True, is_text=None)` (ui/canvas.py:1119): разрешить `is_text` (`None` → атрибут, при отсутствии → `textEditMode()`). В DI-ветке (L1131): `self._undo_mgr.push_command(command, is_text=is_text)`; счётчики инкрементить по **фактическому** решению (`is_text` → `num_pushed_textstep`, иначе → `num_pushed_drawstep`). Fallback-ветка (без `_undo_mgr`) уже mode-based — не трогать.
3. `Canvas._push_text_command_internal()` (ui/canvas.py:1001): в DI-ветке (L1008) передавать `is_text=True`.
4. `SceneTextManager.push_undo_command(command, update_pushed_step=True, is_text=None)` (ui/scenetext_manager.py:450): в DI-ветке: `is_text=None` → атрибут, при отсутствии → `self.canvas.textEditMode()`; передавать `update_step=update_pushed_step` (было хардкод `True`; счётчик `_num_pushed_textstep` менеджера нигде не читается — безопасно).
5. `ScenePresenter.push_undo_command(command, update_pushed_step=True, is_text=None)` (ui/scene_presenter.py:97): основная ветка делегирует view (canvas) — `is_text` передавать при явной установке; fallback-ветка (`_undo_mgr` при отсутствии `view.push_undo_command`) — та же классификация: атрибут → `view.textEditMode()` → `False`.
6. `RunBlkTransCommand.__init__()` (ui/drawing_commands.py:84): в ветке `mode > 1` перед `canvas.push_undo_command(self.empty_command)` (L91) добавить `self.empty_command.is_text_command = True`.

## [Tests]

- `tests/ui/test_undo_manager.py`: новый класс `TestCommandAttributeClassification` — команда с `is_text_command=True` попадает в текстовый стек без явного `is_text`; без атрибута → draw; явный `is_text` переопределяет; `undo_text()` трогает только текстовый стек.
- `tests/ui/test_blktrans_undo.py` (новый):
  - `RunBlkTransCommand.is_text_command is True`; класс `EmptyCommand` не помечен (маркируется только инстанс);
  - реальный `Canvas.push_undo_command` (unbound-вызов на stub'е с `_undo_mgr`/`textEditMode`/`drawMode`/`setProjSaveState`): атрибут → текстовый стек даже в draw-режиме; без атрибута → mode-based; счётчики следуют за решением маршрутизации;
  - интеграция: реальный `RunBlkTransCommand(stub_canvas, [], [], mode=2)` — `empty_command` (instance-маркирован) и внешняя команда (class-маркирован) попадают в текстовый стек; два `undo_text()` освобождают текстовый стек, draw-стек не тронут (сценарий Ctrl+Z в редакторе);
  - реальный `SceneTextManager.push_undo_command` (unbound): `is_text=None` — авто (атрибут → mode), явный `is_text` приоритетен;
  - реальный `ScenePresenter.push_undo_command` (unbound): делегирование view + fallback-классификация.

## [Risks]

- Счётчики canvas в DI-режиме используются `on_textstack_changed`/`on_drawstack_changed` (вызываются из `_push_*_internal`) и сбрасываются в `clear_undostack` — привязка к решению маршрутизации сохраняет инвариант «счётчик == глубина соответствующего стека».
- Маркировать класс нельзя «на всякий случай»: `is_text_command = True` переводит команду в текстовый стек **независимо от режима** и ломает зафиксированное тестами поведение (flow-перемещение в draw-стек). Маркировка только для асинхронных push (момент push отделён от запуска операции, режим мог смениться) и классов из явного списка плана.
- Fallback-ветка `SceneTextManager.push_undo_command` (без `_undo_mgr`) идёт через canvas по mode — явный `is_text` там теряется (canvas в fallback не принимает флаг). Ограничение приемлемо: fallback актуален только в не-DI режиме.
- `ui/canvas_undo_manager.py` — мёртвый код (не импортируется нигде); в рамках плана не трогаем.
- `RunBlkTransCommand` помечается как текстовая целиком (в т.ч. inpaint-часть `mode > 1`): команда пушится только из текстового режима (mainwindow.py:1343, `on_blktrans_finished`), поэтому поведение соответствует пред-рефакторинговому (mode-based).
