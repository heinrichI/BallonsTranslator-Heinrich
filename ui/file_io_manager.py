"""
FileIOManager — извлечённый из MainWindow.

Содержит логику импорта/экспорта файлов:
- Экспорт в DOC/TXT/MD
- Импорт из DOC/TXT
- Управление потоками ввода/вывода

НЕ зависит от Qt widgets — только от ProjectImgTrans и IO threads.
"""

import os
import os.path as osp
import logging
from pathlib import Path
from typing import Optional

from utils.logger import logger as LOGGER
from utils.message import create_error_dialog, create_info_dialog

LOGGER = logging.getLogger('BallonTranslator')


class FileIOManager:
    """
    Управление импортом/экспортом файлов.
    
    Responsibilities:
    - Экспорт в DOC/TXT/MD
    - Импорт из DOC/TXT
    - Управление потоками ввода/вывода
    """
    
    def __init__(self, imgtrans_proj, imsave_thread, export_doc_thread, import_doc_thread):
        """
        Args:
            imgtrans_proj: ProjImgTrans — модель проекта
            imsave_thread: ImgSaveThread — поток сохранения изображений
            export_doc_thread: ExportDocThread — поток экспорта в DOC
            import_doc_thread: ImportDocThread — поток импорта из DOC
        """
        self._proj = imgtrans_proj
        self._imsave_thread = imsave_thread
        self._export_doc_thread = export_doc_thread
        self._import_doc_thread = import_doc_thread
    
    def export_as_doc(self):
        """Экспорт проекта в DOC."""
        self._export_doc_thread.exportAsDoc(self._proj)
    
    def import_from_doc(self):
        """Импорт проекта из DOC."""
        self._import_doc_thread.importDoc(self._proj)
    
    def export_as_txt(self, dump_target: str, suffix: str = '.txt'):
        """
        Экспорт текста в TXT/MD файл.
        
        Args:
            dump_target: 'source' или 'translation'
            suffix: Расширение файла (.txt или .md)
        """
        try:
            self._proj.dump_txt(dump_target=dump_target, suffix=suffix)
            create_info_dialog('Text file exported to ' + self._proj.dump_txt_path(dump_target, suffix))
        except Exception as e:
            create_error_dialog(e, 'Failed to export as TEXT file')
    
    def import_translation_from_txt(self, file_path: str):
        """
        Импорт перевода из TXT/MD файла.
        
        Args:
            file_path: Путь к файлу
        
        Returns:
            Tuple (success: bool, message: str)
        """
        try:
            if not osp.exists(file_path):
                return False, "File not found"
            
            all_matched, match_rst = self._proj.load_translation_from_txt(file_path)
            matched_pages = match_rst['matched_pages']
            
            if all_matched:
                msg = 'Translation imported and matched successfully.'
            else:
                msg = 'Imported txt file not fully matched with current project'
                if len(match_rst['missing_pages']) > 0:
                    msg += '\nMissing pages: ' + '\n' + '\n'.join(match_rst['missing_pages'])
                if len(match_rst['unexpected_pages']) > 0:
                    msg += '\nUnexpected pages: ' + '\n' + '\n'.join(match_rst['unexpected_pages'])
                if len(match_rst['unmatched_pages']) > 0:
                    msg += '\nUnmatched pages: ' + '\n' + '\n'.join(match_rst['unmatched_pages'])
                msg = msg.strip()
            
            return True, msg
            
        except Exception as e:
            return False, f"Failed to import translation: {e}"
    
    def save_image(self, path: str, img_array, save_params: dict = None, keep_alpha: bool = False):
        """
        Сохраняет изображение в фоновом потоке.
        
        Args:
            path: Путь для сохранения
            img_array: Массив изображения
            save_params: Параметры сохранения
            keep_alpha: Сохранять альфа-канал
        """
        if save_params is None:
            save_params = {}
        self._imsave_thread.saveImg(path, img_array, save_params=save_params, keep_alpha=keep_alpha)
    
    def is_saving(self) -> bool:
        """Проверяет, идёт ли сохранение."""
        return self._imsave_thread.isRunning()
    
    def wait_for_save(self):
        """Ожидает завершения сохранения."""
        while self._imsave_thread.isRunning():
            import time
            time.sleep(0.1)
