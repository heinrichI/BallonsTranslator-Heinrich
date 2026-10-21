"""
Регрессии propagate-пути «панель перевода ↔ документ item» (bug1.txt).

Класс бага — index-space: панель держит CLEAN-текст, а документ
FlowTextBlkItem содержит soft hyphens (U+00AD), и правка переносилась
позиционно + с «removed», выведенным арифметикой двух characterCount().
Текст в баллоне «пережёвывался» (ВИДЕШЬ? → ВИДШЬЕГО...).

Харнесс повторяет боевое wiring 1:1 (методология debug-text-ui п.4):
  * панель инициализируется дословно как transpair_wiring.py:48;
  * сигнал propagate_user_edited подключён как transpair_wiring.py:62,
    тело обработчика — как SceneTextManager.on_propagate_{transwidget,textitem}_edit;
  * сама правка идёт через QTextCursor панели, т.е. через реальные
    contentsChange → handle_content_change → emit (позиции и removed
    берутся из Qt, а не подставляются руками).

Запуск:
    set QT_QPA_PLATFORM=offscreen
    myenv\\Scripts\\python.exe -m pytest tests/ui/test_panel_edit_propagation.py -q
"""

import os
import random
import sys
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from qtpy.QtCore import Qt
from qtpy.QtGui import QTextCursor

from utils.textblock import TextBlock
from ui import text_coords as TC
from ui import text_sync as TS
from ui.flow_textitem import FlowTextBlkItem
from ui.page_search_widget import Matched
from ui.textedit_area import TransTextEdit
from ui.textedit_commands import propagate_user_edit
from ui.textitem import TextBlkItem

PANEL_TEXT = "ВИДИТЕ? У НЕГО С ЭТИМ КАКИЕ-ТО..."
TARGET = "ВИДЕШЬ? У НЕГО..."
#: что осело в баллоне до фикса (пробник _probe_bug1.py)
CORRUPT_1 = "ВИЕШЬ У НЕГО ..."
CORRUPT_REPORT = "ВИДШЬЕГО С ЭТИМ КАКИЕ-ТО..."


@pytest.fixture(autouse=True)
def _strict_text_sync():
    """В тестах рассогласование — падение, а не молчаливый re-sync (§5.3)."""
    TC.set_strict(True)
    yield
    TC.set_strict(None)


def _make_blk(text=PANEL_TEXT, xyxy=(0, 0, 400, 200), font_size=24.0):
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


