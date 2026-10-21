"""
text_coords — единственное владение двумя координатными пространствами текста.

В BallonsTranslator один и тот же текст блока живёт (как минимум) в трёх
проекциях:

    панель перевода (TransTextEdit, всегда CLEAN)
    документ item  (TextBlkItem — clean; FlowTextBlkItem — clean + U+00AD)
    модель         (blk.translation / blk.rich_text, всегда CLEAN)

`FlowTextBlkItem` вставляет в документ soft hyphens (U+00AD), поэтому
номер символа в документе item ≠ номер символа в панели/модели. Любая
операция, которой передают «сырой» int из чужого пространства (позиция
правки, спан search/replace, диапазон обводки), порсит текст тихо.

Здесь лежат чистые строковые функции перевода между пространствами и
общая диагностика рассогласования (`TextSyncError`, `check`,
`describe_desync`). Модуль сознательно НЕ импортирует qtpy — маппинг
должен быть тестируемы без QApplication и доступен из команд, виджетов и
пайплайна (см. PLAN_panel_edit_propagation.md §7).
"""

import logging
import os
import re

LOGGER = logging.getLogger('BallonTranslator')

SOFT_HYPHEN = '\u00ad'
#: Qt возвращает U+2028 (а не '\n') из QTextCursor::selectedText() для границ
#: блоков; обратно в документ надо отдавать именно '\n'.
QT_LINE_SEP = '\u2028'
PARAGRAPH_SEP = '\u2029'

_TAG_RE = re.compile(r'<[a-zA-Z/!][^>]*>')


# ── базовые вещи над текстом ─────────────────────────────────

def strip_hyphens(text: str) -> str:
    """CLEAN-вид текста (без soft hyphens)."""
    if not text:
        return ''
    return text.replace(SOFT_HYPHEN, '')


def hyphen_count(text: str) -> int:
    """H — число soft hyphens в тексте (величина «дефицита» индексов)."""
    if not text:
        return 0
    return text.count(SOFT_HYPHEN)


def clean_len(text: str) -> int:
    """Число видимых (не hyphen) символов."""
    return len(text) - hyphen_count(text)


def block_count(text: str) -> int:
    """Число QTextBlock'ов, как его считает Qt (каждый '\n'terminates блок).

    Не путать с ``text.count('\\n') + 1``: для текста, оканчивающегося
    переводом строки, Qt даёт на один блок больше (это и есть источник
    расхождения blockCount у панели и item, см. PLAN §2 C2)."""
    return text.count('\n') + 1


def normalize_edit_text(text: str) -> str:
    """Привести ``added_text`` из Qt-колбэка к виду, пригодному для записи
    в любой из документов: без soft hyphens и с нормальными переводами
    строк вместо U+2028/U+2029."""
    if not text:
        return ''
    if QT_LINE_SEP in text or PARAGRAPH_SEP in text:
        text = text.replace(QT_LINE_SEP, '\n').replace(PARAGRAPH_SEP, '\n')
    return text.replace(SOFT_HYPHEN, '')


# ── перевод позиций (clean ↔ document) ───────────────────────

def clean_offset(text: str, pos: int) -> int:
    """Позиция *pos* в тексте *text* → число видимых символов перед ней.

    Работает в обе стороны одинаково: для CLEAN-текста это просто pos,
    для hyphenated (документ flow-item) — pos минус hyphens левее.
    Гиперсимволы считаются «приклеенными» к предыдущему видимому
    символу, поэтому позиция сразу после hyphen даёт тот же clean-offset,
    что и позиция перед ним."""
    if not text:
        return 0
    pos = max(0, min(int(pos), len(text)))
    return sum(1 for ch in text[:pos] if ch != SOFT_HYPHEN)


def doc_start_for_clean(doc_text: str, cpos: int) -> int:
    """Документный offset, на котором начинается *cpos*-й видимый символ.

    Hyphens, стоящие сразу после последнего пропущенного видимого символа,
    ПРОПУСКАЮТСЯ — вставка после буквы должна попадать за hyphen, а не
    перед ним (иначе hyphen уезжает в начало следующего слова)."""
    cpos = max(0, int(cpos))
    clean = i = 0
    n = len(doc_text)
    while i < n and clean < cpos:
        if doc_text[i] != SOFT_HYPHEN:
            clean += 1
        i += 1
    while i < n and doc_text[i] == SOFT_HYPHEN:
        i += 1
    return i


