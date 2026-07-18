"""
TextFormatManager — извлечённый из TextBlkItem.

Содержит логику управления форматированием текста:
- Применение FontFormat
- Градиенты, тени, обводка
- Управление прозрачностью

НЕ зависит от бизнес-logic — только от View и FontFormat.
"""

import math
import logging
from typing import Tuple

from qtpy.QtCore import Qt, QRectF, QPointF
from qtpy.QtGui import (QFont, QColor, QPen, QTextCursor, QTextCharFormat,
                        QLinearGradient, QGradient)

from utils.fontformat import FontFormat, pt2px

LOGGER = logging.getLogger('BallonTranslator')


class TextFormatManager:
    """
    Управление форматированием текста в TextBlkItem.
    
    Responsibilities:
    - Применение FontFormat к текстовому блоку
    - Управление градиентами
    - Управление тенями и обводкой
    - Управление прозрачностью
    """
    
    def __init__(self, text_item):
        """
        Args:
            text_item: TextBlkItem для управления форматированием
        """
        self._text_item = text_item
        self._fontformat = text_item.fontformat
    
    def set_fontformat(self, ffmat: FontFormat, set_char_format=False, 
                      set_stroke_width=True, set_effect=True):
        """
        Применяет FontFormat к текстовому блоку.
        
        Args:
            ffmat: FontFormat для применения
            set_char_format: Установить char format для текущего выделения
            set_stroke_width: Установить ширину обводки
            set_effect: Установить эффекты (тень, обводка)
        """
        self._text_item.repainting = True
        
        if self._fontformat.vertical != ffmat.vertical:
            self._text_item.setVertical(ffmat.vertical)
        
        cursor = self._text_item.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        font = self._text_item.document().defaultFont()
        
        # Установка шрифта
        font.setFamily(ffmat.font_family)
        font.setPointSizeF(ffmat.size_pt)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        
        fweight = ffmat.font_weight
        if fweight is None:
            fweight = font.weight()
            ffmat.font_weight = fweight
        font.setBold(ffmat.bold)
        
        self._text_item.document().setDefaultFont(font)
        
        # Установка формата
        format = cursor.charFormat()
        format.setFont(font)
        
        if ffmat.gradient_enabled:
            gradient = self.get_text_gradient(ffmat)
            format.setForeground(gradient)
        else:
            format.setForeground(QColor(*ffmat.foreground_color()))
        
        if not ffmat.bold:
            format.setFontWeight(fweight)
        format.setFontItalic(ffmat.italic)
        format.setFontUnderline(ffmat.underline)
        
        if not ffmat.vertical:
            format.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
            format.setFontLetterSpacing(ffmat.letter_spacing * 100)
        
        cursor.setCharFormat(format)
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setBlockCharFormat(format)
        
        if set_char_format:
            cursor.setCharFormat(format)
        
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._text_item.setTextCursor(cursor)
        self._text_item.stroke_qcolor = QColor(*ffmat.stroke_color())
        
        # Установка эффектов
        if set_effect:
            self.set_shadow(ffmat, repaint=False)
        if set_stroke_width:
            self.set_stroke_width(ffmat.stroke_width, repaint_background=False)
        self.set_opacity(ffmat.opacity)
        
        # Выравнивание
        alignment_qt_flag = [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignCenter, Qt.AlignmentFlag.AlignRight][ffmat.alignment]
        doc = self._text_item.document()
        op = doc.defaultTextOption()
        op.setAlignment(alignment_qt_flag)
        doc.setDefaultTextOption(op)
        
        if ffmat.vertical:
            self._text_item.setLetterSpacing(ffmat.letter_spacing)
        self._text_item.setLineSpacing(ffmat.line_spacing)
        
        # Сохранение gradient свойств
        self._fontformat.gradient_enabled = ffmat.gradient_enabled
        self._fontformat.gradient_start_color = ffmat.gradient_start_color
        self._fontformat.gradient_end_color = ffmat.gradient_end_color
        self._fontformat.gradient_angle = ffmat.gradient_angle
        self._fontformat.gradient_size = ffmat.gradient_size
        
        self._fontformat.merge(ffmat)
        
        if self._fontformat.gradient_enabled:
            self._text_item.update()
        
        self._text_item.repainting = False
        if set_effect or set_stroke_width:
            self._text_item.repaint_background()
    
    def get_text_gradient(self, fontformat: FontFormat = None):
        """
        Создаёт градиент для текста.
        
        Args:
            fontformat: FontFormat для градиента (по умолчанию self._fontformat)
        
        Returns:
            QLinearGradient: Градиент для текста
        """
        gradient = QLinearGradient()
        if fontformat is None:
            fontformat = self._fontformat
        
        angle = fontformat.gradient_angle
        rad = math.radians(angle)
        dx = math.cos(rad)
        dy = math.sin(rad)
        
        rect = self._text_item.boundingRect()
        center = rect.center()
        radius = max(rect.width(), rect.height()) * fontformat.gradient_size
        
        gradient.setStart(center.x() - dx * radius, center.y() - dy * radius)
        gradient.setFinalStop(center.x() + dx * radius, center.y() + dy * radius)
        
        start_color = QColor(*fontformat.gradient_start_color)
        end_color = QColor(*fontformat.gradient_end_color)
        gradient.setColorAt(0, start_color)
        gradient.setColorAt(1, end_color)
        
        return gradient
    
    def set_shadow(self, fmt: FontFormat, repaint=True):
        """
        Устанавливает тень для текста.
        
        Args:
            fmt: FontFormat с параметрами тени
            repaint: Перерисовать фон
        """
        self._fontformat.shadow_radius = fmt.shadow_radius
        self._fontformat.shadow_strength = fmt.shadow_strength
        self._fontformat.shadow_color = fmt.shadow_color
        self._fontformat.shadow_offset = fmt.shadow_offset
        
        if self._fontformat.shadow_radius > 0:
            self._text_item.setPadding(self._text_item.layout.max_font_size(to_px=True))
        
        if repaint:
            self._text_item.repaint_background()
    
    def set_stroke_width(self, stroke_width: float, padding=True, 
                        repaint_background=True, restore_cursor=False):
        """
        Устанавливает ширину обводки текста.
        
        Args:
            stroke_width: Ширина обводки
            padding: Добавить padding для обводки
            repaint_background: Перерисовать фон
            restore_cursor: Восстановить позицию курсора
        """
        cursor, after_kwargs = self._text_item._before_set_ffmt(
            set_selected=False, restore_cursor=restore_cursor
        )
        
        self._fontformat.stroke_width = stroke_width
        if stroke_width > 0 and padding:
            p = self._text_item.layout.max_font_size(to_px=True) * (stroke_width + 0.05) / 2
            self._text_item.setPadding(p)
        
        self._text_item._after_set_ffmt(cursor, repaint_background, restore_cursor, **after_kwargs)
        if repaint_background:
            self._text_item.update()
    
    def set_stroke_color(self, scolor):
        """
        Устанавливает цвет обводки.
        
        Args:
            scolor: Цвет обводки (QColor или кортеж RGB)
        """
        self._text_item.stroke_qcolor = scolor if isinstance(scolor, QColor) else QColor(*scolor)
        self._fontformat.srgb = [
            self._text_item.stroke_qcolor.red(),
            self._text_item.stroke_qcolor.green(),
            self._text_item.stroke_qcolor.blue()
        ]
        self._text_item.repaint_background()
        self._text_item.update()
    
    def set_opacity(self, opacity: float):
        """
        Устанавливает прозрачность текста.
        
        Args:
            opacity: Прозрачность (0.0 - 1.0)
        """
        self._text_item.setOpacity(opacity)
        self._fontformat.opacity = opacity
    
    def set_gradient_enabled(self, value: bool, repaint_background=True):
        """
        Включает/выключает градиент.
        
        Args:
            value: Включить градиент
            repaint_background: Перерисовать фон
        """
        self._fontformat.gradient_enabled = value
        cursor, after_kwargs = self._text_item._before_set_ffmt(
            set_selected=False, restore_cursor=False
        )
        
        cfmt = QTextCharFormat()
        if value:
            gradient = self.get_text_gradient()
            cfmt.setForeground(gradient)
        else:
            cfmt.setForeground(QColor(*[int(c) for c in self._fontformat.frgb]))
        
        self._text_item.set_cursor_cfmt(cursor, cfmt, True)
        self._text_item._after_set_ffmt(cursor, repaint_background, False, **after_kwargs)
    
    def set_gradient_attribute(self, attr_name: str, value):
        """
        Устанавливает атрибут градиента.
        
        Args:
            attr_name: Имя атрибута
            value: Значение атрибута
        """
        self._text_item.old_ffmt_values = {}
        self._text_item.old_ffmt_values[attr_name] = self._fontformat[attr_name]
        setattr(self._fontformat, attr_name, value)
        self.set_gradient_enabled(self._fontformat.gradient_enabled)
        self._text_item.old_ffmt_values = None
    
    def set_bg_attribute(self, attr_name: str, value, repaint=True):
        """
        Устанавливает атрибут фона.
        
        Args:
            attr_name: Имя атрибута
            value: Значение атрибута
            repaint: Перерисовать
        """
        setattr(self._fontformat, attr_name, value)
        if repaint:
            self._text_item.repaint_background()
            self._text_item.update()
