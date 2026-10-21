"""
Юниты чистых мапперов clean↔document и диагностики (T11/T14 из
PLAN_panel_edit_propagation.md §4.2).

Без QApplication: ui/text_coords.py сознательно не импортирует qtpy,
поэтому регрессии маппинга проверяются дёшево и без offscreen-платформы.
"""

import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from ui import text_coords as TC

# «ВИДИТЕ? У НЕГО С ЭТИМ КАКИЕ-ТО...» с soft hyphens, как их ставит
# _hyphenate_text (pyphen ru_RU): ВИ\xadДИ\xadТЕ? ... КА\xadКИЕ-ТО
DOC = "ВИ\u00adДИ\u00adТЕ? У НЕГО С ЭТИМ КА\u00adКИЕ-ТО..."
CLEAN = "ВИДИТЕ? У НЕГО С ЭТИМ КАКИЕ-ТО..."


# ── модуль не должен зависеть от Qt ─────────────────────────

def test_text_coords_has_no_qt_import():
    """Маппинг обязан оставаться доступным без QApplication (§4.3)."""
    src = open(os.path.join(ROOT, "ui", "text_coords.py"), encoding="utf-8").read()
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert "qtpy" not in mods and "PyQt6" not in mods and "PyQt5" not in mods


# ── базовые счётчики ─────────────────────────────────────────

def test_hyphen_counts():
    assert TC.hyphen_count(DOC) == 3
    assert TC.hyphen_count(CLEAN) == 0
    assert TC.strip_hyphens(DOC) == CLEAN
    assert TC.clean_len(DOC) == len(CLEAN)


def test_hyphen_positions():
    assert TC.hyphen_spans(DOC) == [2, 5, 26]


# ── clean_offset: позиция → число видимых символов ───────────

@pytest.mark.parametrize("doc", [DOC, CLEAN])
def test_clean_offset_is_prefix_only(doc):
    """Гарантия Qt: текст левее позиции правки не меняется, поэтому
    clean_offset считается по префиксу и не зависит от того, что правее."""
    for pos in range(0, len(doc) + 1):
        assert TC.clean_offset(doc, pos) == len(TC.strip_hyphens(doc[:pos]))


def test_clean_offset_clamps_and_ignores_hyphens():
    assert TC.clean_offset(DOC, -5) == 0
    assert TC.clean_offset(DOC, 10_000) == TC.clean_len(DOC)
    # hyphen «приклеен» к предыдущему символу: обе позиции дают один clean-offset
    assert TC.clean_offset(DOC, 2) == TC.clean_offset(DOC, 3) == 2


# ── doc_start / doc_end ──────────────────────────────────────

def test_doc_start_for_clean_skips_hyphens_forward():
    # clean 'И' (index 1) → doc index 1
    assert TC.doc_start_for_clean(DOC, 1) == 1
    # clean 'Д' (index 2) стоит за hyphen: doc index 3
    assert TC.doc_start_for_clean(DOC, 2) == 3
    # вставка после clean-позиции 2 (после 'Д') — за hyphen, а не перед 'И'
    assert TC.doc_start_for_clean(DOC, 3) == 4
    assert TC.doc_start_for_clean(DOC, 0) == 0
    assert TC.doc_start_for_clean(DOC, TC.clean_len(DOC)) == len(DOC)


def test_doc_end_for_clean_does_not_absorb_trailing_hyphen():
    assert TC.doc_end_for_clean(DOC, 2) == 2          # 'ВИ' — hyphen на 2 НЕ входит
    assert TC.doc_start_for_clean(DOC, 2) == 3        # а старт после 'ВИ' — за hyphen
    assert TC.doc_end_for_clean(DOC, 3) == 4          # 'ВИД' (hyphen внутри спана)
    # 'КА\xadКИЕ': hyphen внутри диапазона поглощается, на границе — нет
    assert TC.doc_end_for_clean(DOC, 24) == 26
    assert TC.doc_start_for_clean(DOC, 24) == 27
    assert TC.doc_end_for_clean(DOC, 26) == 29
    assert TC.doc_end_for_clean(DOC, 28) == 31


