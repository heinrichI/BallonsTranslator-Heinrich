---
name: font-auto-size
description: >
  Справочник по механизму авторазмера шрифта (auto font size) в BallonsTranslator:
  флаги, классы, триггеры пересчёта, программные точки входа, защита от рекурсии,
  цепочка применения пресетов шрифтов (TextStylePresetPanel).
  TRIGGER WHEN: работа с авторазмером шрифта, FontAutoAdjuster, FontSizeManager, shrink/grow,
  панелью шрифтов (font panel / текст-стили / prесеты), setFontSize / setFontFamily / set_fontformat,
  пересчёт размера шрифта после смены шрифта или применения пресета, «текст не влезает в блок».
  DO NOT TRIGGER WHEN: только UI пресетов без авторазмера; layout без шрифтов; flow-boundary
  control points (см. skill flow-blocks в .claude/skills/).
---

# Авторазмер шрифта (auto font size) — справочник

Механизм автоматической подгонки размера шрифта под размер текстового блока (облако/полоса),
чтобы текст влезал в выделенную область. Использовать при любой задаче, где размер шрифта
меняется программно или нужно понять, почему (не) сработал пересчёт.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `ui/font_auto_adjuster.py` | `FontAutoAdjuster` — shrink/grow калькулятор (инжектится в блоки) |
| `ui/font_size_manager.py` | `FontSizeManager` — единый источник правды размера (3 хранилища) |
| `ui/textitem.py` | `TextBlkItem` — плоские блоки: `_auto_adjust_font`, `set_size`, `setFontFamily`, `setFontSize`, `set_fontformat` |
| `ui/flow_textitem.py` | `FlowTextBlkItem` — flow-блоки: `_update_flow_layout(adjust_font=...)`, `scaleFontSizes` |
| `ui/fontformat_commands.py` | Команды панели: `ffmt_change_font_family`, `ffmt_change_font_size`, `ffmt_change_rel_font_size` (обёртка `font_formating` — undo через `TextStyleUndoCommand`) |
| `ui/text_layout_manager.py` | `TextLayoutManager` — pipeline auto-layout: бинарный поиск `_find_best_font_size` |
| `ui/text_style_presets.py` | `TextStylePresetPanel` / `TextStyleLabel` — панель сохранённых шрифтов (пресеты) |
| `ui/text_panel.py` | `FontFormatPanel` — панель форматирования: `FontFamilyComboBox` (245–279, создание 297–301), `on_param_changed` (501), `set_active_format` (556), `_refresh_font_size_display` (770) — обновляет размер-бокс панели |
| `ui/scenetext_manager.py` | `SceneTextManager` — `apply_fontformat`, `onFormatTextblks`, `onAutoLayoutTextblks` |
| `ui/textedit_commands.py` | Undo-команды: `ApplyFontformatCommand`, `AutoLayoutCommand`, `ReshapeItemCommand` |
| `utils/fontformat.py` | `FontFormat` — структура: `font_size` в px (поле), `size_pt` (property) |
| `utils/config.py` | `pcfg.let_fntsize_flag`, `pcfg.let_autolayout_flag`, `text_styles` (пресеты) |
| `ui/configpanel.py` | UI настроек: комбобокс «Font Size» (`let_fntsize_combox`), чекбокс «Auto layout» |

## Флаги

### Глобальные (настройки → Text Settings)

| Флаг | Значение | Хранение | UI |
|------|----------|----------|----|
| `pcfg.let_fntsize_flag: int` | `0` = авторазмер решает программа, `1` = всегда глобальный размер | `utils/config.py:106` | комбобокс `let_fntsize_combox` (`ui/configpanel.py:421`, обработчик `on_fntsize_flag_changed` — configpanel.py:553) |
| `pcfg.let_autolayout_flag: bool = True` | авто-лейаут pipeline | `utils/config.py:114` | чекбокс «Auto layout» (configpanel.py:458, обработчик :559) |

### Per-block

