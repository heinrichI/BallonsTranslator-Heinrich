"""
text_sync — единственный владелец переноса правки между текстовыми
проекциями и единственный владелец массовой записи текста.

Два инварианта, которыми владеет этот модуль:

  I1  документ item без soft hyphens == текст панели
  I2/I3  в ``blk.translation`` и в панель перевода soft hyphens не попадают

Позиции при переносе правки всегда переводятся через CLEAN-пространство
(:mod:`ui.text_coords`), «removed» берётся из ``QTextDocument::contentsChange``,
а не из арифметики двух ``characterCount()`` (именно эта арифметика и
сломала текст в баллоне — bug1.txt, PLAN_panel_edit_propagation.md §1).
"""

import logging
from typing import Union

from qtpy.QtGui import QTextCursor

from . import text_coords as TC

LOGGER = logging.getLogger('BallonTranslator')


def doc_text(view) -> str:
    """Сырой текст документа view (QTextEdit / TextBlkItem / FlowTextBlkItem)."""
    return view.document().toPlainText()


def clean_text_of(view) -> str:
    """CLEAN-текст view (без U+00AD) — общая валюта проекций."""
    return TC.strip_hyphens(doc_text(view))


# ── единственная массовая запись текста ──────────────────────

def write_clean_text(view, text: str, *, where: str = '', keep_undo: bool = False,
                     check_hyphens: bool = False) -> str:
    """Записать текст в view (панель или item), гарантируя инвариант I3.

    Панель всегда получает CLEAN текст; hyphenated-документ (flow-item)
    гифенизует сам (``FlowTextBlkItem.setPlainText``), поэтому в него тоже
    льётся clean. Для item/panel это *штатная* конвертация (текст пришёл из
    hyphenated-документа), поэтому strip здесь молчаливый; подозрительные
    источники (значение из модели) проверяются через :func:`clean_text_value`.

    keep_undo=True — использовать ``setPlainTextAndKeepUndoStack`` (путь,
    который не сбрасывает undo-стек документа; важен для replay-undo).

    Возвращает текст, который реально был записан (clean-форма).
    """
    is_panel = not hasattr(view, 'blk')
    text = TC.strip_hyphens(text) if TC.SOFT_HYPHEN in (text or '') else text

    if keep_undo:
        view.setPlainTextAndKeepUndoStack(text)
    else:
        view.setPlainText(text)

    if is_panel:
        got = doc_text(view)
        if got != text:
            TC.check('I3 panel-accepted-clean-text', f"after write_clean_text {where}".strip(),
                     hint="панель не приняла clean-текст",
                     want=text, got=got)
    return text


def clean_text_value(text: str, *, where: str = '',
                     label: str = 'I2 model-is-clean') -> str:
    """Значение, которое ДОЛЖНО быть чистым (``blk.translation``, текст из
    проект-файла) — вернуть clean-версию и сообщить о грязном источнике.

    В отличие от write_clean_text, здесь наличие U+00AD нештатное: значит
    рассогласование уже записано в проект (§6)."""
    if TC.SOFT_HYPHEN in (text or ''):
        clean = TC.strip_hyphens(text)
        TC.check(label, where,
                 hint="soft hyphens в значении из модели — они уже осели в "
                      "проект-файле (blk.translation/rich_text), см. PLAN §6",
                 raw=text, clean=clean)
        return clean
    return text


def write_model_text(blk, text: str, *, where: str = '') -> str:
    """Единственная запись в ``blk.translation`` (инвариант I2)."""
    text = TC.strip_hyphens(text) if TC.SOFT_HYPHEN in (text or '') else text
    blk.translation = text
    return text


# ── единственная точка переноса правки ───────────────────────

def _write_into(view, start: int, end: int, text: str, joint_previous: bool):
    cursor = view.textCursor()
    cursor.setPosition(start)
    if joint_previous:
        cursor.joinPreviousEditBlock()
    else:
        cursor.beginEditBlock()
    if end > start:
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(text)
    cursor.endEditBlock()
    view.old_undo_steps = view.document().availableUndoSteps()


