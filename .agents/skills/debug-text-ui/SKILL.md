---
name: debug-text-ui
description: >
  Справочник и методология отладки selection-зависимых операций над текстовыми
  блоками BallonsTranslator (обводка stroke/SRGB для части текста, форматирование
  по выделению панели e_trans): кто пишет текст в панель, точки решений
  (_effective_selection, whole-block fallback в fontformat_commands), soft hyphens
  U+00AD в flow mode, координатные пространства outline_ranges, загрязнение
  blk.translation.
  TRIGGER WHEN: «весь текст показывается с обводкой» / обводка или формат не
  применился к части текста, панельное выделение не учитывается, лог
  «panel selection REJECTED (text mismatch)», обводка «уплыла»/сместилась после
  смены flow-режима или перезагрузки, zero-width символы (U+00AD) в переводе/панели,
  отладка _effective_selection / set_selection_outline / _stroke_groups /
  paint_stroke / sync e_trans ↔ blk_item, написание тестов для панельных
  formatting-операций.
  DO NOT TRIGGER WHEN: авторазмер шрифта (skill font-auto-size), flow-boundary
  control points (skill flow-blocks в .claude/skills/), layout/лейаут без
  выделений, чистая отрисовка stroke без selection-аспекта.
---

# Отладка selection-зависимых операций (stroke/SRGB/формат по выделению)

Методология поиска стейт-багов + карта подсистемы + известные классы багов.
Написано по итогам бага «при переключении в Flow mode установка обводки для
части текста показывала обводку на ВСЁМ тексте» (исследовано и исправлено
2026-07-09, см. `PLAN_flow_outline_whole_text.md`).

## Методология: как быстро искать стейт-баг в текстовом UI

Порядок действий, сокращающий поиск с дней до часов (урок бага 2026-07-09):

1. **Сначала включи Готовые логи, затем живой репро.** В модулях UI есть
   отключаемые debug-логи: `QUIET_UI = True` в `ui/textitem.py:27`,
   `ui/fontformat_commands.py:19`, `ui/scenetext_manager.py:31`,
   `ui/block_manager.py:18`. Ставишь `QUIET_UI = False`, воспроизводишь в
   реальном GUI — логи `[stroke]` (ниже, «Ключевые точки решений») показывают
   точное место отклонения. Не симулируй offscreen-пробником то, что живое
   приложение за секунды покажет в логах (пробник — когда репро невозможен).
2. **Карта потока данных ДО чтения логики.** Один grep на «кто пишет
   проблемное состояние» часто даёт root cause сразу:
   `rg "e_trans.setPlainText" ui/` → `ui/transpair_wiring.py:48` (текст
   панели) — именно здесь было расхождение. Аналогично:
   `rg "blk.translation\s*="` (кто пишет модель), `rg "outline_ranges\s*="`
   (кто пишет диапазоны обводки).
3. **Отбой от точки решения, а не от рендера.** Симптом «весь текст с
   обводкой» = сработал whole-block path = `_has_effective_selection() ==
   False` в обёртке `fontformat_commands` (см. ниже). Бинарный поиск по
   цепочке «почему выделение отклонено?» (2–3 функции) вместо исследования
   `paint_stroke`/`_stroke_groups` — рендер в баге 2026-07-09 был корректен.
4. **Смотря на тест: как инициализируется view в ТЕСТЕ vs в РЕАЛЬНОМ wiring.**
   Расхождение «тест льёт в панель чистый текст, а `transpair_wiring.py`
   льёт `blk_item.toPlainText()`» — типичный способ, как баг проживает среди
   зелёных тестов. Интеграционные тесты должны инициализировать view тем же
   точным вызовом, что и реальная wiring (копируй вызов, не выдумывай stub-текст).
5. **Знай дефолты формата проекта.** `is_flow_mode: bool = True`
   (`utils/textblock.py:55`) — ВСЕ блоки загруженного проекта создаются как
   `FlowTextBlkItem` (`SceneTextManager.addTextBlock`,
   `ui/scenetext_manager.py:622`). Баг, «появляющийся в flow mode», обычно
   живёт на всех блоках пользователя, а не только на переключённых.

## Карта подсистемы: кто что делает (stroke/SRGB по выделению)

