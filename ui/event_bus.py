"""
EventBus — центральная шина событий для слабой связанности.

Вместо прямых подписок между виджетами, все коммуникации
проходят через EventBus.
"""

from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict


class EventBus:
    """
    Центральная шина событий (Singleton).

    Responsibilities:
    - Публикация событий от компонентов
    - Подписка компонентов на события
    - Декомпозиция связей между виджетами

    Pattern: Publish-Subscribe (Mediator)
    """

    _instance: Optional['EventBus'] = None

    @classmethod
    def get_instance(cls) -> 'EventBus':
        """Возвращает единственную INSTANCE шины событий."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Сбрасывает singleton (для тестов)."""
        cls._instance = None

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._event_count: Dict[str, int] = defaultdict(int)

    def subscribe(self, event: str, handler: Callable) -> None:
        """
        Подписывается на событие.

        Args:
            event: Имя события
            handler: Обработчик (callable)
        """
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        """
        Отписывается от события.

        Args:
            event: Имя события
            handler: Обработчик для удаления
        """
        if event in self._handlers:
            try:
                self._handlers[event].remove(handler)
            except ValueError:
                pass

    def publish(self, event: str, data: Any = None) -> None:
        """
        Публикует событие.

        Args:
            event: Имя события
            data: Данные события (опционально)
        """
        self._event_count[event] += 1

        for handler in self._handlers.get(event, []):
            try:
                handler(data)
            except Exception as e:
                import logging
                logging.getLogger('EventBus').error(
                    f"Error in handler for '{event}': {e}"
                )

    def has_subscribers(self, event: str) -> bool:
        """Проверяет, есть ли подписчики на событие."""
        return bool(self._handlers.get(event))

    def get_subscriber_count(self, event: str) -> int:
        """Возвращает количество подписчиков на событие."""
        return len(self._handlers.get(event, []))

    def get_event_stats(self) -> Dict[str, int]:
        """Возвращает статистику по событиям."""
        return dict(self._event_count)

    def clear(self) -> None:
        """Очищает все подписки."""
        self._handlers.clear()
        self._event_count.clear()


# Стандартные имена событий
class Events:
    """Константы для имен событий."""

    # Навигация
    NAVIGATE_NEXT = "navigate_next"
    NAVIGATE_PREV = "navigate_prev"

    # Блоки
    DELETE_TEXT_BLOCKS = "delete_text_blocks"
    COPY_TEXT_BLOCKS = "copy_text_blocks"
    PASTE_TEXT_BLOCKS = "paste_text_blocks"
    FORMAT_TEXT_BLOCKS = "format_text_blocks"
    LAYOUT_TEXT_BLOCKS = "layout_text_blocks"

    # Выделение
    SELECTION_CHANGED = "selection_changed"
    BLOCK_SELECTED = "block_selected"
    BLOCK_DESELECTED = "block_deselected"

    # Редактирование
    TEXT_EDIT_STARTED = "text_edit_started"
    TEXT_EDIT_ENDED = "text_edit_ended"
    TEXT_CHANGED = "text_changed"

    # Undo/Redo
    UNDO = "undo"
    REDO = "redo"

    # Рисование
    DRAW_MODE_CHANGED = "draw_mode_changed"
    INPAINT_STARTED = "inpaint_started"
    INPAINT_FINISHED = "inpaint_finished"

    # Страницы
    PAGE_CHANGED = "page_changed"
    PAGE_SAVED = "page_saved"

    # Модули
    MODULE_SET_DETECTOR = "module_set_detector"
    MODULE_SET_OCR = "module_set_ocr"
    MODULE_SET_TRANSLATOR = "module_set_translator"
    MODULE_SET_INPAINTER = "module_set_inpainter"

    # Масштаб
    SCALE_CHANGED = "scale_changed"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"

    # Прозрачность
    TRANSPARENCY_CHANGED = "transparency_changed"

    # Страницы (продолжение)
    PAGE_CHANGING = "page_changing"      # Начало смены страницы

    # Проект
    PROJECT_OPENED = "project_opened"    # Проект открыт
    PROJECT_CLOSED = "project_closed"    # Проект закрыт
    PROJECT_SAVED = "project_saved"      # Проект сохранён

    # Режимы
    MODE_CHANGED = "mode_changed"        # Смена режима (textedit/draw/textblock)