def doc_end_for_clean(doc_text: str, cpos: int) -> int:
    """Исключающий документный offset, покрывающий *cpos* видимых символов.

    В отличие от :func:`doc_start_for_clean` hyphens ПОСЛЕ последнего
    включённого видимого символа не поглощаются — они относятся к
    следующему слову. Разница между ``doc_end_for_clean(d, k+j)`` и
    ``doc_start_for_clean(d, k)`` = диапазон удаления j видимых символов
    вместе с hyphens внутри него."""
    cpos = max(0, int(cpos))
    clean = i = 0
    n = len(doc_text)
    while i < n and clean < cpos:
        if doc_text[i] != SOFT_HYPHEN:
            clean += 1
        i += 1
    return i


def map_pos(src_text: str, dst_text: str, pos: int, end: bool = False) -> int:
    """Offset *pos* из пространства *src_text* → offset в *dst_text*.

    Перевод идёт через CLEAN-пространство, поэтому одинаково корректен
    для всех комбинаций: clean→hyphenated, hyphenated→clean,
    clean→clean и hyphenated→hyphenated (в т.ч. legacy-панели, которые
    ещё держат hyphens до перезагрузки страницы).

    *end=True* — переводится правая (исключающая) граница диапазона.
    """
    cpos = clean_offset(src_text, pos)
    cpos = min(cpos, clean_len(dst_text))
    return doc_end_for_clean(dst_text, cpos) if end \
        else doc_start_for_clean(dst_text, cpos)


def map_range(src_text: str, dst_text: str, start: int, end: int):
    """Диапазон из *src_text* → диапазон в *dst_text* (start inclusive, end exclusive)."""
    s = map_pos(src_text, dst_text, start, end=False)
    e = map_pos(src_text, dst_text, end, end=True)
    if e < s:
        e = s
    return s, e


def hyphen_spans(text: str):
    """Позиции soft hyphens в тексте (для логов и диагностики)."""
    return [i for i, ch in enumerate(text) if ch == SOFT_HYPHEN]


# ── диагностика рассогласования ──────────────────────────────

class TextSyncError(RuntimeError):
    """Рассогласование текстовых проекций (панель / документ item / blk.translation)."""


_STRICT_OVERRIDE = None
_WARNED = set()
_TRIPS = {}          # label -> сколько раз рассогласование возникло за сессию


def trip_counts():
    """Счётчик срабатываний инвариантов за сессию (для UI/статус-бара)."""
    return dict(_TRIPS)


def reset_trip_counts():
    _TRIPS.clear()


def reset_dedup():
    """Забыть, какие рассогласования уже были залогированы (для тестов)."""
    _WARNED.clear()


def _note_trip(label: str) -> int:
    key = label.split()[0] if label else label
    _TRIPS[key] = _TRIPS.get(key, 0) + 1
    return _TRIPS[key]


def set_strict(value):
    """Явное включение/выключение строгого режима (тесты). None — сброс."""
    global _STRICT_OVERRIDE
    _STRICT_OVERRIDE = value
    _WARNED.clear()


def strict_enabled() -> bool:
    """STRICT = бросать TextSyncError вместо лога и re-sync'а.

    По умолчанию выключен (пользовательский GUI не роняем). Включается
    переменной окружения ``BTRANS_STRICT_TEXT_SYNC`` (dev/тесты).
    Сама ПРОВЕРКА выполняется всегда — флаг меняет только реакцию."""
    if _STRICT_OVERRIDE is not None:
        return bool(_STRICT_OVERRIDE)
    flag = os.environ.get('BTRANS_STRICT_TEXT_SYNC', '')
    return flag not in ('', '0', 'false', 'False', 'no')


def _visual(text: str) -> str:
    return (text.replace(SOFT_HYPHEN, '\\xad')
                .replace(QT_LINE_SEP, '\u2407')
                .replace('\n', '\u2407'))