| Место | Роль |
|-------|------|
| `ui/transpair_wiring.py:48` | **кто пишет текст в панель** при создании/загрузке: `e_trans.setPlainText(blk_item.toPlainText().replace('\u00ad', ''))` — панель держит ЧИСТЫЙ текст (приехало в `283c0ec`, 2026-10-21; исследование 2026-07-09) |
| `ui/text_coords.py` | **единственный владелец двух координатных пространств**: `clean_offset` (позиция → число видимых символов), `doc_start_for_clean` / `doc_end_for_clean` (clean → документ), `map_pos`/`map_range`, плюс диагностика `TextSyncError` / `check` / `describe_desync`. Без `qtpy` — юниты без QApplication (`tests/test_text_coords.py`) |
| `ui/text_sync.py` | `apply_edit` — единственный перенос правки панель↔item (оба направления); `write_clean_text` / `write_model_text` — единственная массовая запись текста (панель/модель); `replace_spans_in_doc` — search/replace-спаны из панели в документ item; `verify_sync` — страж I1 (+re-sync) |
| `ui/textedit_area.py:154-159`, `TextBlkItem.on_content_changing` | держат `change_removed` из `QTextDocument::contentsChange` — 4-й аргумент сигнала `propagate_user_edited(pos, added_text, joint_previous, removed)`; «removed» больше НЕ выводится из арифметики двух `characterCount()` |
| `ui/textedit_commands.py:propagate_user_edit` | тонкий делегат в `text_sync.apply_edit` (было: позиционный перенос + `removed = ori_count + len(added) - new_count`) |
| `ui/scenetext_manager.py:1350` | `updateTranslation()` — ресинк панели и item из `blk.translation` (защитный стрип U+00AD); вызывается при focus-out панели |
| `ui/textitem.py:1766` | `_effective_selection()` — **главная точка решения**: (1) выделение курсора item → (2) панель `e_trans` через `SW.st_manager.pairwidget_list[idx]` со стражем mismatch (обе стороны в clean-виде) → (3) снапшот `_last_selection` из `endEdit`; иначе `None` |
| `ui/textitem.py:1827–1868` | `_panel_pos_to_clean` / `_panel_pos_to_doc_start` / `_panel_pos_to_doc_end` — делегаты в `ui/text_coords` (сохранены для существующих вызовов/тестов) |
| `ui/fontformat_commands.py` | обёртка `font_formating.wrapper`: `stroke_sel = param in ('stroke_width','srgb') and not is_global and blkitems[0]._has_effective_selection()` → True: **немедленное** применение + снапшот-команда `SelectionOutlineUndoCommand`; False: `act_ffmt[param]=value`, закреплённый `set_selected=False`, **ленивая** `TextStyleUndoCommand` (whole-block) |
| `ui/textitem.py:2012` / `:1986` | `setStrokeWidth` / `setStrokeColor`: selection path → `set_selection_outline(...)` (диапазоны в `blk.outline_ranges`, блок-скаляр НЕ трогается); whole-block path → `fontformat.stroke_width` / `fontformat.srgb` на весь текст |
| `ui/textitem.py:1895` | `set_selection_outline(width=None, srgb=None)` — запись/удаление (width<0)/перекрас (width=None, srgb) диапазонов; снапшот `_outline_clean_text` |
| `ui/textitem.py:234` / `:328` | `_stroke_groups()` (группы по (ширина, цвет): ranges поверх блок-скаляра) и `paint_stroke()` (рендер через копию документа: весь текст прозрачный → opaque только спаны группы → dilate) — **рендер в баге 2026-07-09 был корректен** |
| `ui/flow_textitem.py:82` | `_hyphenate_text` — вставляет soft hyphens `U+00AD` (min_word_len=5; en_US/ru_RU через pyphen; idempotence-guard: текст с `U+00AD` не перегифенизируется) — источник смещения координат в flow-документах |
| `ui/block_manager.py:122` | `update_textblk_list` — сохранение в модель через `text_sync.write_model_text` (strip U+00AD) + пред-save страж I7 (`[SYNC] I7 pre-save MISMATCH`) |
| `ui/text_block_presenter.py` | `_on_text_edited` / `sync_to_model` — та же запись `blk.translation` со стрипом U+00AD |
| `ui/scenetext_manager.py:700` | `toggle_block_flow_mode` — создаёт новый item того же `blk`, **очищает `blk.outline_ranges`** (координаты ranges относятся к документу старого item — с/без hyphens); блок-скаляр `fontformat.stroke_width` сохраняется |

### Ключевые логи (при `QUIET_UI = False`)