class _Pair:
    """Пара «панель + item» с боевым wiring (transpair_wiring.py:48/62)."""

    def __init__(self, cls, scene, text=PANEL_TEXT):
        self.blk = _make_blk(text=text)
        self.item = cls(self.blk, idx=0, show_rect=False)
        scene.addItem(self.item)

        self.panel = TransTextEdit(0, None)
        # дословно transpair_wiring.py:48 — панель всегда clean
        self.panel.setPlainText(self.item.toPlainText().replace("\u00ad", ""))
        self.panel.old_undo_steps = self.panel.document().availableUndoSteps()
        self.item.repaint_on_changed = False

        # offscreen-фокус реальный нет: эмиттеры проверяют hasFocus()
        self._focus = {"panel": True, "item": False}
        self.panel.hasFocus = lambda: self._focus["panel"]
        self.item.hasFocus = lambda: self._focus["item"]

        self.panel.propagate_user_edited.connect(self._on_panel_edit)
        self.item.propagate_user_edited.connect(self._on_item_edit)
        self.errors = []      # исключения, проглоченные Qt внутри слотов

    # ── обработчики, повторяющие scenetext_manager.py:1299-1312 ──
    def _on_panel_edit(self, pos, added_text, joint_previous, removed):
        if self.item.isEditing():
            self.item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        try:
            propagate_user_edit(self.panel, self.item, pos, added_text,
                                joint_previous, removed)
        except Exception as e:            # как в проде: PyQt глотает слоты
            self.errors.append(f"panel->item: {e!r}")

    def _on_item_edit(self, pos, added_text, joint_previous, removed):
        try:
            propagate_user_edit(self.item, self.panel, pos, added_text,
                                joint_previous, removed)
        except Exception as e:
            self.errors.append(f"item->panel: {e!r}")

    # ── наблюдаемое состояние ──
    @property
    def doc(self) -> str:
        return self.item.document().toPlainText()

    @property
    def item_clean(self) -> str:
        return TC.strip_hyphens(self.doc)

    @property
    def panel_text(self) -> str:
        return self.panel.toPlainText()

    @property
    def hyphens(self) -> int:
        return TC.hyphen_count(self.doc)

    # ── правки на панели (clean-координаты) ──
    def panel_edit(self, start, end, text, *, paste=False, ime=False):
        self._focus["panel"], self._focus["item"] = True, False
        if ime:
            self.panel.input_method_from = start
            self.panel.input_method_text = text
        cursor = self.panel.textCursor()
        cursor.setPosition(start)
        if end > start:
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        if paste:
            # как при вставке из контекстного меню: paste_flag + in_acts
            # (on_content_changed в это время handle_content_change НЕ зовёт),
            # затем явный handle_content_change() — так делает contextMenuEvent,
            # когда курсор виджета уже указывает на конец вставленного
            self.panel.paste_flag = True
            self.panel.in_acts = True
            cursor.insertText(text)
            self.panel.setTextCursor(cursor)
            self.panel.in_acts = False
            self.panel.handle_content_change()
            self._no_slot_errors()
            return
        cursor.insertText(text)
        self.panel.setTextCursor(cursor)   # как при реальном вводе
        self._no_slot_errors()

    # ── правки прямо на canvas (doc-координаты, clean-позиция входа) ──
    def item_edit(self, clean_start, clean_end, text):
        self._focus["item"], self._focus["panel"] = True, False
        start = TC.doc_start_for_clean(self.doc, clean_start)
        end = TC.doc_end_for_clean(self.doc, clean_end)
        cursor = self.item.textCursor()
        cursor.setPosition(start)
        if end > start:
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.item.setTextCursor(cursor)
        self._no_slot_errors()

    def _no_slot_errors(self):
        """Обработка правки не имеет права бросать внутри слота: PyQt такое
        исключение глотает молча, и тест остаётся «зелёным», хотя перенос не
        отработал (так потерялся NameError в text_coords.warn_once)."""
        assert not self.errors, self.errors
        return True

    def assert_in_sync(self, where=""):
        """Тот же I1, что и в проде: в STRICT расхождение = падение теста."""
        TS.verify_sync(self.panel, self.item, where=where or "test")
        assert self.item_clean == self.panel_text, (
            f"[SYNC] I1 panel<->item MISMATCH {where}\n"
            f"  panel : {self.panel_text!r}\n"
            f"  item  : {self.item_clean!r}\n"
            f"  doc   : {self.doc!r} (H={self.hyphens})")


# ── контроль: харнесс обязан ловить старый код ──────────