def first_diff(a: str, b: str, window: int = 12):
    """(индекс первого расхождения, окно из a, окно из b).

    Если одна строка — префикс другой, индекс = len(более короткой)."""
    n = min(len(a), len(b))
    idx = 0
    while idx < n and a[idx] == b[idx]:
        idx += 1
    if idx >= n and len(a) != len(b):
        pass  # индекс = длина общей префиксной части
    lo, hi = max(0, idx - window // 2), idx + window
    return idx, _visual(a[lo:hi]), _visual(b[lo:hi])


def describe_desync(label: str, where: str, *, raised: bool = False,
                    tag: str = '', hint: str = '', **sides: str) -> str:
    """Собрать сообщение о рассогласовании для ЛЮБОГО числа сторон.

    Один и тот же текст видит и пользователь в логе, и pytest — чтобы
    провал теста выглядел ровно как падение в GUI (PLAN §5.1).
    ``tag`` — заголовок (MISMATCH / RAISED / NOTICE); по умолчанию
    берётся из ``raised``."""
    name_w = max([len(k) for k in sides] + [4])
    word = tag or ('RAISED' if raised else 'MISMATCH')
    lines = [f"[SYNC] {label} {word} {where}"]
    for k, v in sides.items():
        lines.append(f"  {k:<{name_w}} len={len(v):<4} : {_visual(v)!r}")

    names = list(sides)
    base = sides[names[0]]
    for other in names[1:]:
        if sides[other] == base:
            continue
        idx, wa, wb = first_diff(base, sides[other])
        lines.append(
            f"  first diff @{idx}: {names[0]}={wa!r} {other}={wb!r}")
        break

    infos = []
    for k, v in sides.items():
        h = hyphen_count(v)
        infos.append(f"{k}: len={len(v)} H={h} blocks={block_count(v)}")
    lines.append("  " + "  ".join(infos))
    if hint:
        lines.append(f"  hint: {hint}")
    return "\n".join(lines)


def check(label: str, where: str, *, hint: str = '', **sides: str) -> bool:
    """True, если все переданные стороны равны.

    Иначе — :class:`TextSyncError` в STRICT, либо однократный
    ``LOGGER.error`` на пару (label, индекс) за сессию. Проверяется
    ВСЕГДА, выключить саму проверку нельзя (§5.3)."""
    values = list(sides.values())
    if all(v == values[0] for v in values):
        return True
    names = list(sides)
    key = None
    for i in range(1, len(values)):
        if values[i] != values[0]:
            key, _, _ = first_diff(values[0], values[i])
            break
    dedup = (label, key)
    raised = strict_enabled()
    msg = describe_desync(label, where, raised=raised, hint=hint, **sides)
    if raised:
        raise TextSyncError(msg)
    n = _note_trip(label)
    if dedup not in _WARNED:
        _WARNED.add(dedup)
        LOGGER.error(f"{msg}  (за сессию по этому инварианту: {n})")
    return False


def warn_once(label: str, where: str, *, key=None, hint: str = '',
              **sides: str) -> str:
    """Не-ассертное, но НЕ тихое событие: расхождение заметно, но чинить
    его не нужно (например blockCount разный, а clean-тексты равны).

    Логируется один раз на (label, key), счётчик сессии растёт всегда."""
    n = _note_trip(label)
    msg = describe_desync(label, where, tag='NOTICE', hint=hint, **sides)
    dedup = (label, key)
    if dedup not in _WARNED:
        _WARNED.add(dedup)
        LOGGER.warning(f"{msg}  (за сессию по этому инварианту: {n})")
    return msg


def texts_match(item_text: str, panel_text: str):
    """Единый страж «текст item и текст панели описывают одно и то же»
    (сводит вместе две прежние копии правила — textitem.py:1132 и :1800).

    Возвращает (ok, reason). Совпадение допускается и в raw-виде, и в
    clean-виде: панель до перезагрузки страницы может ещё держать
    legacy-hyphens, а item — чистый текст не-flow-блока."""
    if item_text == panel_text:
        return True, 'raw'
    if strip_hyphens(item_text) == strip_hyphens(panel_text):
        return True, 'clean'
    idx, wi, wp = first_diff(item_text, panel_text)
    return False, (f"first diff @{idx}: item={wi!r} panel={wp!r} "
                   f"(item H={hyphen_count(item_text)}, panel H={hyphen_count(panel_text)})")