def apply_edit(src, dst, pos: int, added_text: str, joint_previous: bool = False,
               removed: int = None, *, where: str = '') -> bool:
    """Перенести одну пользовательскую правку из ``src`` (где её набрали)
    в ``dst`` (зеркало).

    ``pos`` — offset в пространстве ДОКУМЕНТА src, где началась правка.
    ``removed`` — точное число удалённых символов из
    ``QTextDocument::contentsChange``; принимается для совместимости и
    диагностики, но диапазон считается в CLEAN-пространстве, поэтому
    hyphens в нём не нужны.

    Важная деталь: ``contentsChange`` эмитится ПОСЛЕ изменения источника,
    поэтому текст src здесь уже «после» правки, а текст dst — ещё «до».
    Префикс src[:pos] при правке не меняется (гарантия Qt), поэтому
    clean-позиция съёма берётся из src, а вот длина удаления и doc-
    диапазон — из собственного текста dst (он и есть целевое
    пространство). Раньше и то, и другое брали как сырые int из
    арифметики characterCount() двух разных документов (bug1.txt).

    Возвращает True, если после правки проекции согласованы.
    """
    src_post = doc_text(src)
    dst_pre = doc_text(dst)
    added = TC.normalize_edit_text(added_text)

    c_src_post = TC.clean_len(src_post)
    c_dst_pre = TC.clean_len(dst_pre)
    c_added = TC.clean_len(added)

    clean_start = min(TC.clean_offset(src_post, pos), c_dst_pre)
    # c_src_post == c_dst_pre - clean_removed + c_added  (следствие I1 до правки)
    clean_removed = max(0, c_dst_pre + c_added - c_src_post)
    if removed is not None and removed >= 0 and TC.hyphen_count(src_post) == 0 \
            and removed != clean_removed:
        # Источник чистый → clean_removed обязан совпасть с тем, что сообщил
        # Qt. Расхождение значит, что проекции разъехались ДО этой правки
        # (текст записал сторонний писатель); чинить позиционно нельзя —
        # это заметный сигнал, его подхватит verify_sync ниже.
        TC.warn_once('I4 removed-vs-clean', where, key=(removed, clean_removed),
                     hint=f"contentsChange removed={removed}, "
                          f"clean_removed={clean_removed} — проекции "
                          f"разошлись ДО этой правки",
                     **_side_labels(src, dst))
    if clean_start + clean_removed > c_dst_pre:
        if removed is not None and removed >= 0 and TC.strict_enabled():
            raise TC.TextSyncError(
                TC.describe_desync('I1 panel<->item', f"{where} (pre-edit drift)",
                                   raised=True,
                                   hint='проекции разошлись ДО правки — источник '
                                        'изменил кто-то ещё, диапазон удаления '
                                        'не выводим',
                                   src_clean=TC.strip_hyphens(src_post),
                                   dst_clean=TC.strip_hyphens(dst_pre)))
        clean_removed = c_dst_pre - clean_start

    start = TC.doc_start_for_clean(dst_pre, clean_start)
    end = TC.doc_end_for_clean(dst_pre, clean_start + clean_removed)
    end = max(end, start)

    _write_into(dst, start, end, added, joint_previous)

    blocks_diverged = src.document().blockCount() != dst.document().blockCount()
    return verify_sync(src, dst, where=where, blocks_diverged=blocks_diverged)