def test_delete_range_covers_interior_hyphens():
    """Удаление 'ИТЕ' (clean 3..6) должно вырезать 'И\\xadТЕ' целиком."""
    start = TC.doc_start_for_clean(DOC, 3)
    end = TC.doc_end_for_clean(DOC, 6)
    assert DOC[start:end] == "И\u00adТЕ"


def test_replacement_span_roundtrip():
    """Любой clean-спан, вырезанный через start/end, остаётся clean-спаном."""
    for s in range(TC.clean_len(CLEAN)):
        for e in range(s, TC.clean_len(CLEAN) + 1):
            ds = TC.doc_start_for_clean(DOC, s)
            de = TC.doc_end_for_clean(DOC, e)
            assert TC.strip_hyphens(DOC[ds:de]) == CLEAN[s:e]


# ── map_pos / map_range: обе стороны, все комбинации ────────

@pytest.mark.parametrize("src,dst", [
    (CLEAN, DOC),      # панель → hyphenated документ item
    (DOC, CLEAN),      # hyphenated документ item → панель
    (DOC, DOC),        # legacy: панель ещё держит hyphens
    (CLEAN, CLEAN),    # обычный TextBlkItem
])
def test_map_pos_roundtrip_on_same_clean_offsets(src, dst):
    for cpos in range(TC.clean_len(CLEAN) + 1):
        pos = TC.doc_start_for_clean(src, cpos)
        mapped = TC.map_pos(src, dst, pos)
        assert mapped == TC.doc_start_for_clean(dst, cpos)


def test_map_range_monotonic_and_bounded():
    prev = 0
    for s in range(0, TC.clean_len(CLEAN), 3):
        e = min(s + 5, TC.clean_len(CLEAN))
        ds, de = TC.map_range(CLEAN, DOC, s, e)
        assert 0 <= ds <= de <= len(DOC)
        assert ds >= prev
        prev = ds
        assert DOC[ds:de].replace("\u00ad", "") == CLEAN[s:e]


def test_map_pos_clamps_to_target_length():
    """Источник длиннее цели (правка уже применена к источнику) — не вываливаться."""
    assert TC.map_pos(CLEAN + "ххххх", CLEAN, 10_000) == len(CLEAN)


# ── нормализация added_text (U+2028 из selectedText) ─────────

def test_normalize_edit_text():
    assert TC.normalize_edit_text("a\u2028b\u2029c") == "a\nb\nc"
    assert TC.normalize_edit_text("КА\u00adКИЕ") == "КАКИЕ"
    assert TC.normalize_edit_text("") == ""


def test_block_count_matches_qt_semantics():
    assert TC.block_count("abc") == 1
    assert TC.block_count("a\nb") == 2
    assert TC.block_count("a\n") == 2
    assert TC.block_count("") == 1


# ── диагностика рассогласования ──────────────────────────────

def test_first_diff_reports_index_and_windows():
    idx, wa, wb = TC.first_diff("ВИДЕШЬ? У НЕГО", "ВИЕШЬ У НЕГО")
    assert idx == 2
    assert "\\xad" not in wa            # обычная печать, не soft hyphen
    assert "Д" in wa and "Е" in wb


def test_first_diff_on_prefix_difference():
    idx, _, _ = TC.first_diff("abc", "abcdef")
    assert idx == 3


def test_describe_desync_reports_all_sides_and_first_diff():
    msg = TC.describe_desync("I1 panel<->item", "after apply_edit",
                             panel="ВИДЕШЬ? У НЕГО",
                             item_clean="ВИЕШЬ У НЕГО")
    assert msg.startswith("[SYNC] I1 panel<->item MISMATCH after apply_edit")
    assert "first diff @2" in msg
    assert "panel" in msg and "item_clean" in msg
    assert "H=0" in msg and "blocks=1" in msg


def test_check_passes_on_equal_sides():
    assert TC.check("I2 model-is-clean", "test", a="abc", b="abc") is True


