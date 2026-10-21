# Баг: текст в баллоне «пережёвывается» при правке в панели перевода

Отчёт: `bug1.txt` (панель: `ВИДЕШЬ? У НЕГО...`, баллон: `ВИДШЬЕГО С ЭТИМ КАКИЕ-ТО...`).
Воспроизведение (offscreen): `_probe_bug1.py` → `_probe_bug1_out.txt`.
Статус: **не исправлено**. Это локальная регрессия, в апстриме её нет.

---

## 1. Root cause

`propagate_user_edit()` — `ui/textedit_commands.py:25-40` — переносит каждое пользовательское
изменение из одного `QTextDocument` в другой **позиционно**:

```python
ori_count  = target_edit.document().characterCount()   # документ item
new_count  = src_edit.document().characterCount()      # документ панели
removed    = ori_count + len(added_text) - new_count   # ← арифметика двух РАЗНЫХ документов
cursor.setPosition(pos)                                # pos — офсет ИСТОЧНИКА (панели)
if removed > 0: cursor.setPosition(pos + removed, KeepAnchor)
cursor.insertText(added_text)
```

Такой перенос корректен **только если два документа индекс-идентичны** (так и было в апстриме,
коммит `b77c884`, 2025-01-23).

Дальше:

| коммит | дата | изменение |
|---|---|---|
| `1058008` | 2026-06-14 | в **документ** `FlowTextBlkItem` вставляются soft hyphens `U+00AD` (`_hyphenate_text`, `ui/flow_textitem.py:83`, применяется в `setPlainText:382` / `setHtml:392` / `setPlainTextAndKeepUndoStack:399`). Панель при этом тоже содержала hyphens → документы идентичны, propagate цел. |
| `283c0ec` (HEAD) | 2026-10-21 | «clean panel»-фикс: `ui/transpair_wiring.py:48` теперь пишет в панель `toPlainText().replace('\u00ad','')`, плюс стрип `U+00AD` на всех записях в модель (`block_manager.py:136`, `text_block_presenter.py:75,111`, `scenetext_manager.py:1350-1358`). **Инвариант сломан, а путь propagate маппинга не получил.** |

Итого для flow-блока документ item = clean + **H** штук `U+00AD`, панель = clean:

1. `pos` занижен на (число hyphens левее позиции) → вставка/удаление уезжает не туда;
2. `removed` завышен ровно на **H** → чистая вставка/замена «N в N» выполняется как
   «удалить N+H и вставить» → реальные символы съедаются.

### Подтверждение (пробник, flow-блок, H = 3)

`ВИДИТЕ? У НЕГО С ЭТИМ КАКИЕ-ТО...` → `_hyphenate_text` → `ВИ\xadДИ\xadТЕ? У НЕГО С ЭТИМ КА\xadКИЕ-ТО...`
hyphens в документных позициях `[2, 5, 26]`; pyphen `ru_RU` в venv есть (`hyph_ru_RU.dic`).
⚠ Строки в `bug1.txt` сокращены, реальный текст блока длиннее → реальный `H` больше
(каждое слово ≥5 букв даёт +1…2 hyphens), т.е. и порча в бою сильнее, чем в пробнике.

```
panel op: replace[3:6] = 'ЕШЬ'   → propagate: pos=3  removed_computed=6  (реально 3)
panel op: replace[5:6] = ''      → propagate: pos=5  removed_computed=4  (реально 1)

FINAL panel : 'ВИДЕШЬ? У НЕГО...'   ✓
FINAL item  : 'ВИЕШЬ У НЕГО ...'    ✗  (съедены 'Д' и '?')
CONTROL (обычный TextBlkItem, H=0): item = 'ВИДЕШЬ? У НЕГО...'  ✓
```

Косвенное подтверждение по строке из отчёта: испорченный участок
`ВИД|ШЬ|ЕГО` лежит ровно вокруг hyphen-позиций `[2, 5]` — т.е. порча привязана к местам
вставки `U+00AD`, а хвост `С ЭТИМ КАКИЕ-ТО...` выживает.

### Закон чётности длин (главная диагностика для реального случая)

Внимание: в `bug1.txt` обе строки **сокращены многоточием** (автор оставил только начало),
поэтому числа ниже по `H` и позициям — лишь для фрагмента, а не для реального блока.

Инвариант арифметики `propagate_user_edit`. Пусть `D_k = len(doc_k) − len(panel_k)`
(для flow-документа `D_0 = H` — число `U+00AD` в документе). Тогда для любой правки
(удалили `real_removed`, вставили `added`):

```
removed_computed = len(doc) + len(added) − len(panel_after) = D_k + real_removed
D_{k+1} = len(doc) − removed_computed + len(added) − len(panel_after) = 0
```

