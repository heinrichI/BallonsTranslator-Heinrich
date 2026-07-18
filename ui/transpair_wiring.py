"""
TransPairWiring — извлечённый из SceneTextManager.

Содержит логику подключения сигналов TransPairWidget к текстовым блокам.
Уменьшает связанность между SceneTextManager и TransPairWidget.

НЕ зависит от business logic — только от View interfaces.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .scenetext_manager import SceneTextManager
    from .textedit_area import TransPairWidget
    from .textitem import TextBlkItem


class TransPairWiring:
    """
    Подключение сигналов TransPairWidget к текстовым блокам.
    
    Responsibilities:
    - Подключение сигналов focus_in, propagate_user_edited и т.д.
    - Обновление текста в TransPairWidget при изменении блока
    """

    def __init__(self, manager: 'SceneTextManager'):
        """
        Args:
            manager: SceneTextManager для доступа к обработчикам сигналов
        """
        self._manager = manager

    def wire_signals(self, pair_widget: 'TransPairWidget', blk_item: 'TextBlkItem') -> None:
        """
        Подключает сигналы TransPairWidget к обработчикам SceneTextManager.
        
        Args:
            pair_widget: TransPairWidget для подключения
            blk_item: TextBlkItem для инициализации текста
        """
        # Установка текста
        pair_widget.e_source.setPlainText(blk_item.blk.get_text())
        pair_widget.e_trans.setPlainText(blk_item.toPlainText())

        # Подключение сигналов e_source
        pair_widget.e_source.focus_in.connect(self._manager.on_transwidget_focus_in)
        pair_widget.e_source.ensure_scene_visible.connect(self._manager.on_ensure_textitem_svisible)
        pair_widget.e_source.push_undo_stack.connect(self._manager.on_push_edit_stack)
        pair_widget.e_source.redo_signal.connect(self._manager.on_textedit_redo)
        pair_widget.e_source.undo_signal.connect(self._manager.on_textedit_undo)
        pair_widget.e_source.show_select_menu.connect(self._manager.on_show_select_menu)
        pair_widget.e_source.focus_out.connect(self._manager.on_pairw_focusout)
        pair_widget.e_source.text_changed.connect(self._manager._on_source_text_changed)

        # Подключение сигналов e_trans
        pair_widget.e_trans.focus_in.connect(self._manager.on_transwidget_focus_in)
        pair_widget.e_trans.propagate_user_edited.connect(self._manager.on_propagate_transwidget_edit)
        pair_widget.e_trans.ensure_scene_visible.connect(self._manager.on_ensure_textitem_svisible)
        pair_widget.e_trans.push_undo_stack.connect(self._manager.on_push_edit_stack)
        pair_widget.e_trans.redo_signal.connect(self._manager.on_textedit_redo)
        pair_widget.e_trans.undo_signal.connect(self._manager.on_textedit_undo)
        pair_widget.e_trans.show_select_menu.connect(self._manager.on_show_select_menu)
        pair_widget.e_trans.focus_out.connect(self._manager.on_pairw_focusout)

        # Подключение сигналов pair_widget
        pair_widget.drag_move.connect(self._manager.textEditList.handle_drag_pos)
        pair_widget.pw_drop.connect(self._manager.textEditList.on_pw_dropped)
        pair_widget.idx_edited.connect(self._manager.textEditList.on_idx_edited)