def test_invariant_violation_raises_in_strict_mode():
    TC.set_strict(True)
    try:
        with pytest.raises(TC.TextSyncError) as ei:
            TC.check("I1 panel<->item", "unit", panel="x", item_clean="y")
        assert "[SYNC] I1 panel<->item RAISED unit" in str(ei.value)
    finally:
        TC.set_strict(None)


def test_non_strict_check_logs_once_and_returns_false(monkeypatch):
    """не-STRICT: расхождение уходит в лог ОДИН раз на (label, индекс).
    Логгер приложения (utils/logger.py) не прозрачен для caplog, поэтому
    ставим свой обработчик."""
    TC.set_strict(False)
    seen = []
    monkeypatch.setattr(TC.LOGGER, "error",
                        lambda msg, *a, **k: seen.append(msg))
    try:
        assert TC.check("I1 dedup-test", "unit", a="x", b="y") is False
        assert TC.check("I1 dedup-test", "unit2", a="x", b="y") is False
        assert len(seen) == 1, "одинаковое расхождение не должно логироваться дважды"
        assert "[SYNC] I1 dedup-test MISMATCH" in seen[0]
        assert TC.check("I9 dedup-other", "unit3", a="x", b="z") is False
        assert len(seen) == 2, "другая пара (label, индекс) логируется отдельно"
    finally:
        TC.set_strict(None)


def test_env_var_enables_strict(monkeypatch):
    TC.set_strict(None)
    monkeypatch.setenv("BTRANS_STRICT_TEXT_SYNC", "1")
    assert TC.strict_enabled() is True
    monkeypatch.setenv("BTRANS_STRICT_TEXT_SYNC", "0")
    assert TC.strict_enabled() is False


# ── единый страж «панель и item говорят об одном тексте» (I8) ─

def test_texts_match_raw_clean_and_mismatch():
    ok, why = TC.texts_match(DOC, DOC)
    assert ok and why == "raw"
    ok, why = TC.texts_match(DOC, CLEAN)
    assert ok and why == "clean"
    ok, why = TC.texts_match(DOC, CLEAN.replace("ВИД", "ВИЕ"))
    assert not ok and "first diff @2" in why


# ── реакция обычной сборки: видно, но без спама (I4/счётчик) ──

def test_strict_mode_never_trips_on_clean_sides():
    """Согласованные проекции не дают ни исключения, ни срабатываний."""
    TC.set_strict(True)
    TC.reset_trip_counts()
    try:
        # стороны сравниваются как есть: clean-проекцию считает verify_sync
        assert TC.check("I1 panel<->item", "x", item=CLEAN, panel=CLEAN) is True
    finally:
        TC.set_strict(None)
    assert TC.trip_counts() == {}


def test_trip_counter_counts_every_detection():
    TC.set_strict(False)
    TC.reset_trip_counts()
    try:
        for _ in range(3):
            TC.check("I1 panel<->item", "x", item="abc", panel="abd")
    finally:
        TC.set_strict(None)
    assert TC.trip_counts()["I1"] == 3


def test_warn_once_is_visible_but_not_spam(monkeypatch):
    """Не-ассертные события (blockCount разошёлся при равных clean-текстах)
    видны в логе, но не печатаются на каждый keystroke.

    LOGGER читается напрямую (не через caplog): app-логгер BallonTranslator
    имеет propagate=False (utils/logger.py), поэтому caplog его не видит."""
    TC.reset_dedup()
    TC.reset_trip_counts()
    logged = []
    monkeypatch.setattr(TC.LOGGER, "warning",
                        lambda msg, *a, **k: logged.append(str(msg)))
    for _ in range(4):
        TC.warn_once("I4 block-count", "blk idx=0", key="blk idx=0",
                     hint="blocks item=2 panel=1",
                     panel_clean="ab", item_clean="ab")
    assert TC.trip_counts()["I4"] == 4
    assert len(logged) == 1
    assert "NOTICE" in logged[0] and "blocks item=2" in logged[0]
