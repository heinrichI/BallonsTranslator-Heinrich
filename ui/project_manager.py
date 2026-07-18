"""
ProjectManager — управление проектами.

Извлечён из MainWindow для уменьшения размера класса.
"""

import os
import os.path as osp
from typing import Optional
from pathlib import Path

from utils.logger import logger as LOGGER
from utils.config import pcfg
from utils import shared


class ProjectManager:
    """
    Управляет открытием/закрытием проектов.

    Responsibilities:
    - Открытие директорий с изображениями
    - Открытие JSON проектов
    - Обновление списка страниц
    - Навигация по страницам
    """

    def __init__(self, mainwindow):
        """
        Args:
            mainwindow: MainWindow — главное окно
        """
        self.mw = mainwindow
        self.imgtrans_proj = mainwindow.imgtrans_proj

    def open_project(self, proj_dir: str):
        """
        Открывает проект из директории.

        Args:
            proj_dir: Путь к директории проекта
        """
        if not osp.exists(proj_dir):
            LOGGER.error(f"Directory does not exist: {proj_dir}")
            return

        # Сохраняем текущий проект если нужно
        if self.mw.save_on_page_changed and self.imgtrans_proj.is_valid():
            self.mw.conditional_save()

        # Открываем новый проект
        self.imgtrans_proj.set_imgdir(proj_dir)
        self.mw.canvas.set_imgtrans_proj(self.imgtrans_proj)

        # Обновляем UI
        self.update_page_list()

        # Сохраняем в историю
        self._add_to_recent(proj_dir)

        LOGGER.info(f"Opened project: {proj_dir}")

    def open_json_project(self, json_path: str):
        """
        Открывает проект из JSON файла.

        Args:
            json_path: Путь к JSON файлу
        """
        if not osp.exists(json_path):
            LOGGER.error(f"JSON file does not exist: {json_path}")
            return

        # Сохраняем текущий проект если нужно
        if self.mw.save_on_page_changed and self.imgtrans_proj.is_valid():
            self.mw.conditional_save()

        # Открываем JSON проект
        self.imgtrans_proj.set_json_path(json_path)
        self.mw.canvas.set_imgtrans_proj(self.imgtrans_proj)

        # Обновляем UI
        self.update_page_list()

        LOGGER.info(f"Opened JSON project: {json_path}")

    def update_page_list(self):
        """Обновляет список страниц в UI."""
        self.mw.pageList.clear()

        if not self.imgtrans_proj.is_valid():
            return

        page_list = self.imgtrans_proj.get_page_list()
        current_idx = self.imgtrans_proj.get_current_page_index()

        for i, page_name in enumerate(page_list):
            self.mw.pageList.addItem(page_name)

        # Восстанавливаем выбранную страницу
        if 0 <= current_idx < self.mw.pageList.count():
            self.mw.pageList.setCurrentRow(current_idx)

    def page_changed(self, current_row: int, previous_row: int):
        """
        Обработчик смены страницы.

        Args:
            current_row: Номер текущей страницы
            previous_row: Номер предыдущей страницы
        """
        if current_row < 0 or current_row >= self.mw.pageList.count():
            return

        if self.mw.page_changing:
            return

        self.mw.page_changing = True

        try:
            # Сохраняем текущую страницу
            if self.mw.save_on_page_changed and self.imgtrans_proj.is_valid():
                self.mw.saveCurrentPage()

            # Переключаем страницу
            page_name = self.mw.pageList.item(current_row).text()
            self.imgtrans_proj.set_current_page(page_name)

            # Обновляем canvas
            self.mw.canvas.set_imgtrans_proj(self.imgtrans_proj)

            # Обновляем текстовый менеджер
            self.mw.st_manager.updateSceneTextitems()

            LOGGER.info(f"Switched to page: {page_name}")

        finally:
            self.mw.page_changing = False

    def drop_open_dir(self, dir_path: str):
        """
        Открывает директорию через drag-and-drop.

        Args:
            dir_path: Путь к директории
        """
        if osp.isdir(dir_path):
            self.open_project(dir_path)

    def _add_to_recent(self, proj_dir: str):
        """Добавляет проект в список недавних."""
        recent_list = self.mw.leftBar.recent_proj_list
        if proj_dir in recent_list:
            recent_list.remove(proj_dir)
        recent_list.insert(0, proj_dir)
        # Ограничиваем список 10 проектами
        if len(recent_list) > 10:
            recent_list.pop()
        self.mw.leftBar.save_recent_list()

    def get_page_count(self) -> int:
        """Возвращает количество страниц."""
        if self.imgtrans_proj.is_valid():
            return len(self.imgtrans_proj.get_page_list())
        return 0

    def get_current_page_index(self) -> int:
        """Возвращает индекс текущей страницы."""
        if self.imgtrans_proj.is_valid():
            return self.imgtrans_proj.get_current_page_index()
        return -1
