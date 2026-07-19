"""
ImageModel — модель для работы с изображениями.

Изолирует numpy-операции от View-компонетов.
"""

import numpy as np
from typing import Optional, Tuple

from utils.logger import logger as LOGGER


class ImageModel:
    """
    Модель для работы с изображениями.

    Responsibilities:
    - Доступ к регионам изображения
    - Операции с масками
    - Инпейнтинг
    """

    def __init__(self, proj):
        """
        Args:
            proj: ProjImgTrans — проект изображений
        """
        self._proj = proj

    @property
    def img_array(self) -> Optional[np.ndarray]:
        """Возвращает основной массив изображения."""
        return self._proj.img_array if self._proj else None

    @property
    def inpainted_array(self) -> Optional[np.ndarray]:
        """Возвращает массив инпейнта."""
        return self._proj.inpainted_array if self._proj else None

    @property
    def mask_array(self) -> Optional[np.ndarray]:
        """Возвращает массив маски."""
        return self._proj.mask_array if self._proj else None

    def get_region(self, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
        """
        Возвращает регион изображения.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол

        Returns:
            numpy array или None
        """
        if self.img_array is None:
            return None
        return self.img_array[y1:y2, x1:x2]

    def set_region(self, x1: int, y1: int, x2: int, y2: int, data: np.ndarray) -> bool:
        """
        Устанавливает регион изображения.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол
            data: Данные для установки

        Returns:
            True если успешно
        """
        if self.img_array is None:
            return False
        try:
            self.img_array[y1:y2, x1:x2] = data
            return True
        except Exception as e:
            LOGGER.error(f"Error setting image region: {e}")
            return False

    def get_inpainted_region(self, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
        """
        Возвращает регион инпейнта.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол

        Returns:
            numpy array или None
        """
        if self.inpainted_array is None:
            return None
        return self.inpainted_array[y1:y2, x1:x2]

    def set_inpainted_region(self, x1: int, y1: int, x2: int, y2: int, data: np.ndarray) -> bool:
        """
        Устанавливает регион инпейнта.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол
            data: Данные для установки

        Returns:
            True если успешно
        """
        if self.inpainted_array is None:
            return False
        try:
            self.inpainted_array[y1:y2, x1:x2] = data
            return True
        except Exception as e:
            LOGGER.error(f"Error setting inpainted region: {e}")
            return False

    def get_mask_region(self, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
        """
        Возвращает регион маски.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол

        Returns:
            numpy array или None
        """
        if self.mask_array is None:
            return None
        return self.mask_array[y1:y2, x1:x2]

    def set_mask_region(self, x1: int, y1: int, x2: int, y2: int, value: int = 255) -> bool:
        """
        Устанавливает значение в регионе маски.

        Args:
            x1, y1: Верхний левый угол
            x2, y2: Нижний правый угол
            value: Значение маски (0-255)

        Returns:
            True если успешно
        """
        if self.mask_array is None:
            return False
        try:
            self.mask_array[y1:y2, x1:x2] = value
            return True
        except Exception as e:
            LOGGER.error(f"Error setting mask region: {e}")
            return False

    def apply_inpaint(self, mask: np.ndarray, rect: Tuple[int, int, int, int]) -> bool:
        """
        Применяет инпейнт к региону.

        Args:
            mask: Маска для инпейнта
            rect: Прямоугольник (x1, y1, x2, y2)

        Returns:
            True если успешно
        """
        if self.inpainted_array is None or self.mask_array is None:
            return False

        x1, y1, x2, y2 = rect
        try:
            self.mask_array[y1:y2, x1:x2] = mask
            return True
        except Exception as e:
            LOGGER.error(f"Error applying inpaint: {e}")
            return False

    def get_image_size(self) -> Tuple[int, int]:
        """
        Возвращает размер изображения.

        Returns:
            (width, height) или (0, 0)
        """
        if self.img_array is None:
            return (0, 0)
        h, w = self.img_array.shape[:2]
        return (w, h)

    def is_valid(self) -> bool:
        """Проверяет, загружено ли изображение."""
        return self.img_array is not None