- `[stroke] panel selection REJECTED (text mismatch): item=... panel=...` — панельное выделение отклонено стражем mismatch (`_effective_selection`, textitem.py).
- `[stroke] setStrokeWidth(...) -> SELECTION path` / `-> WHOLE-BLOCK path` / `-> selection no-op` — какой путь сработал (`setStrokeWidth`, textitem.py:2012).
- `[stroke] panel op: param=... stroke_sel=...` — решение обёртки `fontformat_commands`.
- `[stroke] set_selection_outline ...` — результат записи диапазонов.
- `[TOGGLE] toggle_block_flow_mode ...` + `clearing outline_ranges=...` — смена режима (scenetext_manager.py:700).

## Известные классы багов (root causes)

### 1. clean-vs-raw mismatch в страже панели (2026-07-09, исправлен)

Симптом: «установил обводку для части текста в flow mode — весь текст с
обводкой». Цепочка: панель инициализировалась `blk_item.toPlainText()`
(у flow item — **с** soft hyphens), страж сравнивал
`item_text.replace('\u00ad','')` (clean) с `e_trans.toPlainText()` (raw) →
расхождение ВСЕГДА в flow mode → панельное выделение отклонялось →
`stroke_sel=False` → whole-block fallback → обводка всего текста. Тот же
отвал бьёт по всем панельным selection-операциям (шрифт, размер, srgb).
Фикс: чистый текст в `transpair_wiring.py:48` + страж clean-vs-clean +
маппинг с `panel_text` (терпит legacy-панель с hyphens до перезагрузки).
Сигнатура в логах: `panel selection REJECTED (text mismatch)` с
`item=... panel=...`, где различия — только `\xad`.

### 2. Координатные пространства `outline_ranges` (частично закрыт — вариант 3)

Ranges — в документных координатах ТЕКУЩЕГО item: flow-документ содержит
`U+00AD`, normal — нет. При смене режима item пересоздаётся, снапшот
`_outline_clean_text` сбрасывается (`initTextBlock`) → stale-check не
срабатывает → ranges «плывут» (normal→flow: смещение вправо на число
hyphens; flow→normal: «за хвост»). Защита (введено 2026-07-09):
`toggle_block_flow_mode` очищает `blk.outline_ranges`. Полное решение
(отложено, «вариант 2» в PLAN): хранить ranges в clean-координатах и
маппить на координаты текущего документа при использовании — тогда обводки
переживают смену режима и перезагрузку без потери.

### 3. Загрязнение `blk.translation` soft hyphens (2026-07-09, исправлен)

`toPlainText()` flow item (с `U+00AD`) писался в модель
(`update_textblk_list`, `text_block_presenter`) → zero-width символы в
проект-файлах, в панели, в OCR-сравнениях; через `updateTranslation`
загрязнение возвращалось в `e_trans`. Фикс: стрип `'\u00ad'` во всех
точках записи `blk.translation` + защитный стрип в `updateTranslation`.

### 4. index-space propagate: текст баллона «пережёвывается» при правке в панели (2026-11-05, исправлен)

Симптом (`bug1.txt`): в панели «ВИДЕШЬ? У НЕГО...», в баллоне «ВИДШЬЕГО С
ЭТИМ КАКИЕ-ТО...». `propagate_user_edit` переносил правку позиционно
(`pos` из панели) и считал `removed` как
`characterCount(item) + len(added) − characterCount(panel)`. Пока оба
dокумента были индекс-идентичны (до `283c0ec`) это работало; когда панель
стала CLEAN, а документ flow-item остался с `U+00AD`, остались два
разных координатных пространства:

- `pos` занижен на число hyphens левее → вставка уезжает;
- `removed` завышен ровно на `H` → чистая вставка выполняется как
  «удалить N+H и вставить» → реальные символы съедаются;