def test_legacy_propagate_arithmetic_corrupts_text(scene, monkeypatch):
    """Контроль (debug-text-ui п.4): та же последовательность правок, но со
    СТАРОЙ реализацией переноса (арифметика двух characterCount() +
    позиционный перенос) обязана портить текст — иначе харнесс врёт и
    T1–T7 зелёные на сломанном коде."""
    import ui.textedit_commands as TEC

    def legacy(src_edit, target_edit, pos, added_text, joint_previous=False,
               removed=None):
        ori_count = target_edit.document().characterCount()
        new_count = src_edit.document().characterCount()
        removed = ori_count + len(added_text) - new_count
        cursor = target_edit.textCursor()
        cursor.setPosition(pos)
        if joint_previous:
            cursor.joinPreviousEditBlock()
        else:
            cursor.beginEditBlock()
        if removed > 0:
            cursor.setPosition(pos + removed, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(added_text)
        cursor.endEditBlock()
        target_edit.old_undo_steps = target_edit.document().availableUndoSteps()

    monkeypatch.setattr(TEC, "propagate_user_edit", legacy)

    p = _Pair(FlowTextBlkItem, scene)
    p._on_panel_edit_orig = p._on_panel_edit
    p.panel.propagate_user_edited.disconnect(p._on_panel_edit)

    def on_legacy(pos, added_text, joint_previous, removed):
        legacy(p.panel, p.item, pos, added_text, joint_previous, removed)

    p.panel.propagate_user_edited.connect(on_legacy)

    p.panel_edit(3, 6, "ЕШЬ")
    p.panel_edit(14, 30, "")
    assert p.panel_text == TARGET                      # панель-то правильная
    assert p.item_clean == CORRUPT_1                   # а баллон испорчен
    with pytest.raises(TC.TextSyncError):
        p.assert_in_sync("legacy propagate")


# ── T1: направление панель → item ─────────────────────────

def test_flow_panel_typing_keeps_item_in_sync(scene):
    """T1 — сам баг: правка в панели портила текст баллона (красен до фикса)."""
    p = _Pair(FlowTextBlkItem, scene)
    assert p.hyphens == 3, "flow-документ обязан содержать soft hyphens (H=3)"

    p.panel_edit(3, 6, "ЕШЬ")            # ВИДИТЕ → ВИДЕШЬ
    p.assert_in_sync("after 'ИТЕ'->'ЕШЬ'")
    assert p.panel_text == "ВИДЕШЬ? У НЕГО С ЭТИМ КАКИЕ-ТО..."
    assert p.item_clean == p.panel_text
    assert p.panel_text not in (CORRUPT_1, CORRUPT_REPORT)
    assert p.hyphens == 2               # hyphen внутри спана съеден, хвост цел

    p.panel_edit(14, 30, "")                 # снести хвост 'С ЭТИМ КАКИЕ-ТО'
    p.assert_in_sync("after tail delete")
    assert p.panel_text == TARGET
    assert p.item_clean == TARGET


def test_normal_item_typing_control(scene):
    """T2 — контроль: обычный TextBlkItem (H=0) вёл себя верно и раньше."""
    p = _Pair(TextBlkItem, scene)
    assert p.hyphens == 0

    p.panel_edit(3, 6, "ЕШЬ")
    p.assert_in_sync("normal: replace")
    p.panel_edit(14, 30, "")
    p.assert_in_sync("normal: tail delete")
    assert p.panel_text == p.item_clean == TARGET


# ── T3: обратное направление (правка прямо на canvas) ────────

def test_item_to_panel_typing_sync(scene):
    """T3 — тот же баг с другим знаком: removed уходил в минус, pos был
    завышен на число hyphens левее → в панель текст вставлялся со сдвигом."""
    p = _Pair(FlowTextBlkItem, scene)

    p.item_edit(15, 15, "ОЧЕНЬ ")
    p.assert_in_sync("item insert before 'С'")
    expected = "ВИДИТЕ? У НЕГО ОЧЕНЬ С ЭТИМ КАКИЕ-ТО..."
    assert p.panel_text == expected
    assert "\u00ad" not in p.panel_text, "панель обязана оставаться clean"

    p.item_edit(len(expected) - 1, len(expected), "")   # один backspace на canvas
    expected = expected[:-1]
    p.assert_in_sync("item backspace")
    assert p.panel_text == expected

    p.item_edit(0, 3, "Х")                    # замена через hyphen-границу (ВИ\xadД)
    expected = "Х" + expected[3:]
    p.assert_in_sync("item replace across hyphen")
    assert p.panel_text == expected


# ── T4: диапазон через soft hyphen ───────────────────────────

def test_replace_across_soft_hyphen(scene):
    """T4 — длина выделенного диапазона в doc-координатах ≠ clean-длине."""
    p = _Pair(FlowTextBlkItem, scene)
    assert p.hyphens == 3
    # 'КА\xadКИЕ': clean 23..25 = 'АК' — hyphen сидит ровно между этими буквами
    p.panel_edit(23, 25, "И")
    p.assert_in_sync("replace 'АК'->'И' across U+00AD")
    assert p.panel_text == "ВИДИТЕ? У НЕГО С ЭТИМ КИИЕ-ТО..."
    assert p.item_clean == p.panel_text
    assert p.hyphens == 2, "hyphen внутри удалённого диапазона должен исчезнуть"


# ── T5: цепочка одиночных backspace ──────────────────────────

def test_backspace_chain_flow_block(scene):
    """T5 — removed_computed = реальный + H: каждый backspace съедал
    дополнительно по H символов."""
    p = _Pair(FlowTextBlkItem, scene)
    expected = p.panel_text
    for i in range(8):
        at = len(expected)
        p.panel_edit(at - 1, at, "")
        expected = expected[:-1]
        p.assert_in_sync(f"backspace #{i + 1}")
        assert p.item_clean == expected


# ── T6: перевод строки (блочные терминаторы, C2) ─────────────

def test_insert_newline_flow_block(scene):
    """T6 — Return в панели: characterCount() compensate ломается даже при
    H=0, а selectedText() отдаёт U+2028 вместо '\\n'."""
    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(7, 7, "\n")
    p.assert_in_sync("insert newline at clean 7")
    assert p.panel_text == "ВИДИТЕ?\n У НЕГО С ЭТИМ КАКИЕ-ТО..."
    assert p.panel.document().blockCount() == p.item.document().blockCount() == 2

    p.panel_edit(0, 8, "ВИД\nИТЕ? ")
    p.assert_in_sync("replace spanning the newline")
    assert p.panel.document().blockCount() == p.item.document().blockCount()


# ── T7: альтернативные источники added_text ──────────────────

def test_paste_sync(scene):
    """T7a — путь paste_flag (textedit_area.py:180-187)."""
    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(17, 21, "ЗАЧЕМ", paste=True)   # ЭТИМ -> ЗАЧЕМ
    p.assert_in_sync("paste replace 'ЭТИМ'->'ЗАЧЕМ'")
    assert p.panel_text == "ВИДИТЕ? У НЕГО С ЗАЧЕМ КАКИЕ-ТО..."
    assert p.item_clean == p.panel_text


def test_ime_commit_sync(scene):
    """T7b — путь input_method_from/input_method_text (IM-коммит)."""
    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(15, 15, "Ж", ime=True)
    p.assert_in_sync("ime commit 'Ж'")
    assert p.panel_text == "ВИДИТЕ? У НЕГО ЖС ЭТИМ КАКИЕ-ТО..."
    assert p.item_clean == p.panel_text


# ── T11: порча не должна уходить в проект-файл ───────────────

def test_translation_has_no_soft_hyphens_after_typing(scene):
    """T11 — после правки сохранение (block_manager.update_textblk_list)
    не должно писать U+00AD в blk.translation."""
    from ui.block_manager import BlockManager

    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(3, 6, "ЕШЬ")
    p.assert_in_sync("before save")
    assert p.hyphens > 0, "без hyphens в документе тест ничего не проверяет"

    class _Canvas:
        def removeItem(self, *a):
            pass

    class _TextList:
        def removeWidget(self, *a):
            pass

    class _TransPair:
        def __init__(self, panel):
            self.e_trans = panel

            class _E:
                @staticmethod
                def toPlainText():
                    return "source text"
            self.e_source = _E()

    class _Proj:
        def current_block_list(self):
            return []

    bm = BlockManager(_Canvas(), _TextList())
    bm.textblk_item_list = [p.item]
    bm.pairwidget_list = [_TransPair(p.panel)]
    bm.update_textblk_list(_Proj())

    assert p.blk.translation == p.panel_text
    assert "\u00ad" not in p.blk.translation, \
        f"soft hyphens ушли в модель: {p.blk.translation!r}"


def test_presave_panel_wins_over_corrupted_item(scene):
    """I7: расхождение прямо перед save — панель (канал ввода) источник
    правды: item пере-синкается по ней, и в проект-файл уходит текст
    пользователя, а не испорченное зеркало (§5.2, §6)."""
    from ui.block_manager import BlockManager

    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(3, 6, "ЕШЬ")
    # «сторонний писатель» портил item после последней правки
    p.item.document().setPlainText("ВИ\u00adЕ\u00adШЬ У НЕГО ...")
    assert p.item_clean != p.panel_text

    class _Canvas:
        def removeItem(self, *a):
            pass

    class _TextList:
        def removeWidget(self, *a):
            pass

    class _TransPair:
        def __init__(self, panel):
            self.e_trans = panel

            class _E:
                @staticmethod
                def toPlainText():
                    return "source text"
            self.e_source = _E()

    class _Proj:
        def current_block_list(self):
            return []

    bm = BlockManager(_Canvas(), _TextList())
    bm.textblk_item_list = [p.item]
    bm.pairwidget_list = [_TransPair(p.panel)]
    bm.update_textblk_list(_Proj())

    # модель получила текст ПАНЕЛИ, а не порчу из item
    assert p.blk.translation == p.panel_text
    assert "\u00ad" not in p.blk.translation
    # item восстановлен по панели (flow-документ перегифенизован)
    assert p.item_clean == p.panel_text
    p.assert_in_sync("after pre-save resync")


# ── updateTranslation (focus-out): I2/I3 + NameError-регрессия ────

def _fake_stm(p):
    """SceneTextManager.updateTranslation читает только эти атрибуты."""
    return SimpleNamespace(
        textblk_item_list=[p.item],
        pairwidget_list=[SimpleNamespace(e_trans=p.panel)],
        canvas=SimpleNamespace(clear_text_stack=lambda: None),
    )


def test_update_translation_resyncs_from_clean_model(scene):
    """Регрессия NameError: updateTranslation вызывала clean_text_value,
    который не был импортирован (import отсутствовал) — PyQt глотал
    исключение в слоте, и ресинк при focus-out молчал. В STRICT чистая
    модель обязана пройти без единого срабатывания."""
    from ui.scenetext_manager import SceneTextManager

    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(3, 6, "ЕШЬ")
    p.assert_in_sync("before")
    TC.reset_trip_counts()
    p.blk.translation = p.panel_text          # модель чистая (после save)

    SceneTextManager.updateTranslation(_fake_stm(p))   # не бросает (STRICT)

    assert p.panel_text == "ВИДЕШЬ? У НЕГО С ЭТИМ КАКИЕ-ТО..."
    assert p.item_clean == p.panel_text
    p.assert_in_sync("after updateTranslation")
    assert TC.trip_counts() == {}, f"чистый путь не должен щёлкать стражей: {TC.trip_counts()}"


def test_update_translation_dirty_model_raises_in_strict(scene):
    """STRICT (dev/тесты): legacy-грязная blk.translation (U+00AD из
    проект-файла, §6) — падение, а не молчаливое проглатывание."""
    from ui.scenetext_manager import SceneTextManager

    p = _Pair(FlowTextBlkItem, scene)
    p.blk.translation = "ВИ\u00adДИТЕ? У НЕГО С ЭТИМ КА\u00adКИЕ-ТО..."

    with pytest.raises(TC.TextSyncError, match="I2"):
        SceneTextManager.updateTranslation(_fake_stm(p))


def test_update_translation_dirty_model_legacy_clean_run(scene, monkeypatch):
    """§6 в обычной сборке: не роняем GUI, пишем [SYNC] I2 в лог и даём
    и панели, и item чистый текст (flow-item перегифенизует сам)."""
    from ui.scenetext_manager import SceneTextManager

    TC.set_strict(False)
    TC.reset_dedup()
    try:
        p = _Pair(FlowTextBlkItem, scene)
        p.blk.translation = "ВИ\u00adДИТЕ? У НЕГО С ЭТИМ КА\u00adКИЕ-ТО..."

        logged = []
        monkeypatch.setattr(TC.LOGGER, "error", lambda msg, *a, **k: logged.append(msg))

        SceneTextManager.updateTranslation(_fake_stm(p))

        assert p.panel_text == "ВИДИТЕ? У НЕГО С ЭТИМ КАКИЕ-ТО..."
        assert p.item_clean == p.panel_text
        assert "\u00ad" not in p.panel_text
        assert any("[SYNC] I2" in m for m in logged), "грязная модель не попала в лог"
    finally:
        TC.set_strict(None)


# ── T9/T10: точки массовой перезаписи не пачкают панель ───────

def test_panel_clean_after_autolayout_undo_redo(scene):
    """T9 — L1: AutoLayoutCommand.redo/undo переливал hyphenated текст
    item в панель; дальше idempotence-guard гифенизации не срабатывал,
    и H «ехал» посреди сессии."""
    from ui.textedit_commands import AutoLayoutCommand

    p = _Pair(FlowTextBlkItem, scene)
    p.panel_edit(3, 6, "ЕШЬ")
    p.assert_in_sync("before auto-layout")

    old_html = [p.item.toHtml()]
    old_rect = [p.item.absBoundingRect(qrect=True)]
    cmd = AutoLayoutCommand([p.item], old_rect, old_html, [p.panel])

    cmd.redo()          # counter<=1 — состояние уже применено в __init__
    cmd.redo()
    assert "\u00ad" not in p.panel_text, f"в панель попали hyphens: {p.panel_text!r}"
    p.assert_in_sync("after AutoLayoutCommand.redo")

    cmd.undo()
    assert "\u00ad" not in p.panel_text, f"в панель попали hyphens: {p.panel_text!r}"
    p.assert_in_sync("after AutoLayoutCommand.undo")


def test_layout_textblk_keeps_panel_clean(scene):
    """T10 — L2: после auto-layout в панель летел текст item с U+00AD
    и жёсткими \n."""
    import numpy as np
    from ui.scenetext_manager import SceneTextManager

    p = _Pair(FlowTextBlkItem, scene)

    def _stub_layout(blkitem, text=None, mask=None, bounding_rect=None,
                     region_rect=None, img_array=None):
        # как настоящий layout: item получает новую расстановку строк
        layouted = "ВИДЕШЬ?\nУ НЕГО\nС ЭТИМ КАКИЕ-ТО..."
        blkitem.setPlainText(layouted)
        return blkitem.toPlainText()      # flow-item вернёт text С hyphens

    fake_self = SimpleNamespace(
        imgtrans_proj=SimpleNamespace(img_array=np.zeros((8, 8, 3), dtype=np.uint8)),
        layout_manager=SimpleNamespace(layout_textblk=_stub_layout),
        pairwidget_list=[SimpleNamespace(e_trans=p.panel)],
    )
    assert SceneTextManager.layout_textblk(fake_self, p.item, None) is True
    assert "\u00ad" not in p.panel_text, f"в панель попали hyphens: {p.panel_text!r}"
    p.assert_in_sync("after layout_textblk")
    assert p.panel_text == "ВИДЕШЬ?\nУ НЕГО\nС ЭТИМ КАКИЕ-ТО..."


# ── T12: search/replace (S1) ──────────────────────────

class _FakeSearchWidget:
    """Минимальный набор атрибутов PageSearchWidget, который реально
    читают PageReplaceAllCommand / PageReplaceOneCommand."""

    def __init__(self, panel, item, replace, matches=None, cursor=None):
        self.search_rstedit_list = [panel]
        self.highlighter_list = [
            SimpleNamespace(matched_map={i: Matched(i, s, e)
                                         for i, (s, e) in enumerate(matches or [])})]
        self.replace_editor = SimpleNamespace(toPlainText=lambda: replace)
        self.textblk_item_list = [item]
        self.current_edit = panel
        self.current_cursor = cursor
        self.counter_sum = len(matches or [])
        self.result_pos = 0
        self.update_cursor_on_insert = True

    def isVisible(self):
        return False


def test_search_replace_all_spans_land_correctly(scene):
    """T12a — матчи ищутся по панели (clean), а применялись к hyphenated
    документу item вербатим → «ЭТИМ» превращалось в «ЗАЧЕМИМ»."""
    from ui.textedit_commands import PageReplaceAllCommand
    import re

    p = _Pair(FlowTextBlkItem, scene)
    doc_before = p.doc
    assert TC.hyphen_count(doc_before) == 3

    # все 'И' в панели: clean 1, 3, 19, 25 — у первого и второго рядом hyphen
    matches = [(m.start(), m.end()) for m in re.finditer("И", p.panel_text)]
    assert len(matches) == 4
    sw = _FakeSearchWidget(p.panel, p.item, "Ы", matches)
    # panel_ref в команде снимается внутри — спаны в clean-координатах панели
    PageReplaceAllCommand(sw)

    expected = "ВЫДЫТЕ? У НЕГО С ЭТЫМ КАКЫЕ-ТО..."
    assert p.panel_text == expected
    assert p.item_clean == expected
    p.assert_in_sync("PageReplaceAllCommand")


def test_search_replace_one_span_lands_correctly(scene):
    """T12b — PageReplaceOneCommand: sel_start взят из панели, ori_len —
    длина clean-выделения, а применялись они к документу item."""
    from ui.textedit_commands import PageReplaceOneCommand
    from qtpy.QtGui import QTextCursor

    p = _Pair(FlowTextBlkItem, scene)
    cur = p.panel.textCursor()
    cur.setPosition(17)                                   # 'ЭТИМ' в clean-координатах
    cur.setPosition(21, QTextCursor.MoveMode.KeepAnchor)
    sw = _FakeSearchWidget(p.panel, p.item, "ЗАЧЕМ", cursor=cur)

    PageReplaceOneCommand(sw)

    expected = "ВИДИТЕ? У НЕГО С ЗАЧЕМ КАКИЕ-ТО..."
    assert p.panel_text == expected
    assert p.item_clean == expected
    p.assert_in_sync("PageReplaceOneCommand")


# ── T8-adj: как ведёт себя ОБЫЧНАЯ (не-STRICT) сборка ───────

def test_non_strict_run_reports_and_resyncs_from_panel(scene, monkeypatch):
    """Пользовательский запуск (BTRANS_STRICT_TEXT_SYNC выключен): любое
    рассогласование не тихое — лог `[SYNC] I1`, счётчик сессии и re-sync
    баллона по панели (источнику ввода). Проверка выполняется ВСЕГДА,
    флаг меняет только реакцию (§5.3)."""
    TC.set_strict(False)
    TC.reset_dedup()
    TC.reset_trip_counts()
    try:
        p = _Pair(FlowTextBlkItem, scene)
        # «сторонний писатель» испортил документ item (сценарий §1 плана)
        p.item.document().setPlainText("ВИ\u00adЕ\u00adШЬ У НЕГО ...")
        assert p.item_clean != p.panel_text

        logged = []
        monkeypatch.setattr(TC.LOGGER, "error", lambda msg, *a, **k: logged.append(msg))

        p.panel_edit(14, 30, "")                 # следующая правка в панели
        assert p.panel_text == "ВИДИТЕ? У НЕГО..."
        assert p.item_clean == p.panel_text, "re-sync по панели не восстановил баллон"
        assert any("[SYNC] I1" in m for m in logged), "рассогласование не попало в лог"
        assert TC.trip_counts().get("I1", 0) >= 1
    finally:
        TC.set_strict(None)


# ── T13: случайные последовательности правок ─────────────────

@pytest.mark.parametrize("seed", [12345, 987])
def test_random_edit_sequences_invariant(scene, seed):
    """T13 — любые неперечисленные источники дрейфа ловятся здесь:
    инвариант I1 проверяется после КАЖДОГО шага (в STRICT — падает на шаге,
    где проекции разъехались, с first-diff в сообщении)."""
    rnd = random.Random(seed)
    p = _Pair(FlowTextBlkItem, scene)

    for step in range(200):
        clean_len = TC.clean_len(p.doc)
        assert clean_len == len(p.panel_text)      # I1 перед правкой
        kind = rnd.random()
        if clean_len == 0:
            start = end = 0
            text = rnd.choice(["ВИД", "ТЕКСТ", "ОЧЕНЬ ДЛИННОЕ СЛОВО", "Ж"])
        elif kind < 0.4:                            # вставка
            start = end = rnd.randrange(0, clean_len)
            text = rnd.choice(["Ж", "ОЧЕНЬ", "СЛОВО", "\n", " — "])
        elif kind < 0.75:                           # удаление
            start = rnd.randrange(0, clean_len)
            end = min(clean_len, start + rnd.randint(1, 4))
            text = ""
        else:                                       # замена
            start = rnd.randrange(0, clean_len)
            end = min(clean_len, start + rnd.randint(1, 5))
            text = rnd.choice(["Ы", "КАКИЕ-ТО", "ДЕЛО", "—"])
        if rnd.random() < 0.25:
            p.item_edit(start, end, text)
        else:
            p.panel_edit(start, end, text)
        p.assert_in_sync(f"random step {step} ({start},{end})->{text!r}")

    assert "\u00ad" not in p.panel_text