Т.е. после **первой же** правки `len(doc) == len(panel)` навсегда (дефицит в H съедается
первым over-deletion'ом), а дальше удаляется правильное **число** символов, но не там,
где надо — этим объясняется «испорчена голова, хвост цел» в отчёте. Следствия:

1. **Диагностический тест на реальном проекте:** если после порчи
   `len(item.document().toPlainText()) == len(e_trans.toPlainText())` — виновата чисто
   позиционная прошивка; если длины **разные** — подключился второй писатель (см. ниже).
   Замер: `QT_QPA_PLATFORM=offscreen` + загрузить проект, взять `blk.rich_text`/`translation`.
2. Точный подбор по сокращённым строкам (`_repro_bug1_exact.py`, `_repro_bug1_h.py`)
   совпадения не даёт — это ожидаемо: нужны полные строки (см. «что нужно ниже»).

**Возможный второй писатель** (проверяется тестом чётности выше, п.1):
путь, который перезаписал документ item текстом, **отстающим** от панели. Кандидаты —
точки массовой записи по снапшоту:
   `AutoLayoutCommand.redo/undo` (`textedit_commands.py:244-262`: `item.setPlainText('')` +
   `item.setHtml(html)`, где `html` снят ещё при создании команды),
   `ApplyFontformatCommand.undo/redo` (`:141`), `drawing_commands.py:106,148`
   (`trs = blk.translation` → `item.setPlainText(trs)`; модель отстаёт, т.к. пишется только
   при save), `text_layout_manager.py:110-111,169,193,314,364` (auto-fit/автоlayout берут
   текст item и перезаписывают его), а также undo/redo-replay (`TextEditCommand:364-385`).

**Что нужно для bit-exact репро (T1) и для точного H:**
- полные строки этого баллона (без многоточия) — было / стало / что показали в баллоне;
- проект (`config/*.json` + папка с `text`), где воспроизводили: видно, что именно осело в
  `translation`/`rich_text` блока (это и есть замер п.1);
- ответы: нажимались ли автоlayout / «подобрать размер» / Ctrl+Z во время правки;
- лог с `QUIET_UI = False` (`ui/textitem.py:27` и др.). А после внедрения ассертов §5
  писатель-виновник называется в логе **сам**: `[SYNC] I1 … after <операция>` — без разбора.

### Почему это тихо дожило до релиза

- **Ни один тест не вызывает `propagate_user_edit`** (`grep propagate tests/` → 0 совпадений).
- Направление панель→item молчит в логах; после focus-out испорченный **item** является
  источником правды в модель (`ui/block_manager.py:136`), т.е. порча ещё и **сохраняется
  в проект-файл** (`blk.translation`, `blk.rich_text`).

### Обратное направление (правка прямо на canvas) — тот же баг, другой знак

`ui/scenetext_manager.py:1299-1304` → `propagate_user_edit(blk_item, edit, ...)`:
`src` = hyphenated item, `dst` = чистая панель → `removed` уходит в минус, ветка удаления
(`:36`) молча пропускается, а `pos` завышен на число hyphens левее → в панель текст
вставляется со сдвигом и дублированием.

---

## 2. Соседние точки той же_class (дрейфdocuments, а не только typing)

| # | место | проблема |
|---|---|---|
| L1 | `ui/textedit_commands.py:247`, `:256` (`AutoLayoutCommand.redo/undo`) | `trans_widget.setPlainText(item.toPlainText())` — литьё **hyphenated** текста в панель. Панель перестаёт быть clean, и из-за idempotence-guard (`flow_textitem.py:121`) последующие `setPlainText` не перегифенизируют → **H меняется посреди сессии**, порча становится недетерминированной (правдоподобно объясняет «хвост выжил» в отчёте). |
| L2 | `ui/scenetext_manager.py:1201` (`layout_textblk` c `text=None`, см. `ui/text_layout_manager.py:110-111`) | в панель летит `item.toPlainText()` с `U+00AD` + жёсткими `\n` (mask mode). |
| L3 | `ui/global_search_widget.py:260` | `blk.translation = doc.toPlainText()` из `rich_text` (с hyphens) → дальше в `textedit_commands.py:544/564`. |
| S1 | `ui/textedit_commands.py:475-478` (`PageReplaceAllCommand`), `:513-515` (`GlobalRepalceAllCommand`), `:395, 411-418` (`PageReplaceOneCommand`) | спаны, полученные из панели / модели / `rich_text`, применяются к документу item **вербатим**, без hyphen-маппинга; `insertText` не перегифенизирует. |
| S2 | `ui/text_layout_manager.py:386-416` `_restore_charfmts` + `ui/textitem.py:2167-2178` `get_char_fmts` | «1 формат на 1 clean-символ», hyphens сдвигают выравнивание. |
| C1 | `ui/textedit_area.py:111-122` `contextMenuEvent` | `paste_flag` по позиционным индексам `acts[3]/[5]/[6]` стандартного меню — хрупко само по себе (в коде есть комментарий-предупреждение). |
| C2 | `characterCount()` | = `len(toPlainText())+1` только при равном числе блоков; `\n` (Return в панели `textedit_area.py:280-283`, item `textitem.py:930-934`, mask-автоlayout) ломает компенсацию даже при H=0. `cursor.selectedText()` к тому же возвращает `U+2028` вместо `\n`. |
| D1 | `ui/text_block_presenter.py`, `ui/flow_presenter.py` | не стрипают `U+00AD` при записи в модель, но в проде не инстанцируются (только тесты) — латентно. |

Маппинг clean↔doc **уже есть**, но используется только для `outline_ranges`
(в `_effective_selection`), никогда — в пути propagate:

- `ui/textitem.py:1826-1836` `_panel_pos_to_clean(panel_text, pos)`
- `ui/textitem.py:1837-1854` `_panel_pos_to_doc_start(item_text, pos, panel_text=None)`
- `ui/textitem.py:1855-1868` `_panel_pos_to_doc_end(...)` (exclusive, «не перескакивает» хвостовые hyphens)

Ограничения: одиночная позиция (не диапазон), O(n)-обход, нужен свежий снимок текста,
обратного направления (doc→clean) нет.

---

### 2.1 Что такое S1 (search/replace) подробно

Тот же index-space баг, но в путях «Найти и заменить». Матчи считаются по **панели**
(`page_search_widget.py:457-475` ищет по `text_edit.toPlainText()`), а применяются к
**документу item** вербатим:

- `PageReplaceAllCommand.__init__` (`textedit_commands.py:457-483`): `doc_replace(edit.document(), span_list, replace)` (`ui/misc.py:125-141`) возвращает spans, сдвинутые длиной замены, **в координатах панели**, затем `doc_replace_no_shift(blkitem.document(), sel_list, replace)` (`ui/misc.py:143-151`) вставляет по этим же числам в hyphenated-документ;
- `GlobalRepalceAllCommand` (`:495-520`) — ровно та же пара вызовов;
- `PageReplaceOneCommand` (`:386-419`) — берёт `self.sel_start = current_cursor.selectionStart()` (панель) и `self.ori_len = len(selectedText())` (clean-длина) и применяет их к `blkitem.textCursor()`.

Пример на том же тексте: панель `…С ЭТИМ КАКИЕ-ТО…` (clean), документ `…С ЭТИМ КА\xadКИЕ-ТО…`.
Замена `ЭТИМ` → `ЗАЧЕМ`: в панели match `[17,21]`, в документе `ЭТИМ` сидит в `[19,23]` →
`doc_replace_no_shift` вырежет doc[17:21] = «С ЭТ» и вставит «ЗАЧЕМ» туда, т.е. в баллоне
получится «…У НЕГО ЗАЧЕМИМ КАКИЕ-ТО…». Плюс `insertText` не перегифенизирует, поэтому после
замены hyphen-расстановка внутри заменённого слова остаётся старой (это же I5).

### 2.2 Что значит «undo-семантику (Вариант B) не трогаем»

Отмена в этой системе — **не командный undo поверх модели**, а replay двух независимых
Qt-стеков синхронно:

```
Ctrl+Z → edit.undo_signal → on_textedit_undo
       → TextEditCommand.undo()          textedit_commands.py:364-385
       → edit.undo()  → document().undo()        textedit_area.py:288-299
         blkitem.undo() → document().undo()      textitem.py:939-950
         (число шагов = num_steps, посчитанное по availableUndoSteps())
```

Нужный инвариант: после одинакового числа шагов оба документа дают одинаковый **clean**-текст.
`U+00AD` его ломает: любая массовая перезапись (`setPlainText`/`setHtml` из auto-layout,
undo/redo форматирования, paste, загрузка) — это **один шаг** стека item, вставляющий или
удаляющий сразу несколько hyphens, а стек item не чистится никогда (панельный чистится:
`textedit_commands.py:109,126`).

Вариант B (перезапись текста item целиком на каждый keystroke) порождает такой шаг на каждую
букву — т.е. Ctrl+Z начинает отменять гифенизацию/relayout вместо символов. Мы меняем один
заметный баг на второй, незаметный. Поэтому в этом PR undo не трогаем: сначала тесты на сам
replay (T8, T14), потом отдельный разговор. Текущий дрейф undo частично прикрывают I5
(детерминированная гифенизация) и I7 (проверка перед save).

## 3. Варианты решения

### Вариант A — точечный фикс propagate (hotfix, 0.5–1 день)

Файлы: `ui/textedit_area.py`, `ui/textitem.py`, `ui/textedit_commands.py`, `ui/scenetext_manager.py`.

1. **Перестать выводить `removed` из арифметики счётчиков.** `QTextDocument::contentsChange`
   уже даёт точное число удалённых символов: `ui/textedit_area.py:154-159`
   `on_content_changing(from_, removed, added)` — `removed` сейчас **выбрасывается**.
   Сохранить `self.change_removed = removed` и передавать его в сигнале
   `propagate_user_edited` (добавить 4-й параметр; обе точки эмита —
   `textedit_area.py:208`, `textitem.py:184`; оба обработчика —
   `scenetext_manager.py:1299-1312`; у сигналов в `textedit_area.py:63`, `textitem.py:68`).
2. **Маппить позицию в пространство целевого документа** внутри
   `propagate_user_edit(src_edit, target_edit, pos, removed, added_text, joint_previous)`:
   - панель→item: `start = _panel_pos_to_doc_start(doc_text, pos, panel_text)`,
     `end = _panel_pos_to_doc_end(doc_text, pos + removed, panel_text)`;
   - item→панель: обратное преобразование = `_panel_pos_to_clean(item_doc_text, pos)`
     (добавить как хелпер,方向 doc→clean);
   - `added_text` предварительно очищать от `U+00AD` и нормализовать `U+2028` → `\n`.
3. **Страж инварианта (страховка от неизвестных источников дрейфа):** после применения
   операции сравнить `item.document().toPlainText().replace('\u00ad','')` с
   `edit.toPlainText()`; при расхождении — не «чинить» позиционно, а сделать полный
   re-sync `item.set_plain_text_clean(panel_text)` (гифенизует сама). O(n) на keystroke —
   приемлемо. Это же даёт наблюдаемый лог `[sync] invariant mismatch` вместо тихой порчи.
4. Тесты: `tests/ui/test_panel_edit_propagation.py` (см. §4).

Плюсы: минимальная площадь, устраняет и typing-порчу, и обратное направление; ничего не
меняет в undo/авторазмере.
Минусы: не закрывает S1/S2 (search-replace, charfmts) и L1/L2 (H меняется посреди сессии);
в модели по-прежнему живут два координатных пространства.

### Вариант B — единый источник правды: никаких позиционных зеркалок (1–2 дня, риск средний)

При любом изменении панели текст item перезаписывается целиком
(`setPlainTextAndKeepUndoStack`-путь, `flow_textitem.py:399` уже гифенизует), курсор item
восстанавливается через clean→doc маппинг; все точки L1/L2/L3 стрипают `U+00AD`.

Плюсы: O(1) в рассуждении, исчезает весь класс позиционных багов для typing, H детерминирован.
Минусы: именно от этого уходил апстрим в `b77c884` («fix sync issues … #742 #76 #313 #647 #654») —
undo в этой системе строится на `document().undo()/redo()` по `num_steps`
(`TextEditCommand` `:364-385`, `TextItemEditCommand` `:309-363`, replay в `textitem.py:939-950`
/ `textedit_area.py:288-299`); wholesale-перезаписи добавляют undo-шаги, вставляющие/удаляющие
`U+00AD`, иundo начинает «дёргать» гифенизацию. Плюс пер-keystroke re-hyphenate + re-layout
(и риск повторно дёргать `FontAutoAdjuster`). Нужен аккуратный перенос semantics undo.

### Вариант C — убрать `U+00AD` из текстовой модели (неделя+, риск высокий) — **ПРОВЕРЕН ВРУЧНУЮ, НЕ РАБОТАЕТ**

> Подтверждено автором правки: попытка реализовать собственный механизм разбиения строк
> в `ui/scene_textlayout.py` уже делалась и не удалась. Причина видна в коде: обе раскладки
> используют штатный разрыватель Qt — `QTextLine.setLineWidth` (`scene_textlayout.py:735`,
> `:1073`). Отказ от `setLineWidth` в пользу ручного разбиения требует, чтобы с собственным
> списком строк согласовались `hitTest` (`:640`, `:981`), `blockBoundingRect` (`:259`),
> `documentSize` (`:275`), `documentChanged` (`:278`), курсор/выделение, `_line_left_offsets`
> flow-машины, рендер обводки (`textitem.py:193-210`) и `punc_actual_rect` (индексы символов).
> При этом Qt не даёт break opportunity без символа в тексте. **Вывод: C снимаем с рассмотрения.**

Модель/панель/документ item = только clean текст; перенос по слогам реализуется в
`HorizontalTextDocumentLayout` (`ui/scene_textlayout.py`) либо рендером **копии** документа
с hyphens (прецедент уже есть: `_make_stroke_doc`, `ui/textitem.py:193-210`).
Это же закрывает «Вариант 2» из `PLAN_flow_outline_whole_text.md:109-120` (хранить офсеты
в clean-координатах) — тогда `outline_ranges`, propagate, search-replace, charfmts живут
в **одном** пространстве, и половина стражей становится не нужна.

Плюсы: коренное решение, одним махом снимает L1–L3, S1, S2, C2.
Минусы: Qt не делает break opportunity без символа в тексте — нужен свой механизм разбиения
строк; миграция проект-файлов, где `rich_text` уже содержит `U+00AD`; падает часть текущих
тестов, которые утверждают `'\u00ad' in item.document().toPlainText()`
(`tests/ui/test_flow_textitem.py::TestHyphenation*`, `test_flow_panel_outline.py:133`).

### Вариант D — рекомендуемый маршрут: A сейчас, D-каркас сразу после (2.5–4 дня суммарно)

1. **A** как хотфикс + тесты-регрессии (снимает потеря данных у пользователя).
2. Централизация: новый модуль `ui/text_sync.py` (или `TextSync`), владеющий
   * единственной парой мапперов clean↔doc (перенос `_panel_pos_to_*` из `textitem.py`,
     плюс обратный doc→clean и *range*-версии);
   * `apply_edit(src, dst, pos, removed, added, joint)` — единственный способ переносить
     редактирование между документами (панель↔item, оба направления);
   * `write_clean_text(target, text)` — единственный способ массовой перезаписи текста
     (undo-команды `:247/256`, `:585`, search/replace S1, `layout_textblk`, pipeline),
     который гарантирует: в панель и в `blk.translation` `U+00AD` не попадает.
3. Закрыть L1/L2/L3 и S1 (spans → через маппер).
4. Инвариант-тесты (§4) + обновить `.agents/skills/debug-text-ui/SKILL.md`
   (там нет ни слова про index-space регрессию propagate — документационный пробел;
   там же неверные даты «2026-07-09» для work, приехавшего в `283c0ec` 2026-10-21).

---

## 4. Тесты (добавляются при любом варианте; без них фикс не принимаем)

**BASE зафиксирован прогоном до правок:** `600 passed, 6 skipped, 20 subtests passed`
(`_base_pytest.log`; `QT_QPA_PLATFORM=offscreen myenv\Scripts\python.exe -m pytest tests/ -q`).
Гейт: каждый коммит — полный прогон **≥ BASE + число новых тестов**, ранее зелёные тесты
не краснеют.

### 4.1 Новый файл `tests/ui/test_panel_edit_propagation.py` — харнесс

Wiring **1:1** как в бою (методология `debug-text-ui/SKILL.md` п. 4: тест обязан инициализировать
view тем же вызовом, что реальная wiring — иначе баг переживает в зелёной базе):

- фикстуры `qapp`, `scene` — из `tests/ui/conftest.py:27, :36` (уже есть);
- `_make_blk` / `_make_item` — как в `tests/ui/test_flow_textitem.py:35, :49`;
- `_mk_pair(cls, text)`: создаёт item, затем `TransTextEdit(0, None)` и строку
  `e.setPlainText(item.toPlainText().replace('\u00ad',''))` — **дословно** `transpair_wiring.py:48`,
  и коннект `propagate_user_edited` — дословно `transpair_wiring.py:62` → обработчик,
  повторяющий `on_propagate_transwidget_edit` (`scenetext_manager.py:1305-1312`);
- `_RunningCanvas` — выполняет `cmd.redo()` внутри `push_undo_command` (иначе ленивые
  команды не применяются; см. `debug-text-ui/SKILL.md`, раздел «Offscreen-пробники»);
- `_edit(e, item, start, end, text)` — одна правка через `QTextCursor` **на панели**,
  параметры берутся из `contentsChange(from, removed, added)`;
- `_assert_invariant(e, item)` — `item.document().toPlainText().replace('\u00ad','') == e.toPlainText()`,
  вызывается после каждого шага во всех тестах.

### 4.2 Матрица новых тестов

| # | тест | что ловит | коммит |
|---|---|---|---|
| T1 | `test_flow_panel_typing_keeps_item_in_sync` — сценарий `_probe_bug1.py` (рус., H=3): `ИТЕ`→`ЕШЬ`, затем удаление хвоста | сам баг; **красен до фикса** (`ВИЕШЬ У НЕГО ...`) | 1 |
| T2 | `test_normal_item_typing_control` — то же на `TextBlkItem` | контроль: зелёный и до фикса (иначе харнесс врёт) | 1 |
| T3 | `test_item_to_panel_typing_sync` — правка на canvas (src = item) | обратное направление: `removed<0`, сдвиг/дубли в панели | 1 |
| T4 | `test_replace_across_soft_hyphen` — диапазон внутри `КА\xadКИЕ` | длина диапазона в doc-координатах ≠ clean-длине | 1 |
| T5 | `test_backspace_chain_flow_block` — N одиночных backspace | `removed_computed = реальный + H` | 1 |
| T6 | `test_insert_newline_flow_block` — Return в панели при H>0 (`textedit_area.py:280-283`) | C2: блочные терминаторы, `U+2028` из `selectedText()` | 1 |
| T7 | `test_paste_sync` (путь `paste_flag`), `test_ime_commit_sync` (`input_method_from`) | альтернативные источники `added_text` | 1 |
| T8 | `test_undo_redo_keeps_both_in_sync` — undo/redo N шагов панели | replay двух document-стеков (`TextEditCommand:364-385`) | 2 |
| T9 | `test_panel_clean_after_autolayout_undo_redo` | L1: `textedit_commands.py:247/256` льёт hyphens в панель | 3 |
| T10 | `test_layout_textblk_panel_clean` (`layout_textblk` c `text=None`) | L2: `scenetext_manager.py:1201` | 3 |
| T11 | `test_translation_has_no_soft_hyphens_after_typing` — расширить `test_flow_panel_outline.py:275` (было: только save) | порча уходит в `blk.translation` → в проект-файл | 1 |
| T12 | `test_search_replace_spans_land_correctly` (flow, H>0) | S1: `PageReplaceAllCommand:475-478`, `PageReplaceOneCommand:411-413` | 3 |
| T13 | `test_random_edit_sequences_invariant` — `random.Random(seed)`, 200 случайных вставок/удалений/замен на flow-блоке, инвариант после каждого шага | неперечисленные источники дрейфа; проверяет страж + re-sync | 2 |
| T14 | `tests/test_text_coords.py` — юниты чистых мапперов без `QApplication` | регрессии маппинга дёшево; обратный маппинг doc→clean (в коде его сейчас нет) | 2 |

`hypothesis` в venv **нет** (`ModuleNotFoundError`) → T13 на `random.Random(seed)`, новой
зависимости не добавляем.

### 4.3 Правки в существующих тестах

- `tests/ui/test_flow_panel_outline.py`: фейки `_FakeTransEdit` (`:173`, `:193`) уже ставят чистую
  панель — сверить с боевым wiring после T1–T7 (прецедент расхождения: `test_panel_stroke_display.py`).
- `tests/ui/test_flow_textitem.py::TestHyphenation*` не трогаем (D гифенизацию не меняет).
  При варианте C они бы падали (`test_hyphenate_integration_with_setplaintext:348`,
  `test_flow_panel_outline.py:133`) — дополнительный аргумент против C.
- Если в репо есть `tests/test_architecture_boundaries.py` — добавить правило
  «`ui/text_coords.py` не импортирует `qtpy`» (иначе маппинг снова осядет на Qt-классе).

---

## 5. Ассерт-инварианты в проде (чтобы рассогласование падало понятно, а не портило текст)

Принцип: **тихое расхождение запрещено**. Каждый инвариант — маленькая проверка в точке,
где расхождение может возникнуть, с **одним общим форматом сообщения** (грепается по
`[SYNC] I<n>`) и с готовой диагностикой: первый расходящийся символ, контекст, число
soft hyphens, число блоков. Один и тот же хелпер используют прод и тесты — чтобы провал
теста выглядел ровно так же, как падение в GUI.

### 5.1 Единая ошибка и генератор диагностики — `ui/text_coords.py`

```python
class TextSyncError(RuntimeError):
    """Рассогласование текстовых проекций (панель / документ item / blk.translation)."""

STRICT = lambda: bool(os.environ.get("BTRANS_STRICT_TEXT_SYNC")) or C.strict_text_sync

def first_diff(a: str, b: str) -> tuple[int, str, str]:
    """(индекс первого расхождения, окно из a, окно из b) — окна по 12 символов,
    U+00AD показываются как \xad, переводы строк как \u2407."""

def describe_desync(label: str, where: str, **sides: str) -> str:
    """Собирает сообщение вида (см. пример ниже) для ЛЮБОГО числа сторон."""

def check(label: str, where: str, **sides: str) -> bool:
    """True, если все переданные строки равны. Иначе — TextSyncError (STRICT)
    или LOGGER.error(...) один раз на (label, idx) за сессию. Возвращает False."""
```

Пример сообщения (то, что увидит и пользователь в логе, и pytest):

```
[SYNC] I1 panel↔item RAISED after apply_edit (blk idx=5, page 2)
  panel      len=17 : 'ВИДЕШЬ? У НЕГО...'
  item→clean len=15 : 'ВИЕШЬ У НЕГО ...'
  first diff @2: panel='Д' item='Е' | ctx panel='ВИ[Д]ЕШЬ? У НЕ' item='ВИ[Е]ШЬ У НЕГО'
  doc len=18  soft_hyphens(H)=3  blocks: panel=1 item=1
  hint: pos/removed применены в разных координатных пространствах
        (clean vs doc) — см. PLAN_panel_edit_propagation.md §1
```

### 5.2 Инварианты, точки вставки, поведение при нарушении

| # | инвариант | где проверяется (вставить) | при нарушении |
|---|---|---|---|
| **I1** | `doc.replace('\u00ad','') == e_trans.toPlainText()` | конец `apply_edit` (`textedit_commands.py:25-40` → новый `text_sync.apply_edit`); `on_propagate_textitem_edit` (`scenetext_manager.py:1299-1304`); `on_pairw_focusout` (`:1283-1289`); перед `update_textblk_list` (`block_manager.py:122`) | **re-sync по панели** (`write_clean_text`) + `[SYNC] I1`; в STRICT — `TextSyncError` |
| **I2** | `'\u00ad' not in blk.translation` | все записи модели: `block_manager.py:136,139`, `scenetext_manager.py:647,654`, `textedit_commands.py:544,564`, `global_search_widget.py:260`, `translation_pipeline.py:140` (одной функцией `write_model_text`) | strip + `[SYNC] I2`; в STRICT — raise |
| **I3** | `'\u00ad' not in e_trans.toPlainText()` | все записи в панель: `transpair_wiring.py:48`, `scenetext_manager.py:1201,1356`, `textedit_commands.py:247,256`, `drawing_commands.py:187,204,210` (одной функцией `write_clean_text`) | strip + `[SYNC] I3`; в STRICT — raise |
| **I4** | `panel.document().blockCount() == item.document().blockCount()` | в начале и в конце `apply_edit` (ловит LF-дрейф, §2 C2) | raise в STRICT; иначе re-sync |
| **I5** | `doc == _hyphenate_text(clean)` при flow-режиме (детерминированность гифенизации, «H не поехал») | после `apply_edit`/`write_clean_text` и после `AutoLayoutCommand.redo/undo` | перезагифенизировать + `[SYNC] I5` (ловит L1/L2) |
| **I6** | маппер корректен: `0 ≤ map(p) ≤ doc.characterCount()` и монотонность `p ≤ q ⇒ map(p) ≤ map(q)` | внутри `_panel_pos_to_doc_start/_end` (debug-only) + юниты T14 | raise (это баг маппера, не данных) |
| **I7** | перед save: `I1 ∧ I2` | `main_presenter.manual_save` / `update_textblk_list` | **источником правды объявляется панель** (она — канал ввода), предупреждение в лог/статус-бар |
| **I8** | страж совпадения один, не два | `textitem.py:1132` (clean vs raw) и `:1800` (clean vs clean) свести к `texts_match(item, panel) -> (bool, reason)` c логом причины | не ассерт, а устранение расхождения двух копий одного правила |

### 5.3 Режимы

**Сама проверка выполняется ВСЕГДА, в обычном запуске программы** — в каждой точке из §5.2,
на каждом keystroke, при каждом save, при каждом undo/redo и при каждом auto-layout.
Никакого «только для dev», никакого «включить перед отладкой»: проверка не должна иметь
способа выключиться, иначе ровно так и живут тихие баги. Флаг меняет **только реакцию**:

- **STRICT** (`BTRANS_STRICT_TEXT_SYNC=1` или `C.strict_text_sync`) — бросаем `TextSyncError`.
  Включено в тестах (autouse-фикстура в `tests/ui/conftest.py`) и рекомендуется в dev-сборке:
  иначе тест «починил» текст молча и стал зелёным.
- **не-STRICT** (сборка пользователя, дефолт): GUI не роняем, но делаем ровно три вещи —
  1) безопасный re-sync (панель как источник ввода), 2) `[SYNC] I<n> …` в лог (сообщение
  с first-diff, §5.1), 3) **видно пользователю**: строка в статус-баре «текст блока N
  рассогласован — восстановлен из поля перевода» + счётчик за сессию; при I7 (расхождение
  прямо перед save) — additionally non-modal warning, потому что иначе рассогласование
  уйдёт в проект-файл как обычный «не вижу проблем» save.
