# -*- coding: utf-8 -*-
"""
Регрессия: нижняя часть последней строки в flow-блоках обрезается клипом.

Корни (PLAN_FLOW_BOTTOM_CLIP_FIX.md):
  A. `shrink_height` меряет базовую строку `'木fg'`, а не реальный ink-extent
     — в большинстве шрифтов реальные глифы уходят на 1–17px ниже базы,
     и после авторазмера ink последней строки уходит ниже нижней
     ограничивающей линии; `boundingRect().bottom()` клипит его.
  B. `grow()` делает шаг увеличения и `break`-ится, оставляя шрифт,
     при котором текст в переполнении (S > target) — немоноотонный reflow.
  C. Display-rect не позиционируется за текстом: при отрицательном
     `min_y` (верхний CP выше начала блока) rect дегенерирует
     (height = S + 2*min_y) и не накрывает текст.

Красные кейсы зафиксированы свипом `_sweep_clip.py` (все шрифты fonts/
зарегистрированы, offscreen):

    A.C.M.E            +г  S=290.0 > 260  (font 33.3)
    BOMGcom004         +д  S=266.8 > 260  (font 36.0)
    BOMGcomPsuedoSaudi +г  S=359.6 > 260  (font 49.0)
    v_Blambot Casual MOD+щ S=276.0 > 260  (font 42.0)
    BOMGcomPsuedoSaudi (латиница, fallback) ink=270 > br=266.8  [CLIP-ink]

После фикса (3.1 ink-метрика + 3.7 grow-откат + 3.2 display-rect) все тесты
зелёные.

Run with:
    set QT_QPA_PLATFORM=offscreen
    myenv\\Scripts\\python.exe -m pytest tests/ui/test_flow_resize_bottom_clip.py -v
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import numpy as np

from qtpy.QtCore import QRectF, QPointF
from qtpy.QtGui import QImage, QPainter, QFontDatabase
from qtpy.QtWidgets import QApplication  # noqa: F401 (qapp fixture)

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.misc import pixmap2ndarray
from ui.scene_textlayout import VERTICAL_CENTER

# ── Фикстура: только нужные шрифты репо ─────────────────────
# addApplicationFont необратим в рамках процесса: регистрируем минимум
# файлов (4 семейства из тест-кейсов), чтобы не смещать глобальный
# fallback-решивинг порядка-чувствительных тестов (QFontDatabase общий).
_REQUIRED_FONT_FILES = {
    "BOMGcomPsuedoSaudi": os.path.join(ROOT, "fonts", "BOMGcomPseudoSaudi.ttf"),
    "BOMGcom004": os.path.join(ROOT, "fonts", "BOMGcom004.ttf"),
    "v_Blambot Casual MOD": os.path.join(ROOT, "fonts", "v_Blambot Casual_v1.01MOD.ttf"),
    "A.C.M.E": os.path.join(ROOT, "fonts", "ACMEBold.ttf"),
}


@pytest.fixture(scope="module", autouse=True)
def repo_fonts(qapp):  # noqa: F811 (fixture из tests/ui/conftest.py)
    before = set(QFontDatabase.families())
    for path in _REQUIRED_FONT_FILES.values():
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    available = set(QFontDatabase.families())
    yield available


def _require_family(repo_fonts, family):
    if family not in repo_fonts:
        pytest.skip(f"family {family!r} not available in this environment")


# ── Хелперы ────────────────────────────────────────────────────

def _make_blk(xyxy, text, font_size, family):
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = family
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_item(scene, xyxy=(0, 0, 500, 260), text="", font_size=40.0, family="Arial"):
    item = FlowTextBlkItem(_make_blk(xyxy, text, font_size, family),
                           idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _cp_target_height(item):
    all_pts = item._left_points + item._right_points
    ys = [p.y() for p in all_pts]
    return max(ys) - min(ys)


def _set_cp_vertical(item, top_y, bottom_y):
    """Заменить CP-сетку: верх=top_y, низ=bottom_y (x-координаты сохранены)."""
    for pts in (item._left_points, item._right_points):
        n = len(pts)
        for i in range(n):
            y = top_y + (bottom_y - top_y) * i / max(n - 1, 1)
            pts[i] = QPointF(pts[i].x(), y)


def ink_bottom_doc(item, pad=40):
    """Дно реального ink-рендера документа в координатах документа."""
    doc = item.document()
    w = int(doc.size().width()) + pad
    h = int(doc.size().height()) + pad
    img = QImage(w + pad, h + pad, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.translate(pad, pad)
    doc.drawContents(p, QRectF(-pad, -pad, w, h))
    p.end()
    arr = pixmap2ndarray(img, keep_alpha=True)
    rows = np.where((arr[..., -1] > 16).any(axis=1))[0]
    return float(rows.max()) - pad if len(rows) else -float("inf")


# ── Красные кейсы свипа (min_y = 0, репортованный симптом) ─────

_CYRILLIC_CASES = [
    # (family, ender) — свип: S после авторазмера > target=260
    ("A.C.M.E", "г"),
    ("BOMGcom004", "д"),
    ("BOMGcomPsuedoSaudi", "г"),
    ("v_Blambot Casual MOD", "щ"),
]


class TestAutoSizeNoOverflow:
    """После авторазмера `shrink_height` не должен превышать нижнюю
    ограничивающую линию (размах CP по Y)."""

    @pytest.mark.parametrize("family,ender", _CYRILLIC_CASES,
                             ids=[f"{f}+{c}" for f, c in _CYRILLIC_CASES])
    def test_shrink_height_within_target(self, scene, repo_fonts, family, ender):
        _require_family(repo_fonts, family)
        text = "В ЭТОЙ БУКВЕ ОНА\nЗАПИСЫВАЕТ ТЕКСТ\nФИНАЛ" + ender
        item = _make_item(scene, (0, 0, 500, 260), text, 40.0, family)
        item._update_flow_layout()

        target = _cp_target_height(item)
        S = item.layout.shrink_height
        assert S <= target + 0.5, (
            f"{family}+{ender}: после авторазмера shrink_height={S:.1f} "
            f"превышает нижнюю линию CP (target={target:.1f}) — "
            f"текст вылезает за ограничивающую линию "
            f"(font={item.layout.max_font_size():.1f}pt)"
        )

    @pytest.mark.parametrize("family,ender", _CYRILLIC_CASES,
                             ids=[f"{f}+{c}" for f, c in _CYRILLIC_CASES])
    def test_ink_not_clipped_below_br(self, scene, repo_fonts, family, ender):
        """Дно ink-рендера не должно уходить за boundingRect().bottom()
        (иначе Qt клипом режет нижнюю часть последней строки)."""
        _require_family(repo_fonts, family)
        text = "В ЭТОЙ БУКВЕ ОНА\nЗАПИСЫВАЕТ ТЕКСТ\nФИНАЛ" + ender
        item = _make_item(scene, (0, 0, 500, 260), text, 40.0, family)
        item._update_flow_layout()

        ib = ink_bottom_doc(item)
        brb = item.boundingRect().bottom()
        assert ib <= brb + 0.5, (
            f"{family}+{ender}: ink_bottom={ib:.1f} ниже br_bottom={brb:.1f} — "
            f"нижняя часть последней строки обрезана клипом"
        )

    def test_layout_metric_covers_ink(self, scene, repo_fonts):
        """Метрика layout (shrink_height) должна покрывать реальный ink
        В ПОЗИЦИЯХ ЛЕЙАУТА — иначе авторазмер останавливается, а ink уходит
        ниже линии.

        Текст в flow-блоках центрируется вертикально (VERTICAL_CENTER и
        _vertical_center_always): строки сдвинуты вниз на
        (max_height - S)/2 - doc_margin, и рендерный ink-дно включает этот
        детерминированный сдвиг. Поэтому сравниваем ink с S + сдвиг.
        """
        _require_family(repo_fonts, "BOMGcomPsuedoSaudi")
        text = "В ЭТОЙ БУКВЕ ОНА\nЗАПИСЫВАЕТ ТЕКСТ\nФИНАЛг"
        item = _make_item(scene, (0, 0, 500, 260), text, 40.0, "BOMGcomPsuedoSaudi")
        item._update_flow_layout()

        ib = ink_bottom_doc(item)
        layout = item.layout
        S = layout.shrink_height
        dm = item.document().documentMargin()
        from qtpy.QtCore import Qt
        centered = VERTICAL_CENTER and (
            layout._vertical_center_always
            or item.document().defaultTextOption().alignment() == Qt.AlignmentFlag.AlignCenter
        )
        center_shift = ((layout.max_height - S) / 2 - dm) if centered else 0.0
        assert center_shift >= 0, (
            f"неотрицательный сдвиг центрирования ожидался: {center_shift:.1f} "
            f"(max_height={layout.max_height:.1f}, S={S:.1f}, dm={dm:.1f})"
        )
        assert ib <= S + center_shift + 1.0, (
            f"shrink_height={S:.1f} не покрывает ink в позициях лейаута "
            f"(ink_bottom={ib:.1f}, сдвиг центрирования={center_shift:.1f}) — "
            f"метрика измеряет базовую строку '木fg', а не реальный ink "
            f"(дефицит={ib - S - center_shift:.1f}px)"
        )


class TestClipInkFallbackCase:
    """CLIP-ink кейс: латиница в шрифте без латиницы (fallback-глифы).

    Зафиксировано свипом: ink=270.0 > br=266.8 при S=266.8 > target=260
    (BOMGcomPsuedoSaudi, size 48, латинский текст, посл. строка 'XXXXXXг').
    """

    def test_latin_fallback_ink_not_clipped(self, scene, repo_fonts):
        _require_family(repo_fonts, "BOMGcomPsuedoSaudi")
        text = ("FIRST LINE OF THE BUBBLE\n"
                "SECOND LINE OF THE BUBBLE\n"
                "XXXXXXг")
        item = _make_item(scene, (0, 0, 500, 260), text, 48.0, "BOMGcomPsuedoSaudi")
        item._update_flow_layout()

        target = _cp_target_height(item)
        S = item.layout.shrink_height
        assert S <= target + 0.5, (
            f"shrink_height={S:.1f} > target={target:.1f} — "
            f"авторазмер остановился в переполнении (font={item.layout.max_font_size():.1f}pt)"
        )
        ib = ink_bottom_doc(item)
        brb = item.boundingRect().bottom()
        assert ib <= brb + 0.5, (
            f"ink_bottom={ib:.1f} ниже br_bottom={brb:.1f} — "
            f"fallback-глифы глубже метрики, нижняя строка клипнута"
        )


# ── Сценарий отрицательного CP (механика C, из поглощённого плана) ──

class TestNegativeCpGeometry:
    """Верхний CP выше начала блока (min_y < 0).

    Qt уважает отрицательный documentMargin (показано микро-пробом):
    текст сдвигается вверх целиком. Display-rect должен следовать за текстом
    (y = doc_margin), clip-регион (boundingRect = base ∪ CP-rect) накрывать
    инк, а координаты blk — оставаться согласованными с absBoundingRect().
    """

    def test_display_rect_covers_ink_when_top_cp_negative(self, scene, repo_fonts):
        """Контракт при min_y < 0: инк не выходит за clip-регион (boundingRect()
        = базовый rect ∪ CP-rect), display-rect не дегенерирует, координаты
        blk согласованы с absBoundingRect().

        (Конвенция: display-rect содержит padding (padding() == doc_margin),
        потребители вычитают 2*pad; полная «накрываемость» текста — за
        boundingRect() c union по CP, как в production-клиппинге.)
        """
        _require_family(repo_fonts, "BOMGcomPsuedoSaudi")
        item = _make_item(scene, (0, 0, 400, 260), "АБВ\nГДЕЖ\nЖЗг", 30.0,
                          "BOMGcomPsuedoSaudi")
        _set_cp_vertical(item, -80, 180)
        item._update_flow_layout()

        doc = item.document()
        dm = doc.documentMargin()
        assert dm < 0, "setDocumentMargin(min_y) не применил отрицательный марджин"

        # display-rect не должен дегенерировать в невалидный/нулевой rect
        dr = item._display_rect
        assert dr.height() > 0, (
            f"display-rect дегенерировал: height={dr.height():.1f} "
            f"(S={item.layout.shrink_height:.1f}, dm={dm:.1f})"
        )

        # Инк в пределах clip-региона (boundingRect = base ∪ CP-rect)
        ib = ink_bottom_doc(item)
        brb = item.boundingRect().bottom()
        assert ib <= brb + 0.5, (
            f"ink_bottom={ib:.1f} ниже br_bottom={brb:.1f}"
        )
        brt = item.boundingRect().top()
        assert dm <= brt + 1.0, (
            f"clip-регион (top={brt:.1f}) не доходит до начала текста (dm={dm:.1f})"
        )

        # Согласованность координат: blk.xyxy == absBoundingRect()
        bx, by, bw, bh = item.absBoundingRect()
        expected = [int(bx), int(by), int(bx + bw), int(by + bh)]
        assert item.blk.xyxy == expected, (
            f"blk.xyxy={item.blk.xyxy} != absBoundingRect={expected}"
        )

    def test_no_overshoot_after_grow_with_negative_cp(self, scene, repo_fonts):
        """Grow при отрицательных CP не должен уйти в переполнение
        (кейс свипа: span=340 → S=409.4 > 340)."""
        _require_family(repo_fonts, "BOMGcomPsuedoSaudi")
        item = _make_item(scene, (0, 0, 400, 340), "АБВ\nГДЕЖ\nЖЗг", 30.0,
                          "BOMGcomPsuedoSaudi")
        _set_cp_vertical(item, -80, 260)
        item._update_flow_layout()

        target = _cp_target_height(item)
        S = item.layout.shrink_height
        assert S <= target + 0.5, (
            f"при min_y<0 shrink_height={S:.1f} > target={target:.1f} — "
            f"grow ушёл в переполнение (font={item.layout.max_font_size():.1f}pt)"
        )