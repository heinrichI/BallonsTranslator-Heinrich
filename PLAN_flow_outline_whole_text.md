# План: «В Flow mode обводка части текста применяется ко всему тексту»

Дата: 2026-07-09
Статус: **внедрён Вариант 1 + Вариант 3** (2026-07-09)
- Ядро (В1): `transpair_wiring.py` — панель с чистым текстом; `textitem.py` —
  clean-vs-clean страж + `_panel_pos_to_clean` (маппинг и для legacy-панели
  с hyphens); стрип U+00AD при записи `blk.translation` (`block_manager`,
  `text_block_presenter`), защитный стрип в `scenetext_manager.updateTranslation`.
- В3: `toggle_block_flow_mode` очищает `blk.outline_ranges` при смене режима
  (block-level `fontformat.stroke_width` сохраняется).
- Тесты: `tests/ui/test_flow_panel_outline.py` (12 тестов). Полный прогон:
  600 passed, 6 skipped.
- Отложенно: Вариант 2 (хранение ranges в clean-координатах — обводки
  переживут смену режима без потери).
Пробные скрипты: `_probe_flow_outline.py`, `_probe_flow_outline2.py`, `_repro_e23.py`

## 1. Симптом

В Flow mode установка ширины обводки для **части** текста (выделение в панели e_trans
→ stroke width) приводит к обводке **всего** текста блока. В Normal mode то же самое
действие работает корректно (обводка только на выделенном слове).

## 2. Воспроизведение (offscreen, `_probe_flow_outline2.py`)

- Flow item + панельная инициализация как в приложении
  (`transpair_wiring.py:44`: `e_trans.setPlainText(blk_item.toPlainText())`):
  текст панели содержит soft hyphens `U+00AD` (гифенизация `_hyphenate_text`).
- Выделено «world» в панели.
- `item._effective_selection()` → `None` (панельное выделение **отклоняется**).
- `ffmt_change_stroke_width` → `stroke_sel=False` → whole-block path:
  `setStrokeWidth(0.5, set_selected=False)` → `item.fontformat.stroke_width = 0.5`
  → `_stroke_groups()` = `[(0, 24)]` — обводка на **весь** документ.
- Контроль (Normal item, без hyphens): `effective_selection=(6,11)`,
  `outline_ranges=[[6,11,...]]` — обводка только слова. Корректно.

## 3. Корневая причина (цепочка P1)

1. Документ `FlowTextBlkItem` содержит soft hyphens `U+00AD`
   (гифенизация в `flow_textitem.py::_hyphenate_text`; Normal item — нет).
2. Панель инициализируется «сырым» текстом item:
   `ui/transpair_wiring.py:44` — `pair_widget.e_trans.setPlainText(blk_item.toPlainText())`
   → в flow mode текст панели **с** hyphens.
   - Все блоки по умолчанию загружаются в flow mode (`is_flow_mode: bool = True`,
     `utils/textblock.py:55`).
   - `block_manager.update_textblk_list` (~стр. 135: `blk.translation = blk_item.toPlainText()`)
     **загрязняет модель** soft hyphens → попадает в проект-файл и обратно в e_trans
     через `scenetext_manager.py:1342` (`updateTranslation`).
3. Страж в `TextBlkItem._effective_selection()` (`ui/textitem.py:1766`):
   `item_text.replace('\u00ad','') != e_trans.toPlainText()` — сравнивает
   **clean** текст item с **сырым** текстом панели. В flow mode сравнение никогда
   не сходится → панельное выделение всегда отклоняется → `None` / `_last_selection`.
4. `ui/fontformat_commands.py:177-189` (аналогично `ffmt_change_srgb`):
   `stroke_sel = blkitems[0]._has_effective_selection()` == False → операция
   whole-block: `act_ffmt['stroke_width'] = value` + `set_selected=False` →
   `setStrokeWidth(value, set_selected=False)` → обводка всего текста.
   Та же неявный fallback бьёт по **всем** панельным selection-операциям flow-блоков
   (шрифт, размер, bold/italic…) — обводка просто наиболее заметна.

### Почему «именно при переключении в Flow mode»

- Блоки загружаются в flow mode по умолчанию → сразу после загрузки страницы
  панельный текст с hyphens → все selection-операции сломаны.
- В Normal mode панельный текст == тексту item (без hyphens) → работает — отсюда
  восприятие «появилось в flow mode».
- После toggle normal→flow первые операции ещё работают (e_trans не ресинкнут),
  а после переключения/сохранения страницы (ресинк через `wire_signals` /
  `updateTranslation`) — ломаются.

## 4. Вторичные дефекты (найдены при исследовании)

