"""
TextBlockPresenter — MVP Presenter для текстового блока.

Медиатор между TextBlock (Model) и ITextBlockView (Interface).
Следует принципу Dependency Inversion: Presenter зависит от Interface, не от View.

Pattern:
  Model < Presenter > View (Interface) < View (PyQt)
"""

import logging
from typing import Optional

from utils.logger import logger as LOGGER
from utils.fontformat import FontFormat, pt2px, px2pt
from .view_interfaces import ITextBlockView

LOGGER = logging.getLogger('BallonTranslator')


class TextBlockPresenter:
    """
    MVP Presenter для текстового блока.

    Responsibilities:
    - Связывает Model (TextBlock) и View Interface (ITextBlockView)
    - Обрабатывает события от View и обновляет Model
    - Загружает данные из Model и говорит View показать

    Правило: Presenter зависит от View Interface, не от конкретного View.
    """

    def __init__(self, model, view: ITextBlockView):
        """
        Args:
            model: TextBlock — модель данных
            view: ITextBlockView — интерфейс View для отображения
        """
        self._model = model
        self._view = view
        self._connected = False

    def connect_signals(self):
        """Подключает сигналы View к обработчикам Presenter."""
        if self._connected:
            return

        # View signals → Presenter handlers
        if hasattr(self._view, 'propagate_user_edited'):
            self._view.propagate_user_edited.connect(self._on_text_edited)

        self._connected = True

    def disconnect_signals(self):
        """Отключает сигналы View от обработчиков Presenter."""
        if not self._connected:
            return

        if hasattr(self._view, 'propagate_user_edited'):
            try:
                self._view.propagate_user_edited.disconnect(self._on_text_edited)
            except:
                pass

        self._connected = False

    # ── View → Model (события от View) ──────────────────────

    def _on_text_edited(self, pos: int, added_text: str, joint_previous: bool):
        """Обработчик: текст изменился в View → обновляем Model."""
        if self._model is None:
            return

        # Обновляем Model
        self._model.translation = self._view.toPlainText()

        LOGGER.debug("[Presenter] text edited: pos=%d, added='%s'", pos, added_text)

    def _on_font_size_changed(self, size_pt: float):
        """Обработчик: размер шрифта изменился в View → обновляем Model."""
        if self._model is None or self._model.fontformat is None:
            return

        self._model.fontformat.font_size = pt2px(size_pt)

        LOGGER.debug("[Presenter] font size changed: %.1f pt", size_pt)

    # ── Model → View (загрузка данных) ───────────────────────

    def load_from_model(self):
        """Загружает данные из Model и говорит View показать."""
        if self._model is None or self._view is None:
            return

        # Текст
        if self._model.translation:
            self._view.setPlainText(self._model.translation)
        elif self._model.rich_text:
            self._view.setHtml(self._model.rich_text)

        # Шрифт
        if self._model.fontformat:
            self._view.setFontSize(self._model.fontformat.size_pt)

    def sync_to_model(self):
        """Синхронизирует данные из View обратно в Model."""
        if self._model is None or self._view is None:
            return

        # Текст
        self._model.translation = self._view.toPlainText()
        self._model.rich_text = self._view.toHtml()

        # Шрифт
        if self._view.fontformat:
            self._model.fontformat = self._view.fontformat.deepcopy()

    # ── Presenter → Model (команды) ──────────────────────────

    def set_font_size(self, size_pt: float):
        """Устанавливает размер шрифта."""
        if self._model is None or self._model.fontformat is None:
            return

        self._model.fontformat.font_size = pt2px(size_pt)

        # Обновляем View
        if self._view:
            self._view.setFontSize(size_pt)

    def set_font_family(self, family: str):
        """Устанавливает семейство шрифта."""
        if self._model is None or self._model.fontformat is None:
            return

        self._model.fontformat.font_family = family

        # Обновляем View
        if self._view:
            self._view.setFontFamily(family)

    def set_alignment(self, alignment: int):
        """Устанавливает выравнивание."""
        if self._model is None or self._model.fontformat is None:
            return

        self._model.fontformat.alignment = alignment

        # Обновляем View
        if self._view:
            self._view.setAlignment(alignment)

    def set_vertical(self, vertical: bool):
        """Устанавливает вертикальный режим."""
        if self._model is None or self._model.fontformat is None:
            return

        self._model.fontformat.vertical = vertical

        # Обновляем View
        if self._view:
            self._view.setVertical(vertical)

    # ── Presenter → View (инструкции) ────────────────────────

    def select(self):
        """Говорит View: выделить блок."""
        if self._view:
            self._view.setSelected(True)

    def deselect(self):
        """Говорит View: снять выделение."""
        if self._view:
            self._view.setSelected(False)

    def start_edit(self):
        """Говорит View: начать редактирование."""
        if self._view:
            self._view.startEdit()

    def end_edit(self):
        """Говорит View: закончить редактирование."""
        if self._view:
            self._view.endEdit()

    def ensure_visible(self):
        """Говорит View: сделать видимым."""
        if self._view and self._view.scene():
            self._view.scene().views()[0].ensureVisible(self._view)
