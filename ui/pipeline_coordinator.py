"""
PipelineCoordinator — извлечённый из MainWindow.

Содержит логику координации pipeline обработки:
- Запуск imgtrans pipeline
- Постобработка переводов
- Управление состоянием pipeline

НЕ зависит от Qt widgets — только от ProjectImgTrans и ModuleManager.
"""

import re
import logging
from typing import Dict, List, Optional

from utils.logger import logger as LOGGER
from utils.textblock import TextBlock, TextAlignment
from utils.text_processing import is_cjk, full_len, half_len
from utils.config import pcfg
from utils import shared

LOGGER = logging.getLogger('BallonTranslator')


class PipelineCoordinator:
    """
    Координация pipeline обработки изображений.
    
    Responsibilities:
    - Запуск imgtrans pipeline
    - Постобработка переводов
    - Управление состоянием pipeline
    """
    
    def __init__(self, imgtrans_proj, module_manager):
        """
        Args:
            imgtrans_proj: ProjImgTrans — модель проекта
            module_manager: ModuleManager — менеджер модулей
        """
        self._proj = imgtrans_proj
        self._module_manager = module_manager
        self._postprocess_mt_toggle = True
        self._run_imgtrans_wo_textstyle_update = False
        self._backup_blkstyles: List = []
    
    def set_postprocess_mt_toggle(self, toggle: bool):
        """Устанавливает флаг постобработки MT."""
        self._postprocess_mt_toggle = toggle
    
    def set_run_wo_textstyle_update(self, run_wo_update: bool):
        """Устанавливает флаг запуска без обновления стилей."""
        self._run_imgtrans_wo_textstyle_update = run_wo_update
    
    def clear_backup_blkstyles(self):
        """Очищает бэкап стилей блоков."""
        self._backup_blkstyles.clear()
    
    def postprocess_translations(self, blk_list: List[TextBlock], 
                                 mt_sub_widget=None, upper_case: bool = False):
        """
        Постобработка переводов.
        
        Args:
            blk_list: Список TextBlock для постобработки
            mt_sub_widget: Виджет для замены текста
            upper_case: Преобразовать в верхний регистр
        """
        src_is_cjk = is_cjk(pcfg.module.translate_source)
        tgt_is_cjk = is_cjk(pcfg.module.translate_target)
        
        if tgt_is_cjk:
            for blk in blk_list:
                if src_is_cjk:
                    blk.translation = full_len(blk.translation)
                else:
                    blk.translation = half_len(blk.translation)
                    blk.translation = re.sub(r'([?.!"])\s+', r'\1', blk.translation)
        else:
            for blk in blk_list:
                if blk.vertical:
                    blk.alignment = TextAlignment.Center
                blk.translation = half_len(blk.translation)
                blk.vertical = False
        
        for blk in blk_list:
            if mt_sub_widget is not None:
                blk.translation = mt_sub_widget.sub_text(blk.translation)
            if upper_case:
                blk.translation = blk.translation.upper()
    
    def apply_text_style_overrides(self, blk_list: List[TextBlock], 
                                   global_format=None, 
                                   backup_blkstyles: List = None,
                                   run_wo_textstyle_update: bool = False):
        """
        Применяет переопределения стилей текста к блокам.
        
        Args:
            blk_list: Список TextBlock
            global_format: Глобальный FontFormat
            backup_blkstyles: Бэкап стилей
            run_wo_textstyle_update: Запуск без обновления стилей
        """
        if global_format is None:
            return
        
        override_fnt_size = pcfg.let_fntsize_flag == 1
        override_fnt_stroke = pcfg.let_fntstroke_flag == 1
        override_fnt_color = pcfg.let_fntcolor_flag == 1
        override_fnt_scolor = pcfg.let_fnt_scolor_flag == 1
        override_alignment = pcfg.let_alignment_flag == 1
        override_effect = pcfg.let_fnteffect_flag == 1
        override_writing_mode = pcfg.let_writing_mode_flag == 1
        override_font_family = pcfg.let_family_flag == 1
        
        for ii, blk in enumerate(blk_list):
            if run_wo_textstyle_update and backup_blkstyles is not None and ii < len(backup_blkstyles):
                blk.fontformat.merge(backup_blkstyles[ii])
            else:
                if override_fnt_size or blk.font_size < 0:
                    blk.font_size = global_format.font_size
                elif blk._detected_font_size > 0 and not pcfg.module.enable_detect:
                    blk.font_size = blk._detected_font_size
                
                if override_fnt_stroke:
                    blk.stroke_width = global_format.stroke_width
                elif pcfg.module.enable_ocr:
                    blk.recalulate_stroke_width()
                
                if override_fnt_color:
                    blk.set_font_colors(fg_colors=global_format.frgb)
                if override_fnt_scolor:
                    blk.set_font_colors(bg_colors=global_format.srgb)
                if override_alignment:
                    blk.alignment = global_format.alignment
                elif pcfg.module.enable_detect and not blk.src_is_vertical:
                    blk.recalulate_alignment()
                
                if override_effect:
                    blk.opacity = global_format.opacity
                    blk.shadow_color = global_format.shadow_color
                    blk.shadow_radius = global_format.shadow_radius
                    blk.shadow_strength = global_format.shadow_strength
                    blk.shadow_offset = global_format.shadow_offset
                
                if override_writing_mode:
                    blk.vertical = global_format.vertical
                if override_font_family or blk.font_family is None:
                    blk.font_family = global_format.font_family
                
                blk.line_spacing = global_format.line_spacing
                blk.letter_spacing = global_format.letter_spacing
                blk.italic = global_format.italic
                blk.bold = global_format.bold
                blk.underline = global_format.underline
                
                sw = blk.stroke_width
                if sw > 0 and pcfg.module.enable_ocr and pcfg.module.enable_detect and not override_fnt_size:
                    blk.font_size = blk.font_size / (1 + sw)
    
    def prepare_pages_for_translation(self, pages: Dict[str, List[TextBlock]]):
        """
        Подготавливает страницы к переводу.
        
        Args:
            pages: Словарь страниц
        """
        all_disabled = pcfg.module.all_stages_disabled()
        
        if pcfg.module.enable_detect:
            for page in pages:
                if not pcfg.module.keep_exist_textlines:
                    self._proj.pages[page].clear()
        else:
            textblk: TextBlock = None
            for blklist in pages.values():
                for textblk in blklist:
                    if pcfg.module.enable_ocr:
                        textblk.text = []
                        textblk.set_font_colors((0, 0, 0), (0, 0, 0))
                    if pcfg.module.enable_translate or (all_disabled and not self._run_imgtrans_wo_textstyle_update) or pcfg.module.enable_ocr:
                        textblk.rich_text = ''
                    textblk.vertical = textblk.src_is_vertical