**P2. Разные координатные пространства `outline_ranges`.**
Диапазоны, установленные в Normal mode — «clean»-координаты; в flow mode —
документные координаты **с** hyphens. При переключении режима диапазоны не
пересчитываются, а снапшот `_outline_clean_text` сбрасывается на ребаинде
(`initTextBlock`) → stale-check не срабатывает:
- normal→flow: имеющаяся частичная обводка **смещается вправо**
  (репробан S2b: «world» (6,11) в doc с hyphenom накрывает « w orl»);
- flow→normal: диапазоны указывают «за хвост» текста.
Позицию обводки (не факт её наличия) это ломает и после переключения страниц.

**P3. Загрязнение `blk.translation` soft hyphens.**
`toPlainText()` flow item пишется в модель:
- `ui/block_manager.py` `update_textblk_list`;
- `ui/text_block_presenter.py:75,111` (`_on_text_edited`, `sync_to_model`);
→ zero-width символы в сохраняемых переводах, в панели, в проект-файле.

## 5. Варианты исправления

### Вариант 1 (минимальный: P1 + P3) — ядро, общее для всех вариантов
1. `ui/transpair_wiring.py:44` — текст панели без soft hyphens:
   `blk_item.toPlainText().replace('\u00ad', '')`.
2. `ui/textitem.py::_effective_selection` — страж mismatch сравнивает обе стороны
   в clean-виде: `item_text.replace('\u00ad','') != e_trans.toPlainText().replace('\u00ad','')`
   (терпит «застрявший» hyphen-панель в текущей сессии до перезагрузки).
3. `ui/textitem.py::_panel_pos_to_doc_start/_end` — маппинг по числу
   non-hyphen-символов **панельного** текста (корректен и для clean-, и для
   hyphen-панели).
4. Стрип soft hyphens при записи `blk.translation`:
   `block_manager.update_textblk_list`, `text_block_presenter.py:75,111`,
   (защитно) `scenetext_manager.py:1342`.
5. Регрессионный тест: панель инициализирована `item.toPlainText()` (с hyphens),
   выделение в панели → stroke/SRGB применяется только к диапазону.

Чинит: reported-симптом + все панельные selection-операции flow-блоков + чистые
переводы в проекте. **Не чинит** P2 (смещение диапазонов при смене режима).

### Вариант 2 (полный: вариант 1 + P2, обводки живут при смене режима)
Дополнительно хранить `outline_ranges` в **clean**-координатах (инвариантно к
режиму/загрузке):
6. `set_selection_outline` — перед сохранением переводит doc-позиции выделения
   в clean (счёт non-hyphen до позиции).
7. `_stroke_groups` / `paint_stroke` / `_range_font_size_px` — перед использованием
   маппят clean → координаты текущего документа (walk по тексту, skip `U+00AD`).
8. `get_selection_outline` — сравнение в clean-пространстве.
9. Миграция легаси-проектов (диапазоны в файле — flow doc-координаты): при загрузке
   flow-блока перевод в clean (детерминировано: режим сохраняется per-block).
   Защита: при загрузке в normal-блок диапазоны за пределами clean-текста
   инвалидируются (по образцу `_maybe_invalidate_outline_ranges`).
Плюс: частичные обводки сохраняют позицию при normal↔flow и при перезагрузке.
Минус: больше точек изменения + миграция формата координат (риск: ожидание в тестах
flow-блоков, работающих в doc-координатах).

### Вариант 3 (прагматичный: вариант 1 + защита от P2)
Вариант 1 + в `toggle_block_flow_mode` (`scenetext_manager.py:1120`) при смене
режима обнулять `blk.outline_ranges = []` (block-level `fontformat.stroke_width`
сохраняется). Частичные обводки не переносятся на смену режима, но и не «плывут»
тихо. Формат проекта не меняется.

## 6. Рекомендация

- Быстрый безопасный фикс reported-бага: **вариант 3** (ядро варианта 1 + очистка
  диапазонов на toggle).
- Полное устранение класса координатных багов (P2 бьёт также по srgb-обводке и
  любой future-фиче на ranges): **вариант 2**.
- Можно комбинировать: сначала выпустить вариант 3, затем вариант 2 (ядро варианта 1
  уже встало).

## 7. Проверка после фикса

- `QT_QPA_PLATFORM=offscreen myenv\Scripts\python.exe -m pytest tests/ -q`
- `_probe_flow_outline2.py`: flow → `effective_selection != None`,
  `groups` только на слове; normal — без регрессий.
- Сценарии `_probe_flow_outline.py` S1–S3: S2b после фикса — обводка на
  «world» (clean-координаты), а не « w orl» (только для вариантов 2/3-с-очисткой).
- Визуально: flow-блок, выделение слова в панели, stroke 0.5 → обводка только
  слова; toggle normal↔flow → обводка не смещается/не пропадает (вариант 2)
  или очищается (вариант 3).