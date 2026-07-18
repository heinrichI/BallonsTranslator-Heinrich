"""
TranslationPipeline — бизнес-логика перевода.

Извлечён из MainWindow для уменьшения размера класса.
"""

from typing import List, Optional
import numpy as np

from utils.logger import logger as LOGGER
from utils.text_processing import is_cjk, full_len, half_len
from utils.textblock import TextBlock
from utils.config import pcfg
from utils import shared


def postprocess_translations(text_list: List[str]) -> List[str]:
    """
    Пост-обработка переводов после MT.

    - Конвертация CJK символов
    - Очистка пунктуации
    - Замена ключевых слов

    Args:
        text_list: Список текстов для обработки

    Returns:
        Обработанный список текстов
    """
    result = []

    # Загружаем замены ключевых слов
    keyword_subs = {}
    if hasattr(pcfg, 'trans_config') and hasattr(pcfg.trans_config, 'keyword_subs'):
        keyword_subs = pcfg.trans_config.keyword_subs

    for text in text_list:
        if not text:
            result.append(text)
            continue

        # Конвертация CJK символов
        if pcfg.full_to_half:
            text = half_len(text)
        elif pcfg.half_to_full:
            text = full_len(text)

        # Замена ключевых слов
        if keyword_subs:
            for old, new in keyword_subs.items():
                text = text.replace(old, new)

        result.append(text)

    return result


def translate_blkitem_list(
    blk_items: list,
    src_texts: List[str],
    translator,
    src_lang: str = 'eng',
    tgt_lang: str = 'chs'
) -> List[str]:
    """
    Перевод списка текстовых блоков.

    Args:
        blk_items: Список TextBlkItem
        src_texts: Исходные тексты
        translator: Объект переводчика
        src_lang: Язык источника
        tgt_lang: Язык назначения

    Returns:
        Список переведённых текстов
    """
    if not src_texts:
        return []

    # Фильтруем пустые тексты
    valid_indices = []
    valid_texts = []
    for i, text in enumerate(src_texts):
        if text and text.strip():
            valid_indices.append(i)
            valid_texts.append(text)

    if not valid_texts:
        return [''] * len(src_texts)

    # Переводим
    translated = translator.translate(valid_texts, src_lang, tgt_lang)

    # Восстанавливаем порядок
    result = [''] * len(src_texts)
    for i, idx in enumerate(valid_indices):
        if i < len(translated):
            result[idx] = translated[i]

    return result


def apply_font_format_overrides(
    blk_items: list,
    font_format_overrides: Optional[dict] = None
):
    """
    Применяет переопределения шрифтов к блокам.

    Args:
        blk_items: Список TextBlkItem
        font_format_overrides: Словарь переопределений {idx: FontFormat}
    """
    if not font_format_overrides:
        return

    for idx, fmt in font_format_overrides.items():
        if 0 <= idx < len(blk_items):
            blk_items[idx].set_fontformat(fmt)


def finish_translate_page(
    blk_items: list,
    translations: List[str],
    auto_textlayout: bool = True
):
    """
    Завершает перевод страницы — применяет тексты к блокам.

    Args:
        blk_items: Список TextBlkItem
        translations: Список переведённых текстов
        auto_textlayout: Включить автоматический layout
    """
    for i, (blk_item, text) in enumerate(zip(blk_items, translations)):
        if text and text.strip():
            blk_item.setPlainText(text)
            blk_item.blk.translation = text

            # Автоматический layout если включен
            if auto_textlayout and not blk_item.fontformat.vertical:
                #这里会调用 layout manager
                pass


def run_ocr_postprocess(texts: List[str], keyword_subs: Optional[dict] = None) -> List[str]:
    """
    Пост-обработка OCR текстов.

    Args:
        texts: Список текстов от OCR
        keyword_subs: Замены ключевых слов

    Returns:
        Обработанные тексты
    """
    if not keyword_subs:
        return texts

    result = []
    for text in texts:
        for old, new in keyword_subs.items():
            text = text.replace(old, new)
        result.append(text)

    return result


def run_translate_preprocess(texts: List[str], keyword_subs: Optional[dict] = None) -> List[str]:
    """
    Пред-обработка текстов перед переводом.

    Args:
        texts: Список текстов
        keyword_subs: Замены ключевых слов

    Returns:
        Обработанные тексты
    """
    if not keyword_subs:
        return texts

    result = []
    for text in texts:
        for old, new in keyword_subs.items():
            text = text.replace(old, new)
        result.append(text)

    return result


def run_translate_postprocess(texts: List[str], keyword_subs: Optional[dict] = None) -> List[str]:
    """
    Пост-обработка текстов после перевода.

    Args:
        texts: Список текстов
        keyword_subs: Замены ключевых слов

    Returns:
        Обработанные тексты
    """
    if not keyword_subs:
        return texts

    result = []
    for text in texts:
        for old, new in keyword_subs.items():
            text = text.replace(old, new)
        result.append(text)

    return result