- Бюджет: сравнение строк O(n), n ≤ ~10⁴ символов на блок → на keystroke незаметно;
  `describe_desync` вызывается только при расхождении.
- `assert` **не используем** (вырезается `python -O`) — только явный `if … : raise/log`.

### 5.4 Ассерты в тестах

- `_assert_invariant(e, item)` (см. §4.1) внутри = тот же `check('I1 panel↔item', where='test …')`,
  поэтому в прогоне виден ровно тот же формат с first-diff, что и у пользователя;
- T13 (200 случайных правок) в STRICT даёт падение на **том самом шаге**, где проекции
  разъехались, с полным сообщением — вместо «в конце строки не совпали»;
- отдельные тесты на саму диагностику: `test_describe_desync_reports_first_diff`,
  `test_invariant_violation_raises_in_strict_mode` (проверяет, что ассерты не протухли).

## 6. Что делать с уже испорченными проектами

Порча не ограничивается экраном: при сохранении кривой текст осел в `blk.translation`
и `blk.rich_text` (`ui/block_manager.py:132-136`). Для проекта, на котором воспроизводили:
`text` в панели верен до focus-out — после фикса достаточно переоткрыть проект и, при
необходимости, перезаписать текст из панели (время от времени focus-out сам этого не делает:
источником правды стал item).