| Флаг | Где | Смысл |
|------|-----|-------|
| `TextBlkItem._auto_font_adjust` | `ui/textitem.py:122` (init: `pcfg.let_fntsize_flag != 1`) | разрешает авто-изменение размера. `FlowTextBlkItem` переопределяет: `True` при создании/resize, `False` после ручного изменения шрифта (flow_textitem.py:214) |
| `TextBlkItem._font_size_locked` | `textitem.py:127` | «замок» размера (контекстное меню) — блокирует любые авто-изменения |
| `FontAutoAdjuster._auto_grow_enabled` | `font_auto_adjuster.py:40` | разрешает grow (~90% заполнения); временно гасится при init-shrink и бинарном поиске (text_layout_manager.py:205–208, drawing_commands.py:154–157) |
| `TextLayoutManager.auto_textlayout_flag` | `text_layout_manager.py:73` | живёт только во время postprocess после pipeline: ставится `mainwindow.py:1297–1298` (`let_autolayout_flag and (enable_detect or enable_translate)`), сбрасывается `mainwindow.py:1311` |

Важно: при `setFontSize` (ручное изменение) `_auto_font_adjust` гасится в `False` (textitem.py:2074–2076; flow_textitem.py:710–712),
восстанавливается в `endReshape` (textitem.py:517–523), в конце `_update_block_layout` (textitem.py:875) и `_update_flow_layout` (flow_textitem.py:593).

## Ядро: `FontAutoAdjuster` (ui/font_auto_adjuster.py)

Конструктор: `__init__(layout, document, log, change_font_size, get_points, sync_font)` (строка 33).
Каббэки инжектятся владельцем (TextBlkItem / FlowTextBlkItem):
- `change_font_size(factor)` → у TextBlkItem `setRelFontSize(factor)` (textitem.py:759–766), у Flow `scaleFontSizes(factor)` (flow_textitem.py:470–480) — пропорционально масштабирует ВСЕ диапазоны, сохраняет per-selection размеры пользователя;
- `get_points()` → контрольные точки flow-границы (у плоских `([], [])` — textitem.py:753);
- `sync_font()` → `font_size_mgr.set(doc_pt, source="auto_layout")` (textitem.py:768–775; flow_textitem.py:482–489).

| Метод | Строка | Алгоритм |
|-------|--------|----------|
| `shrink()` | 44 | итеративно (≤20) уменьшает, пока текст не влез в target h/w; `factor = min(0.9, target/actual*0.95)` (101–107); пол на `MIN_FONT_SIZE_PT = 5.0` (14, 129–131); при успехе `sync_font()` (134–136); возвращает `bool applied` |
| `grow()` | 139 | итеративно (≤20) увеличивает, пока текст не займёт ≥90% высоты; `factor = min(1.08, height_factor, width_factor)` (198–203); стоп при переполнении ширины (190–194); **вызывать только если shrink не применился** |

Сигналов сам класс не издает — результат уходит через каббэки → reLayout → `size_enlarged` / `docSizeChanged`.

## `FontSizeManager` (ui/font_size_manager.py)

Единственный источник правды размера; синхронизирует 3 хранилища (docstring 1–14):
`fontformat.font_size` (px, view), `blk.fontformat.font_size` (px, модель), `document().defaultFont().pointSizeF()` (pt, Qt).
`set(size_pt, source="user")` (строка 35), `source ∈ {"user", "auto_layout", "pipeline", "init"}`.
Создаётся в `initTextBlock` (textitem.py:432). Сигналов нет.

## Триггеры пересчёта авторазмера

