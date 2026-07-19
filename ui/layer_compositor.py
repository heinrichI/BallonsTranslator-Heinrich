"""
LayerCompositor — композиция слоёв Canvas.

Извлечён из Canvas для уменьшения размера класса.
"""

import numpy as np
from typing import Optional

from utils.logger import logger as LOGGER
from utils.config import pcfg
from .misc import ndarray2pixmap


class LayerCompositor:
    """
    Управляет композицией слоёв Canvas.

    Responsibilities:
    - Обновление слоёв (inpaint, drawing)
    - Композиция результатов
    - Управление прозрачностью
    """

    def __init__(self, canvas):
        """
        Args:
            canvas: Canvas — графическая сцена
        """
        self.canvas = canvas
        self.imgtrans_proj = canvas.imgtrans

        # Слои
        self.baseLayer = canvas.baseLayer
        self.inpaintLayer = canvas.inpaintLayer
        self.drawingLayer = canvas.drawingLayer
        self.textLayer = canvas.text_layer

    def update_layers(self):
        """Обновляет слой inpaint из данных проекта."""
        if self.imgtrans_proj is None or self.imgtrans_proj.inpainted_array is None:
            return

        img_array = self.imgtrans_proj.inpainted_array

        # Конвертируем numpy array в QPixmap
        pixmap = ndarray2pixmap(img_array)

        # Устанавливаем pixmap на слой
        self.inpaintLayer.setPixmap(pixmap)

        # Обновляем размер сцены
        self.canvas.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        LOGGER.debug("Updated inpaint layer")

    def render_result_img(self) -> Optional[np.ndarray]:
        """
        Рендерит финальное изображение с учётом всех слоёв.

        Returns:
            numpy array с результатом или None
        """
        if self.imgtrans_proj is None:
            return None

        # Сохраняем текущее состояние
        old_scale = self.canvas.get_scale()
        scroll_x, scroll_y = self.canvas.get_scroll_position()

        try:
            # Временно скрываем textLayer для рендера
            text_layer_visible = self.textLayer.isVisible()
            self.textLayer.hide()

            # Устанавливаем масштаб 1:1
            self.canvas.reset_transform()

            # Рендерим сцену
            from qtpy.QtGui import QImage, QPainter
            rect = self.canvas.sceneRect()
            image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
            image.fill(0)

            painter = QPainter(image)
            self.canvas.render(painter)
            painter.end()

            # Конвертируем в numpy array
            ptr = image.bits()
            ptr.setsize(image.byteCount())
            arr = np.array(ptr).reshape(image.height(), image.width(), 4)

            # Восстанавливаем textLayer
            if text_layer_visible:
                self.textLayer.show()

            return arr

        finally:
            # Восстанавливаем масштаб и прокрутку
            self.canvas.scale_to(old_scale)
            self.canvas.set_scroll_position(scroll_x, scroll_y)

    def set_mask_transparency(self, value: int):
        """
        Устанавливает прозрачность слоя inpaint.

        Args:
            value: Значение прозрачности (0-100)
        """
        opacity = value / 100.0
        self.inpaintLayer.setOpacity(opacity)

    def set_original_transparency(self, value: int):
        """
        Устанавливает прозрачность базового слоя.

        Args:
            value: Значение прозрачности (0-100)
        """
        opacity = value / 100.0
        self.baseLayer.setOpacity(opacity)

    def set_text_layer_transparency(self, value: int):
        """
        Устанавливает прозрачность текстового слоя.

        Args:
            value: Значение прозрачности (0-100)
        """
        opacity = value / 100.0
        self.textLayer.setOpacity(opacity)

    def set_active_layer_transparency(self, value: int):
        """
        Устанавливает прозрачность активного слоя рисования.

        Args:
            value: Значение прозрачности (0-100)
        """
        if hasattr(self.canvas, 'drawing_layer'):
            opacity = value / 100.0
            self.canvas.drawing_layer.setOpacity(opacity)

    def composite_layers(self) -> Optional[np.ndarray]:
        """
        Композиция всех слоёв в одно изображение.

        Returns:
            numpy array с результатом
        """
        if self.imgtrans_proj is None:
            return None

        # Начинаем с базового изображения
        result = self.imgtrans_proj.img_array.copy()

        # Накладываем inpaint слой
        if self.imgtrans_proj.inpainted_array is not None:
            mask = self.imgtrans_proj.mask_array
            if mask is not None:
                # Применяем inpaint только в областях маски
                inpainted = self.imgtrans_proj.inpainted_array
                result[mask > 0] = inpainted[mask > 0]

        return result
