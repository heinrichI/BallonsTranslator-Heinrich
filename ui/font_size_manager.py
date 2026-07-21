"""
FontSizeManager — единый источник правды для размера шрифта блока.

Синхронизирует 3 хранилища:
  1. fontformat.font_size (pixels) — view-side
  2. blk.fontformat.font_size (pixels) — data model
  3. document().defaultFont().pointSizeF() (points) — Qt document

Трекает источник изменения:
  "user" — пользователь через панель
  "auto_layout" — бинарный поиск / shrink-grow
  "pipeline" — детектор/OCR
  "init" — загрузка из проекта
"""

import logging
from utils.fontformat import px2pt, pt2px

LOGGER = logging.getLogger('BallonTranslator')


class FontSizeManager:

    def __init__(self, textitem):
        self._item = textitem
        self._source = "init"

    @property
    def size_pt(self) -> float:
        """Canonical размер в points."""
        if self._item.fontformat is not None:
            return px2pt(self._item.fontformat.font_size)
        return 0.0

    @property
    def size_px(self) -> float:
        """Canonical размер в pixels."""
        if self._item.fontformat is not None:
            return self._item.fontformat.font_size
        return 0.0

    @property
    def source(self) -> str:
        """Кто последний изменил размер."""
        return self._source

    def set(self, size_pt: float, source: str = "user"):
        """Установить размер. Автоматически синхронизирует все 3 хранилища."""
        if size_pt <= 0:
            return
        self._source = source
        new_px = pt2px(size_pt)

        # 1. View
        if self._item.fontformat is not None:
            self._item.fontformat.font_size = new_px

        # 2. Model
        if self._item.blk is not None and self._item.blk.fontformat is not None:
            self._item.blk.fontformat.font_size = new_px

        # 3. Qt document
        font = self._item.document().defaultFont()
        font.setPointSizeF(size_pt)
        self._item.document().setDefaultFont(font)

    def is_user_set(self) -> bool:
        """True если размер был задан пользователем (не auto-layout/pipeline)."""
        return self._source == "user"