| Событие | Путь |
|---------|------|
| Drag ручки resize (flow) | handle'ы (`ui/flow_shapecontrol.py:82–110, 165–226, 264–328`) → `_update_flow_layout()` (flow_textitem.py:500): target из контрольных точек (525–548); при `adjust_font and _auto_font_adjust and let_fntsize_flag != 1 and not _font_size_locked` (569–571) → `shrink()` (572), `grow()` только если shrink не сработал (573–576); `reshaped.emit` (582) |
| Drag ручки resize (плоский) | `texteditshapecontrol.py:185–190` → `setRect` → хук в `TextBlkItem.setRect` (textitem.py:536; 576–580, Δsize > 0.5) → `_auto_adjust_font(target_w, target_h)` (textitem.py:777–848): сброс layout-ограничений (810–817), `shrink()`, при влезании повторная `set_size(..., auto_font_adjust=False)` (834–837), иначе `grow()` (838–840) |
| Pipeline перевода (смена текста) | `TextLayoutManager.layout_textblk` (text_layout_manager.py:76): auto-режим при `auto_textlayout_flag and let_fntsize_flag == 0 and let_autolayout_flag` (121); `_auto_layout` (133–216): бинарный поиск `_find_best_font_size` (218–287, 30 итераций, `blockSignals(True)`), `font_size_mgr.set(optimal, source="auto_layout")` (201), финальный shrink-проход с grow выключен (205–208). Вызывается из `SceneTextManager.addTextBlock` (scenetext_manager.py:645–660) и undo-команды перевода `drawing_commands.py:108–185` |
| Ввод текста (flow) | `FlowTextBlkItem.setPlainText` (flow_textitem.py:348–352) — shrink НЕ вызывает сразу, отложен на `set_size()` |
| Ввод текста (плоский) | переполнение → `size_enlarged` (scene_textlayout.py:444–455) → `on_document_enlarged` (textitem.py:929–931) → `set_size(w, h)` (2191, `auto_font_adjust=True` по умолчанию) → `_auto_adjust_font` (2247) — только если `_auto_font_adjust` и размер реально изменился |
| Загрузка страницы/проекта | `FlowTextBlkItem.__init__` (flow_textitem.py:265–281): при сохранённых точках — grow выключается (271/276), принудительный layout, `shrink()`, grow включается; при `let_fntsize_flag == 1 or not let_autolayout_flag` → `_auto_font_adjust = False` (280); для pipeline-блоков без точек: shrink если `max_font_size() > 20.0` (284–297) |
| **Смена шрифта (family)** | **прямого триггера НЕТ** (см. ниже) |

### ⚠ Ключевой нюанс: смена family не пересчитывает размер

Никакой явной логики «после смены family, если авторазмер включён, пересчитать size» в проекте нет:
- обычный комбобокс: `FontFamilyComboBox` (`ui/text_panel.py:245–279`, создание 297–301) → `on_fontfamily_changed` (274–278) → `param_changed.emit('font_family', ...)` (256–259) → `FontFormatPanel.on_param_changed` (text_panel.py:501) → `ffmt_change_font_family` (fontformat_commands.py:189) → `TextBlkItem.setFontFamily` (textitem.py:1538–1544): `_doc_set_font_family` (1546–1583, размер/weight сохраняются) → `reLayoutEverything()`;
- **flow-блоки**: `size_enlarged`/`docSizeChanged` лишь обновляют `_display_rect` (flow_textitem.py:810–821) — shrink/grow не запускаются вообще;
- **плоские блоки**: пересчёт возможен ТОЛЬКО как побочный эффект переполнения (`size_enlarged` → `set_size` → `_auto_adjust_font`); если текст влезает — ничего не пересчитывается.

## Программные точки входа «подогнать размер шрифта к объекту»

