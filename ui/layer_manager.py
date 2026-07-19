"""
LayerManager — управление слоями сцены.

Выделен из Canvas для слабой связанности.
"""

from typing import Optional, Any
from qtpy.QtCore import QObject, Signal
from qtpy.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem
import numpy as np

from utils.logger import logger as LOGGER


class LayerManager(QObject):
    """
    Управление слоями сцены.

    Responsibilities:
    - Управление baseLayer, inpaintLayer, drawingLayer, textLayer
    - Обновление слоёв
    - Управление видимостью и прозрачностью
    """

    layersUpdated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Слои
        self._base_layer: Optional[QGraphicsPixmapItem] = None
        self._inpaint_layer: Optional[QGraphicsPixmapItem] = None
        self._drawing_layer: Optional[QGraphicsItem] = None
        self._text_layer: Optional[QGraphicsItem] = None

        # Проект
        self._imgtrans_proj = None

    def set_layers(self, base, inpaint, drawing, text):
        """Устанавливает слои."""
        self._base_layer = base
        self._inpaint_layer = inpaint
        self._drawing_layer = drawing
        self._text_layer = text

    def set_imgtrans_proj(self, proj):
        """Устанавливает проект изображений."""
        self._imgtrans_proj = proj

    def get_base_layer(self):
        """Возвращает базовый слой."""
        return self._base_layer

    def get_inpaint_layer(self):
        """Возвращает слой инпейнта."""
        return self._inpaint_layer

    def get_drawing_layer(self):
        """Возвращает слой рисования."""
        return self._drawing_layer

    def get_text_layer(self):
        """Возвращает текстовый слой."""
        return self._text_layer

    def set_text_layer_visible(self, visible: bool):
        """Управляет видимостью текстового слоя."""
        if self._text_layer is None:
            return
        if visible:
            self._text_layer.show()
        else:
            self._text_layer.hide()

    def set_text_layer_opacity(self, opacity: float):
        """Устанавливает прозрачность текстового слоя."""
        if self._text_layer is not None:
            self._text_layer.setOpacity(opacity)

    def set_inpaint_layer_opacity(self, opacity: float):
        """Устанавливает прозрачность слоя инпейнта."""
        if self._inpaint_layer is not None:
            self._inpaint_layer.setOpacity(opacity)

    def set_base_layer_opacity(self, opacity: float):
        """Устанавливает прозрачность базового слоя."""
        if self._base_layer is not None:
            self._base_layer.setOpacity(opacity)

    def update_layers(self):
        """Обновляет слои из проекта."""
        if self._imgtrans_proj is None or self._imgtrans_proj.inpainted_array is None:
            return

        try:
            from .misc import ndarray2pixmap
            img_array = self._imgtrans_proj.inpainted_array
            pixmap = ndarray2pixmap(img_array)

            if self._inpaint_layer is not None:
                self._inpaint_layer.setPixmap(pixmap)

            self.layersUpdated.emit()
        except Exception as e:
            LOGGER.error(f"Error updating layers: {e}")

    def add_item_to_text_layer(self, item):
        """Добавляет элемент на текстовый слой."""
        if self._text_layer is not None:
            item.setParentItem(self._text_layer)

    def remove_item_from_scene(self, item, scene: QGraphicsScene):
        """Удаляет элемент со сцены."""
        scene.removeItem(item)

    def composite_layers(self) -> Optional[np.ndarray]:
        """Композиция всех слоёв в одно изображение."""
        if self._imgtrans_proj is None:
            return None

        # Начинаем с базового изображения
        result = self._imgtrans_proj.img_array.copy()

        # Накладываем inpaint слой
        if self._imgtrans_proj.inpainted_array is not None:
            mask = self._imgtrans_proj.mask_array
            if mask is not None:
                inpainted = self._imgtrans_proj.inpainted_array
                result[mask > 0] = inpainted[mask > 0]

        return result
