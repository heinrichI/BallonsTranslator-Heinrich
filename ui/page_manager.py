"""
PageManager — извлечённый из MainWindow.

Содержит логику управления страницами проекта:
- Навигация между страницами
- Сохранение текущей страницы
- Загрузка страницы

НЕ зависит от Qt widgets — только от ProjectImgTrans.
"""

import os
import os.path as osp
import logging
from typing import Dict, List, Optional

from utils.logger import logger as LOGGER
from utils.textblock import TextBlock

LOGGER = logging.getLogger('BallonTranslator')


class PageManager:
    """
    Управление страницами проекта.
    
    Responsibilities:
    - Навигация между страницами
    - Сохранение текущей страницы
    - Загрузка страницы
    - Проверка необходимости сохранения
    """
    
    def __init__(self, imgtrans_proj):
        """
        Args:
            imgtrans_proj: ProjImgTrans — модель проекта
        """
        self._proj = imgtrans_proj
        self._page_changing = False
        self._save_on_page_changed = True
        self._opening_dir = False
    
    @property
    def current_page(self) -> Optional[str]:
        """Текущая страница."""
        return self._proj.current_img
    
    @property
    def num_pages(self) -> int:
        """Количество страниц."""
        return self._proj.num_pages
    
    @property
    def pages(self) -> Dict[str, List[TextBlock]]:
        """Словарь страниц проекта."""
        return self._proj.pages
    
    def set_page_changing(self, changing: bool):
        """Устанавливает флаг смены страницы."""
        self._page_changing = changing
    
    @property
    def is_page_changing(self) -> bool:
        """Флаг смены страницы."""
        return self._page_changing
    
    def set_save_on_page_changed(self, save: bool):
        """Устанавливает флаг автосохранения при смене страницы."""
        self._save_on_page_changed = save
    
    def set_opening_dir(self, opening: bool):
        """Устанавливает флаг открытия директории."""
        self._opening_dir = opening
    
    def has_unsaved_changes(self) -> bool:
        """Проверяет, есть ли несохранённые изменения."""
        return self._proj.img_valid and self._proj.has_unsaved_changes()
    
    def change_page(self, page_name: str) -> bool:
        """
        Переключает страницу.
        
        Args:
            page_name: Имя страницы для переключения
        
        Returns:
            True если страница была переключена
        """
        if page_name not in self._proj.pages:
            return False
        
        self._proj.set_current_img(page_name)
        return True
    
    def change_page_by_index(self, index: int) -> bool:
        """
        Переключает страницу по индексу.
        
        Args:
            index: Индекс страницы
        
        Returns:
            True если страница была переключена
        """
        if index < 0 or index >= self.num_pages:
            return False
        
        self._proj.set_current_img_byidx(index)
        return True
    
    def get_page_index(self, page_name: str) -> int:
        """
        Возвращает индекс страницы по имени.
        
        Args:
            page_name: Имя страницы
        
        Returns:
            Индекс страницы или -1 если не найдена
        """
        keys_list = list(self._proj.pages.keys())
        if page_name in keys_list:
            return keys_list.index(page_name)
        return -1
    
    def get_page_blocks(self, page_name: str) -> List[TextBlock]:
        """
        Возвращает список блоков страницы.
        
        Args:
            page_name: Имя страницы
        
        Returns:
            Список TextBlock или пустой список
        """
        if page_name in self._proj.pages:
            return self._proj.pages[page_name]
        return []
    
    def save_page_blocks(self, page_name: str, blocks: List[TextBlock]):
        """
        Сохраняет блоки страницы.
        
        Args:
            page_name: Имя страницы
            blocks: Список TextBlock для сохранения
        """
        if page_name in self._proj.pages:
            self._proj.pages[page_name] = blocks
    
    def should_save_on_change(self) -> bool:
        """Проверяет, нужно ли сохранять при смене страницы."""
        return self._save_on_page_changed and not self._opening_dir