| Задача | Вызов |
|--------|-------|
| Один плоский блок | `blkitem._auto_adjust_font(target_w, target_h)` (textitem.py:777; guards: `_auto_adjusting`, `_fully_initialized`, `_auto_font_adjust`, `_font_size_locked`, `let_fntsize_flag == 1` — 792–806) |
| Один flow-блок | `blkitem._update_flow_layout(adjust_font=True)` (flow_textitem.py:500) или напрямую `blkitem.font_adjuster.shrink()` / `.grow()` (font_auto_adjuster.py:44/139) |
| Выбранные блоки (как меню «Auto layout») | `SceneTextManager.onAutoLayoutTextblks` (scenetext_manager.py:1091–1123): `canvas.selected_text_items()` минус вертикальные → `ensure_text_in_block` + `layout_textblk` (1151–1170) → `AutoLayoutCommand` (textedit_commands.py:200–234). Триггеры: контекстное меню канваса (canvas.py:847, 866, 899–900) и event bus `Events.LAYOUT_TEXT_BLOCKS` (event_bus.py:117; подписка scenetext_manager.py:484) |
| Нюанс: бинарный поиск в `layout_textblk` работает только при `auto_textlayout_flag=True` (живёт во время pipeline postprocess); ручной вызов из меню обычно делает mask-based layout с глобальным размером (text_layout_manager.py:125–130) | |

## Цепочка применения пресета шрифта (TextStylePresetPanel)

Панель: `ui/text_style_presets.py` — `TextStylePresetPanel` (262), чип `TextStyleLabel` (59), имя — `StyleLabel` (26).
Подключение: `FontFormatPanel` (ui/text_panel.py:281) создаёт панель (376); `TextPanel` (ui/scenetext_manager.py:351) создаёт `FontFormatPanel` (356);
`mainwindow.py:458` → `initStyles(text_styles)` (tsp:417); перезагрузка из каталога проекта — mainwindow.py:519–526; импорт — mainwindow.py:1425–1427.

1. Кнопка Apply на чипе: `apply_btn.clicked → on_applybtn_clicked` (tsp:99, 139–140) → сигнал `apply_fontfmt(FontFormat)` (tsp:64) — передаётся **целый FontFormat** пресета (family + size + stroke + цвета + ...);
2. пересылка панелью: tsp:321 (новые) / tsp:378 (загруженные) → сигнал панели tsp:266;
3. `formatpanel.textstyle_panel.apply_fontfmt.connect(self.onFormatTextblks)` (scenetext_manager.py:398); тот же хендлер на `canvas.format_textblks` (:384) и `Events.FORMAT_TEXT_BLOCKS` (:483);
4. `onFormatTextblks` (scenetext_manager.py:1071–1074): `fmt is None` → `formatpanel.global_format`, иначе `apply_fontformat(fmt)`;
5. `apply_fontformat` (scenetext_manager.py:1284–1295): `canvas.selected_text_items()` + e_trans-виджеты → `push_undo_command(ApplyFontformatCommand(...), is_text=True)` (1290); затем обновление панели (1291–1295);
6. `ApplyFontformatCommand.redo()` (ui/textedit_commands.py:88–91) → `item.set_fontformat(self.new_fmt, set_char_format=True)` (90) + `clearUndoRedoStacks()`;
7. `TextBlkItem.set_fontformat` (textitem.py:1352): `font.setFamily` (1362), `font.setPointSizeF(ffmat.size_pt)` (1363), `document().setDefaultFont` (1374), char/block-форматы, shadow/stroke/opacity, выравнивание, `fontformat.merge(ffmat)` (1431).

У `ApplyFontformatCommand` НЕТ флага «recalc size»; авторазмер при применении пресета возможен только как побочный эффект переполнения layout (см. выше).

Хранение пресетов: `pcfg.text_styles_path` (utils/config.py:118, по умолчанию `config/textstyles/default.json`), `pcfg.text_styles: List[FontFormat]` (config.py:193),
`load_textstyle_from` (196), `save_text_styles` (280–297, атомарно через `.tmp` + `os.replace`); размер хранится в пресете (поле `FontFormat.font_size` px — utils/fontformat.py:62).

## Сигналы и undo