- после ПЕРВОЙ правки `len(doc) == len(panel)` навсегда (дефицит `H`
  съедается первым over-deletion'ом), дальше удаляется правильное число
  символов, но не там — отсюда «голова испорчена, хвост цел»;
- обратное направление (правка прямо на canvas) — тот же баг с другим
  знаком: `removed` уходил в минус, ветка удаления молча пропускалась;
- тот же класс в search/replace (`PageReplaceOneCommand`,
  `PageReplaceAllCommand`, `GlobalRepalceAllCommand`, фоновые страницы в
  `global_search_widget`): матчи считаются по панели/`blk.translation`
  (clean), а применялись к документу item / `rich_text` (hyphenated).

Фикс (2026-11-05): `ui/text_coords.py` + `ui/text_sync.apply_edit` —
позиция и длина удаления переводятся через CLEAN-пространство (диапазон
считается от текста ЦЕЛИ: к моменту эмитта `contentsChange` источник уже
«после» правки), настоящий `removed` из `contentsChange` — кросс-чек,
спаны search/replace маппятся через `replace_spans_in_doc`. Точка истины
при re-sync — панель (канал ввода).

Диагностика без репро: в логе появляется (подписи сторон — по ролям,
`panel_*` / `item_*`, а не src/dst):
```
[SYNC] I1 panel<->item MISMATCH after apply_edit (blk idx=…)
  panel_clean len=33   : 'ВИДЕШЬ? У НЕГО…'
  item_clean  len=31   : 'ВИЕШЬ У НЕГО …'
  first diff @2: panel_clean='ВИДЕШЬ? У НЕГО' item_clean='ВИЕШЬ У НЕГО С'
  panel_clean: len=33 H=0 blocks=1  item_clean: len=31 H=0 blocks=1
  hint: … item doc: len=33 H=2 blocks(item)=1 blocks(panel)=1
         (за сессию по этому инварианту: 1)
```
Флаг `BTRANS_STRICT_TEXT_SYNC=1` (в `tests/` включён через
`tests/conftest.py`) меняет только РЕАКЦИЮ: STRICT — `TextSyncError`,
обычный запуск — лог + re-sync по панели. Сама проверка выполняется
всегда, выключить её нельзя (§5.3 «тихого рассогласования не бывает»).

* `I1`/`I7` — `LOGGER.error` один раз на пару (label, индекс первого
  расхождения) за сессию, дальше только счётчик `TC.trip_counts()`;
* `I4` (blockCount разный при равных clean-текстах, `removed` из Qt не
  совпал с clean-removed) — `LOGGER.warning` с заголовком `NOTICE`,
  позиционно не чинится;
* `I7` пред-save (`update_textblk_list`) — панель (канал ввода) источник
  правды: item пере-синкается по панели, в проект-файл уходит текст панели,
  плюс `[SYNC] I7 pre-save MISMATCH` в лог (иначе порча ушла бы в проект
  как обычный save, §6).

Скрипт-проверка реакции обычной сборки: `_probe_bug1_guard.py` (штатная
правка → счётчик пуст; сломанный перенос → `[SYNC] I1` + re-sync; save при
рассогласовании → `[SYNC] I7 pre-save`).

Диагностический тест на реальном проекте: если после порчи
`len(item.document().toPlainText()) == len(e_trans.toPlainText())` —
виновата чисто позиционная прошивка; если длины РАЗНЫЕ — подключился
сторонний писатель (кандидаты: `AutoLayoutCommand.redo/undo`,
`ApplyFontformatCommand`, `drawing_commands`, `text_layout_manager`).

## Быстрый чеклист: «форматирование не применилось к части текста»

1. Включи `QUIET_UI = False`, воспроизведи, посмотри `[stroke]`-логи:
   `REJECTED (text mismatch)`? `WHOLE-BLOCK path`? `selection no-op`?
2. `rg "e_trans.setPlainText" ui/` — кто в последний раз писал панель
   (wiring на загрузке / `updateTranslation` / `layout_textblk` /
   `propagate_user_edit`); сравни `repr(item.toPlainText())` и
   `repr(panel.toPlainText())` — ищи `\xad`.
3. Блок flow? `"\u00ad" in item.document().toPlainText()` — есть hyphens →
   проверяй и панель (`panel.toPlainText()`), и стрип в страже.
4. Состояние: `blk.outline_ranges` (часть) vs `item.fontformat.stroke_width`
   / `blk.fontformat.stroke_width` (весь блок) — в какой ушла операция.
5. После смены режима? — ranges очищаются (вариант 3): это ожидаемо, не баг.
6. Тест не воспроизводит? Проверь, что тест льёт в панель то же самое, что
   реальный wiring (см. методология, п. 4).
7. Текст в баллоне не совпадает с панелью после правки? Ищи `[SYNC] I1` в
   логе; `text_coords.hyphen_count(item.document().toPlainText()) != 0`
   значит живут две координатные системы, и любой «сырой» int (позиция,
   спан, `removed`) через границу панель↔item — уже ошибка.

## Offscreen-пробники (репро без GUI)

| Скрипт | Назначение |
|--------|-----------|
| `_probe_flow_outline2.py` | 1:1 репро бага 2026-07-09: панель = `item.toPlainText()` (с hyphens) → `_effective_selection` → `ffmt_change_stroke_width` → ranges/groups |
| `_probe_flow_outline.py` | Сценарии S1–S3: flow/normal, установка в разных режимах, блок-скаляр + ranges |
| `_repro_e23.py` | Мерж stroke-групп: блок-скаляр + per-range |
| `_probe_bug1.py` | репро index-space propagate (`bug1.txt`): панель clean, item с `U+00AD` (H=3), selection-replace и одиночные keystrokes |
| `_probe_bug1_guard.py` | та же сцена в НЕ-STRICT (обычный запуск): что именно видит пользователь — `[SYNC] I1`/`I7` в логе, re-sync баллона по панели, `TC.trip_counts()` |

Запуск: `QT_QPA_PLATFORM=offscreen myenv\Scripts\python.exe <скрипт>`.
Нюанс для тестов: обёртка `font_formating` на whole-block пути создаёт
**ленивую** `TextStyleUndoCommand` — fake-канвас в тестах должен выполнять
`cmd.redo()` в `push_undo_command`, иначе операция не применится
(пример: `_RunningCanvas` в `tests/ui/test_flow_panel_outline.py`).

## Тесты

- `tests/ui/test_flow_panel_outline.py` — регрессии бага 2026-07-09 (12 тестов):
  hyphen-панель (wiring 1:1), clean-панель, srgb по выделению, normal-контроль,
  юниты `_panel_pos_to_clean`/`_panel_pos_to_doc_*`, стрип U+00AD в
  `update_textblk_list`, toggle flow↔normal очищает ranges (обратный вызов
  `SceneTextManager.toggle_block_flow_mode` через `SimpleNamespace`-self).
- `tests/ui/test_panel_stroke_display.py` — дисплей stroke-бокса панели;
  ⚠ исторически использовал `FakeTransEdit` с ЧИСТЫМ текстом — именно это
  расхождение с wiring позволило багу проживать (теперь есть
  `test_flow_panel_outline.py` с hyphen-панелью).
- `tests/ui/test_outline_ranges_stale.py` — инвалидация ranges при смене текста.
- `tests/ui/test_selection_stroke_command.py` — undo-команды selection-stroke.
- `tests/ui/test_flow_textitem.py` — `FlowTextBlkItem`, гифенизация
  (`_hyphenate_text`), эталон `_make_blk`/`_make_item` для создания блоков.
- `tests/test_text_coords.py` — юниты чистых мапперов clean↔document,
  диагностика `describe_desync`/`check` (dedup, first-diff), запрет
  импорта `qtpy` в `ui/text_coords.py`.
- `tests/ui/test_panel_edit_propagation.py` — propagate-путь панель↔item
  (T1–T13 из `PLAN_panel_edit_propagation.md`, + контроль старой реализации
  + реакция не-STRICT сборки): харнесс повторяет wiring
  1:1, инвариант I1 проверяется после каждого шага, а
  `test_legacy_propagate_arithmetic_corrupts_text` — контроль, что харнесс
  ловит СТАРУЮ реализацию (иначе зелёные тесты врут).
- STRICT текстовых инвариантов включён для всего `tests/`
  (`tests/conftest.py`, `BTRANS_STRICT_TEXT_SYNC=1`); там же фикстура
  `_isolate_text_diagnostics` сбрасывает dedup-множество и счётчик сессии,
  иначе лог рассогласования зависит от порядка запуска тестов.
- Два подводных камня при тестировании логов/слотов (без них тест бывает
  «зелёным» при мёртвой обработке правки):
  1. логгер `BallonTranslator` имеет `propagate=False` (`utils/logger.py`) —
     `caplog` его НЕ видит, перехватывать надо `TC.LOGGER.error/warning`
     через `monkeypatch.setattr`;
  2. PyQt молча глотает исключения внутри слотов, поэтому в харнессе слоты
     пишут их в `_Pair.errors`, а каждая правка завершается
     `_no_slot_errors()` (так всплыл `NameError` в `text_coords.warn_once`).
- Полный прогон (AGENTS.md): `myenv\Scripts\python.exe -m pytest tests/ -q`.