## 7. Архитектурная оценка вариантов (только по текущему коду)

Вердикт: **D (A как первый коммит внутри D)**. C — только если готовы платить неделю
за миграцию сохранённых проектов. B — не делать.

1. **Причина бага — отсутствие границы, а не «не туда вставили».** Через границу
   панель↔item передаются сырые `int` (позиция + «removed», выведенный арифметикой)
   без типа и без маппинга. Нет ни одного места, владеющего переводом между двумя
   координатными пространствами.
2. **Инвариант «панель/модель = чистый текст» никем не владеется.** Записей в
   `e_trans.setPlainText*` — 6 (`transpair_wiring.py:48` и `scenetext_manager.py:1356`
   стрипают; `textedit_commands.py:247/256`, `scenetext_manager.py:1201` — нет),
   записей в `blk.translation` — ~23, из них со стрипом **3** (`block_manager.py:136`,
   `text_block_presenter.py:75,111` — причём presenter'ы в проде не инстанцируются).
   Правило живёт как соглашение, подкреплённое grep'ом → A лечит один из ~8 потребителей
   сломанного предположения, и следующий коммититщий добавит 9-й inline-стрип.
3. **LSP-нарушение в `FlowTextBlkItem`:** переопределения `setPlainText/setHtml/
   setPlainTextAndKeepUndoStack` (`flow_textitem.py:382-403`) меняют смысл **всех**
   offset-API базового класса (`toPlainText()`, `characterCount()`, позиции курсора).
   позиционные потребители: propagate (2 направления), `PageReplaceAllCommand:475-478`,
   `GlobalRepalceAllCommand:513-515`, `PageReplaceOneCommand:395,411-418`,
   `_restore_charfmts`, `get_char_fmts` — все молча наследуют баг. Это аргумент против
   того, чтобы зашивать маппинг внутрь `propagate_user_edit` (= чистый A).
4. **Маппинг лежит не там:** `_panel_pos_to_*` — `@staticmethod` на Qt-View-классе
   (`textitem.py:1826-1868`), хотя это чистые строковые функции. Из-за этого они
   недоступны из `textedit_commands.py` / search-replace / юнит-тестов без QApplication,
   и в одном классе живут **два несовместных стража одного правила**: `textitem.py:1132`
   (`clean vs raw` — для clean-панели промахивается, отвал в fallback молча) и `:1800`
   (`clean vs clean`).
5. **Обратного маппинга (doc→clean) в коде нет вообще** → направление «правка на canvas →
   панель» починить нечем, кроме как написать новый модуль. Это и есть D.

### Состав D без over-engineering

- `ui/text_coords.py` — чистые функции (`clean→doc`, `doc→clean`, range-версии), без `qtpy`
  → юнит-тесты без `QApplication`;
- `ui/text_sync.py` — `apply_edit(src, dst, pos, removed, added, joint)` как единственный
  перенос правки (оба направления) и `write_clean_text(view, text)` как единственная
  массовая запись текста (в неё заводим L1/L2/L3 и S1); стрип `U+00AD` в модель — одна
  функция вместо трёх inline-строк;
- сигнал `propagate_user_edited` получает настоящий `removed` из `contentsChange`
  (`textedit_area.py:154-159`), арифметика счётчиков уходит;
- инвариант-страж после каждой операции + полный re-sync при расхождении;
- тесты: §4 + property-тест со случайными последовательностями правок.

Чего **не** делать: ABC/`ITextSync` с единственной реализацией; переносить живую логику в
`text_block_presenter.py` / `flow_presenter.py` / `scene_presenter.py` (в проде не
инстанцируются — только тесты).

Почему не B: undo сейчас = replay двух document-стеков по `num_steps`
(`TextEditCommand:364-385`, `TextItemEditCommand:309-363`, replay `textitem.py:939-950` /
`textedit_area.py:288-299`); стек item не чистится никогда и уже содержит шаги,
вставляющие/удаляющие `U+00AD` (любой `setPlainText/setHtml`). Wholesale-перезапись на
каждый keystroke умножает эти шаги и перезапускает relayout/autofit.

Почему C снят: одно координатное пространство убило бы класс и восстановило LSP, но
(а) собственный механизм разбиения строк в `scene_textlayout.py` **уже пробовался вручную и
не получился** (см. врезку в §3 «Вариант C»): обе раскладки сидят на `QTextLine.setLineWidth`
(`:735`, `:1073`), а ручной список строк приходится согласовывать с `hitTest` (`:640`, `:981`),
`blockBoundingRect` (`:259`), `documentSize` (`:275`), `documentChanged` (`:278`),
курсором/выделением, `_line_left_offsets`, рендером обводки и `punc_actual_rect`;
(б) `U+00AD` уже персистится в проект-файлы (`block_manager.py:132-133` сохраняет `rich_text`
с hyphens) → нужна миграция;
(в) на нём стоят текущие тесты (`test_flow_textitem.py::TestHyphenation*`,
`test_flow_panel_outline.py:133`).

Итог: два координатных пространства остаются реальностью; поддерживаемость покупаем
не «одним пространством», а (1) единственным владельцем перевода координат, (2) инвариантом
как кодом (`write_clean_text` + страж с re-sync), (3) механической проверкой инварианта (§4).

## 8. Порядок коммитов и гейты (вариант D)

| коммит | содержимое | тесты | гейт |
|---|---|---|---|
| 1 | `ui/text_coords.py` (чистые мапперы + `TextSyncError`/`check`/`describe_desync`) + настоящий `removed` из `contentsChange` (`textedit_area.py:154-159`) + `apply_edit` в `textedit_commands.py:25-40` с маппингом в обе стороны + **I1/I4** в `apply_edit`, **I2/I3** в точках записи | T1–T7, T11 | ≥ BASE+8, T1 красен до коммита, после — зелёный |
| 2 | детерминированная перегифенизация (D+): правка применяется, затем перегифенизация затронутого слова в том же edit-block'е; **I5** + лог `[SYNC]` | T8, T13, T14 | ≥ BASE+11 |
| 3 | точки утечки и search/replace: `write_clean_text` для `textedit_commands.py:247/256`, `scenetext_manager.py:1201`, `global_search_widget.py:260`; спаны S1 через маппер; **I7** перед save, **I8** — свести стражи `textitem.py:1132`/`:1800` к одной функции | T9, T10, T12 | ≥ BASE+14 |
| 4 | гигиена: обновление `.agents/skills/debug-text-ui/SKILL.md` (класс бага «index-space propagate», исправление дат: clean-panel work приехал в `283c0ec` 2026-10-21, а не 2026-07-09) | — | ≥ прежнему |

Прогон на каждом коммите: `myenv\Scripts\python.exe -m pytest tests/ -q` (AGENTS.md);
BASE = `600 passed, 6 skipped, 20 subtests`.

## 9. Открытые вопросы

1. ~~A или D?~~ → принято **D** (C снят: не работает; B не делаем).
2. S1 (search/replace в flow-блоках) — в коммите 3 того же PR. Подтвердить, что это нужно
   сейчас, иначе коммит 3 откладывается (баг там того же класса, но путь реже используемый).
3. Undo-семантику (Вариант B) не трогаем: тестов на replay `TextEditCommand`/
   `TextItemEditCommand` в базе нет; сначала T8/T14, потом разговор.
4. ~~Нужен ли видимый сигнал при срабатывании стража?~~ → принято: да, не-STRICT режим пишет
   `[SYNC] I<n> …` в лог + счётчик в статус-баре; STRICT (dev/тесты) бросает `TextSyncError` (§5.3).
5. Дефолт `C.strict_text_sync` для пользовательской сборки: `False` (не ронять GUI) — подтвердить.