| Сигнал | Источник | Обработчик |
|--------|----------|------------|
| `TextBlkItem.reshaped = Signal(QGraphicsTextItem)` (textitem.py:62) | emit-источники: textitem.py:523 (`endReshape`), textitem.py:843 (после `_auto_adjust_font` при `font_changed`), flow_textitem.py:582 (после `_update_flow_layout` при `font_changed`) | два потребителя: `SceneTextManager.onTextBlkItemReshaped` (scenetext_manager.py:1029, connect 802/823) — ТОЛЬКО пушит `ReshapeItemCommand`, панель НЕ обновляет; `FlowPresenter._on_reshaped` (ui/flow_presenter.py:73–83) — сохраняет контрольные точки flow в модель |
| `TextBlkItem.doc_size_changed = Signal(int)` (textitem.py:63) | `docSizeChanged` (436–438) | `onTextBlkItemSizeChanged` (917–921) — bounding rect shape control |
| `SceneTextLayout.size_enlarged` (scene_textlayout.py:223) | переполнение (444–455) | `on_document_enlarged` (connect textitem.py:710) |

### ⚠ Undo-семантика `ReshapeItemCommand` (ui/textedit_commands.py:101–160)

- При создании снимает: `oldRect = item.oldRect` (pre-reshape снапшот), `newRect = item.absBoundingRect(qrect=True)` (текущее), `old_font_size = new_font_size = item.fontformat.font_size` — **оба равны размеру, который уже вступил к моменту пуша** (reshaped летит ПОСЛЕ изменения). Для font-refit без смены rect команда дегенеративна: undo/redo делают setRect того же rect + `font_size_mgr.set` того же размера + `_update_flow_layout`.
- Первый `redo()` — no-op (idx −1→0, состояние уже изменено — команда «коммитится» при пуше в QUndoStack); последующие redo: `setRect(newRect)` + `sync_coordinates` + `font_size_mgr.set(px2pt(new_font_size), source="undo_redo")` + restore flow points + `_update_flow_layout()`.
- `mergeWith` сливает последовательные команды по одному item (`newRect = item.rect()`).
- Практический вывод: при «пресет → авторазмер» в undo-стек ложится ДВЕ команды (`ApplyFontformatCommand` + дегенеративная `ReshapeItemCommand`); чтобы не мусорить стек, подавлять `reshaped` на время программной подгонки (`blk.reshaped.blockSignals(True/False)`) — НО это блокирует и `FlowPresenter._on_reshaped` (сохранение контрольных точек в модель): безопасно только если подгонка точек НЕ меняет (меняет только размер шрифта).
- Обновление размер-бокса панели после программных изменений — `_refresh_font_size_display` (text_panel.py:770); без вызова бокс обновится только при focus-in.

## Защита от рекурсии и осцилляций

- `FontAutoAdjuster._internal_font_change` (font_auto_adjuster.py:41): True во время `_change_font_size` (121–125, 207–211) и в кабеляках владельцев (textitem.py:762–766; flow_textitem.py:476–480; drawing_commands.py:175–179). Проверяется в `setFontSize` (textitem.py:2074; flow_textitem.py:710–712): внутренние изменения от shrink/grow НЕ гасят `_auto_font_adjust` и НЕ помечают размер как «user».
- Re-entrancy-гард `_auto_adjusting` (textitem.py:129, проверка 792–794): обрывает цикл shrink/grow → `setRelFontSize` → `setFontSize` → `squeezeBoundingRect` → `set_size` → `_auto_adjust_font`.
- Re-entrancy-гард `_updating_flow` (flow_textitem.py:205, проверка 507–512): сигналы от reLayout внутри grow/shrink не вызывают рекурсивно `_update_flow_layout`.
- «grow только если shrink НЕ применился» (textitem.py:838–840; flow_textitem.py:573–576).
- `squeezeBoundingRect` flow-блока — с `auto_font_adjust=False` (flow_textitem.py:782–806), чтобы grow не переписывал выбор пользователя.
- `setAlignment` → `_update_flow_layout(adjust_font=False)` (flow_textitem.py:680–691) — иначе каждое выравнивание re-grow'ит шрифт.
- Ограничители: shrink/grow ≤ 20 итераций, factor ≤ 0.9 / ≤ 1.08, пол `MIN_FONT_SIZE_PT = 5.0` (font_auto_adjuster.py:14).
- Бинарный поиск: `blockSignals(True)` + `repaint_on_changed=False` + `set_size(..., auto_font_adjust=False)` (text_layout_manager.py:237–241, 252); `setFontSize(..., _is_auto_layout=True)` не затирает `fontformat`/`_user_font_size` (textitem.py:2063–2066).
- Undo resize восстанавливает размер через `font_size_mgr.set(..., source="undo_redo")` (textedit_commands.py:135–137, 147–149).

