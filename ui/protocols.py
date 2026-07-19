"""
Protocols — интерфейсы для слабой связанности.

Определяет контракты между компонентами без привязки к конкретным реализациям.
"""

from typing import Protocol, List, Optional, Any, runtime_checkable
from qtpy.QtCore import QObject


@runtime_checkable
class ICanvasView(Protocol):
    """Интерфейс для Canvas (View)."""

    def textEditMode(self) -> bool:
        """Проверяет, включен ли режим редактирования текста."""
        ...

    def selected_text_items(self, sort: bool = True) -> List:
        """Возвращает список выделенных текстовых элементов."""
        ...

    def push_undo_command(self, command: Any) -> None:
        """Добавляет команду в стек undo."""
        ...

    def ensure_visible(self, item: Any) -> None:
        """Делает элемент видимым."""
        ...

    def set_text_layer_visible(self, visible: bool) -> None:
        """Управляет видимостью текстового слоя."""
        ...

    def get_image_array(self) -> Any:
        """Возвращает numpy массив изображения."""
        ...

    def get_inpainted_array(self) -> Any:
        """Возвращает numpy массив инпейнта."""
        ...

    def get_mask_array(self) -> Any:
        """Возвращает numpy массив маски."""
        ...

    def set_drag_mode(self, mode: Any) -> None:
        """Устанавливает режим перетаскивания."""
        ...

    def add_item_to_text_layer(self, item: Any) -> None:
        """Добавляет элемент на текстовый слой."""
        ...

    def remove_item(self, item: Any) -> None:
        """Удаляет элемент со сцены."""
        ...


@runtime_checkable
class ITextEditListView(Protocol):
    """Интерфейс для TextEditListScrollArea."""

    def set_selected_list(self, indices: List[int]) -> None:
        """Устанавливает список выделенных индексов."""
        ...

    def ensureWidgetVisible(self, widget: Any, **kwargs) -> None:
        """Делает виджет видимым в области прокрутки."""
        ...

    def removeWidget(self, widget: Any) -> None:
        """Удаляет виджет из списка."""
        ...

    def insertPairWidget(self, widget: Any, index: int) -> None:
        """Вставляет виджет по индексу."""
        ...

    def addPairWidget(self, widget: Any) -> None:
        """Добавляет виджет в список."""
        ...

    def clearAllSelected(self) -> None:
        """Очищает все выделения."""
        ...

    @property
    def checked_list(self) -> List:
        """Возвращает список выделенных виджетов."""
        ...

    @property
    def pairwidget_list(self) -> List:
        """Возвращает список pair widgets."""
        ...


@runtime_checkable
class IFormatPanel(Protocol):
    """Интерфейс для FontFormatPanel."""

    def set_textblk_item(self, item: Any = None, multi_select: bool = False) -> None:
        """Устанавливает текущий текстовый блок."""
        ...

    @property
    def global_format(self) -> Any:
        """Возвращает глобальный формат."""
        ...

    def global_mode(self) -> bool:
        """Проверяет, включен ли глобальный режим."""
        ...

    def set_active_format(self, fmt: Any) -> None:
        """Устанавливает активный формат."""
        ...

    def deactivate_style_label(self) -> None:
        """Деактивирует метку стиля."""
        ...

    def on_active_textstyle_label_changed(self) -> None:
        """Обработчик изменения активной метки стиля."""
        ...


@runtime_checkable
class IBlockManager(Protocol):
    """Интерфейс для BlockManager."""

    @property
    def textblk_item_list(self) -> List:
        """Возвращает список текстовых блоков."""
        ...

    @property
    def pairwidget_list(self) -> List:
        """Возвращает список pair widgets."""
        ...

    def update_textblk_item_idx(self, sel_ids: Optional[set] = None) -> None:
        """Обновляет индексы текстовых блоков."""
        ...

    def update_textblk_list(self, imgtrans_proj: Any) -> None:
        """Синхронизирует блоки с моделью данных."""
        ...

    def clear_all(self) -> None:
        """Очищает все блоки."""
        ...


@runtime_checkable
class ISelectionManager(Protocol):
    """Интерфейс для SelectionManager."""

    def on_incanvas_selection_changed(self) -> None:
        """Обработчик изменения выделения на Canvas."""
        ...

    def on_transwidget_selection_changed(self) -> None:
        """Обработчик изменения выделения в TextEditList."""
        ...

    def change_hovering_widget(self, widget: Any) -> None:
        """Изменяет текущий наведенный виджет."""
        ...

    def get_hovering_widget(self) -> Any:
        """Возвращает текущий наведенный виджет."""
        ...

    def clear_hovering(self) -> None:
        """Очищает состояние наведения."""
        ...