def verify_sync(src, dst, *, where: str = '', blocks_diverged: bool = False) -> bool:
    """Инвариант I1 (+I4): проекции после операции совпадают в clean-виде.

    При расхождении текст НЕ «чинится» позиционно — делается полный
    re-sync по источнику ввода (``src``), и событие попадает в лог.
    В STRICT (тесты/dev) вместо re-sync'а бросается TextSyncError.
    """
    src_clean = clean_text_of(src)
    dst_clean = clean_text_of(dst)

    item_view, panel_view = (src, dst) if hasattr(src, 'blk') else (dst, src)
    extra = (f"item doc: len={len(doc_text(item_view))} "
             f"H={TC.hyphen_count(doc_text(item_view))} "
             f"blocks(item)={item_view.document().blockCount()} "
             f"blocks(panel)={panel_view.document().blockCount()}")

    if src_clean == dst_clean:
        # clean-тексты равны, но число QTextBlock разное → позиции
        # переводятся неверно (C2). В не-STRICT это тоже НЕ тихо.
        if blocks_diverged:
            TC.warn_once('I4 block-count', where, key=where,
                         hint='число QTextBlock у панели и item различное — '
                              'следующая правка может леч не туда. ' + extra,
                         **_side_labels(src, dst))
            if TC.strict_enabled():
                raise TC.TextSyncError(
                    TC.describe_desync('I4 block-count', where, raised=True,
                                       hint=extra, **_side_labels(src, dst)))
        return True

    hint = ('позиция/removed применены в разных координатных пространствах '
            'или текст записал сторонний писатель — выполняется re-sync по '
            'источнику ввода. ' + extra)
    # TC.check: в STRICT — TextSyncError, иначе лог (один раз на пару
    # label/позиция) + счётчик сессии. Проверка выполняется ВСЕГДА.
    TC.check('I1 panel<->item', where, hint=hint, **_side_labels(src, dst))
    resync(dst, src_clean)
    return False


def _side_labels(src, dst) -> dict:
    """Подписать стороны сообщения по ролям, а не по порядку аргументов:
    пользователь/тест должен видеть panel/item, а не src/dst."""
    src_item, dst_item = hasattr(src, 'blk'), hasattr(dst, 'blk')
    if src_item == dst_item:
        src_name, dst_name = 'src', 'dst'
    else:
        src_name, dst_name = ('item', 'panel') if src_item else ('panel', 'item')
    return {f"{src_name}_clean": clean_text_of(src),
            f"{dst_name}_clean": clean_text_of(dst)}


def resync(dst, clean_text: str):
    """Полная перезапись текста проекта (последняя линия защиты).

    Только clean-текст; гифенизацию делает сам hyphenated-документ."""
    write_clean_text(dst, clean_text, where='resync', keep_undo=True)


def check_sync(view, panel, *, where: str = '') -> bool:
    """Тот же I1, но без правки — для точек фокуса/сохранения (I7)."""
    return verify_sync(panel, view, where=where)


# ── search/replace: спаны из панели/модели → документ item (S1) ───

def map_spans_to_doc(clean_ref: str, doc_text: str, spans) -> list:
    """Спаны в координатах CLEAN-текста → спаны в hyphenated-документе.

    Матчи всегда ищутся по панели/``blk.translation`` (clean), а применяются
    к документу item (flow — с U+00AD). Вербатимные спаны там попадать не
    могут: это тот же index-space баг, что и в propagate (PLAN §2.1).

    *clean_ref* нормализуется (hyphens из него выбрасываются), поэтому
    спан-координаты всегда трактуются как CLEAN-индексы — даже если
    вызывающий код передал hyphenated-текст."""
    clean_ref = TC.strip_hyphens(clean_ref)
    out = []
    for span in spans:
        start, end = span[0], span[1]
        cs = TC.clean_offset(clean_ref, start)
        ce = TC.clean_offset(clean_ref, end)
        ds = TC.doc_start_for_clean(doc_text, cs)
        de = TC.doc_end_for_clean(doc_text, ce)
        if de < ds:
            de = ds
        out.append((ds, de))
    return out


def replace_spans_in_doc(doc, clean_ref: str, spans, target: str) -> list:
    """Заменить ``spans`` (координаты CLEAN-текста) внутри ``QTextDocument``.

    Замены идут справа налево, поэтому позиции более ранних спанов не
    съезжают, и всё завёрнуто в один edit-block — ровно один шаг undo
    (важно для replay-undo: ``edit.undo()`` + ``item.undo()``, PLAN §2.2).
    """
    target = TC.normalize_edit_text(target)
    doc_text = doc.toPlainText()
    mapped = sorted(map_spans_to_doc(clean_ref, doc_text, spans), reverse=True)
    cursor = QTextCursor(doc)
    cursor.beginEditBlock()
    for start, end in mapped:
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(target)
    cursor.endEditBlock()
    return mapped