## Тесты

Полный прогон: `myenv\Scripts\python.exe -m pytest tests/ -q` (единственный интерпретатор — venv `myenv`, см. AGENTS.md; UI-тесты требуют `QT_QPA_PLATFORM=offscreen`).

### Инфраструктура (tests/ui/)

- `tests/ui/conftest.py`: session-fixture `qapp` (offscreen `QApplication`) + per-test `scene` (`QGraphicsScene` + `QGraphicsView` 2000×2000) — общий для всех tests/ui.
- **Эталон создания блоков**: `_make_blk`/`_make_item` в `test_flow_textitem.py:37/51` — `TextBlock` с `lines`/`translation`, `fontformat.font_size = pt2px(...)`, `_bounding_rect`; `FlowTextBlkItem(blk, idx=0, show_rect=False)` + `scene.addItem`. Plain `TextBlkItem`: `test_block_xyxyxy_sync.py:60`, `test_outline_ranges_stale.py:74`; расширенный (stroke/vertical/flow mode) — `test_stroke_rect_on_autolayout.py`.
- **Стандартный паттерн авторазмера** (`test_flow_textitem.py:754–830`): `_make_item` → `setPlainText(text)` → `_update_flow_layout()` → `item._auto_font_adjust = True` → resize (`setRect`/`set_size`) → assert `item.layout.max_font_size()` / `item.font().pointSizeF()`.
- **Заглушки менеджера**: `_FakeCanvas`/`FakeTransEdit`/`_FakeStManager` + `_wire_pairwidgets` (`test_panel_fontsize_display.py`) — запись `push_undo_command`, шутрование `selected_text_items`/`apply_fontformat`; `_fake_manager` (`test_stroke_rect_on_autolayout.py:121+`) — `SimpleNamespace` + `MethodType(SceneTextManager.<метод>, fake)` — вызов реальных методов `SceneTextManager` без mainwindow.
- **Undo-циклы на живом стеке**: `FakeEdit`/`FakeShapeCtrl`/`_make_window` + `QUndoStack` (`test_global_undo_shortcut.py:50–73`, применение стиля — :204).
- **Тестов TextStylePresetPanel / apply_fontfmt / onAutoLayoutTextblks / AutoLayoutCommand НЕТ** (покрытие пресетной панели отсутствует); `ApplyFontformatCommand` частично покрыт в `test_global_undo_shortcut.py:35,204`, `ReshapeItemCommand` — в `test_block_xyxy_sync.py:637,649` и `test_flow_textitem.py:919,933`.

### Существующие тесты по размеру шрифта

- `tests/ui/test_fontsize_box_buttons.py` — кнопки up/down FontSizeBox парсят дисплейный текст без крашей (RU-locale '12,5', multi-size '15.3+').
- `tests/ui/test_size_combobox_value.py` — парсинг `SizeComboBox.value()` ("24,5", "15.3+" → 15.3, settrace-проверка нулевого числа ValueError), локальный фикстур `SizeComboBox(val_range=[0,200], init_value=10)`.
- `tests/ui/test_panel_fontsize_display.py` — размер-бокс следует живому курсору/выделению (регрессия «Hello»→30pt / «world»→24pt), refresh при focus-in не пушит undo, e2e `panel.on_param_changed('font_size', 30)`.
- `tests/ui/test_stroke_rect_on_autolayout.py` — авто-блоки со stroke → прямоугольный view, без overlap-чека (task10).