"""
KeyboardShortcutManager — управление горячими клавишами.

Извлечён из MainWindow для уменьшения размера класса.
"""

from functools import partial
from qtpy.QtWidgets import QApplication, QShortcut
from qtpy.QtGui import QKeySequence

from utils import shared
from .misc import QKEY


class KeyboardShortcutManager:
    """
    Управляет горячими клавишами приложения.

    Responsibilities:
    - Настройка всех горячих клавиш
    - Обработка нажатий клавиш
    """

    def __init__(self, mainwindow):
        """
        Args:
            mainwindow: MainWindow — главное окно
        """
        self.mw = mainwindow
        self.app = mainwindow.app
        self._shortcuts = []

    def setup_shortcuts(self):
        """Настраивает все горячие клавиши."""
        # TitleBar shortcuts
        self.mw.titleBar.nextpage_trigger.connect(self._shortcut_next)
        self.mw.titleBar.prevpage_trigger.connect(self._shortcut_before)
        self.mw.titleBar.textedit_trigger.connect(self._shortcut_textedit)
        self.mw.titleBar.drawboard_trigger.connect(self._shortcut_drawboard)
        self.mw.titleBar.redo_trigger.connect(self.mw.canvas.redo)
        self.mw.titleBar.undo_trigger.connect(self.mw.canvas.undo)
        self.mw.titleBar.page_search_trigger.connect(self.mw.on_page_search)
        self.mw.titleBar.global_search_trigger.connect(self.mw.on_global_search)
        self.mw.titleBar.replacePreMTkeyword_trigger.connect(self.mw.show_pre_MT_keyword_window)
        self.mw.titleBar.replaceMTkeyword_trigger.connect(self.mw.show_MT_keyword_window)
        self.mw.titleBar.replaceOCRkeyword_trigger.connect(self.mw.show_OCR_keyword_window)
        self.mw.titleBar.run_trigger.connect(self.mw.leftBar.runImgtransBtn.click)
        self.mw.titleBar.run_woupdate_textstyle_trigger.connect(self.mw.run_imgtrans_wo_textstyle_update)
        self.mw.titleBar.translate_page_trigger.connect(self.mw.on_transpagebtn_pressed)
        self.mw.titleBar.enable_module.connect(self.mw.on_enable_module)
        self.mw.titleBar.importtstyle_trigger.connect(self.mw.import_tstyles)
        self.mw.titleBar.exporttstyle_trigger.connect(self.mw.export_tstyles)
        self.mw.titleBar.darkmode_trigger.connect(self.mw.on_darkmode_triggered)

        # Navigation shortcuts
        self._add_shortcut("A", self._shortcut_before)
        self._add_shortcut(QKeySequence.StandardKey.MoveToPreviousPage, self._shortcut_before)
        self._add_shortcut("D", self._shortcut_next)
        self._add_shortcut(QKeySequence.StandardKey.MoveToNextPage, self._shortcut_next)
        self._add_shortcut("W", self._shortcut_textblock)
        self._add_shortcut(QKeySequence.StandardKey.ZoomIn, self.mw.canvas.gv.scale_up_signal)
        self._add_shortcut(QKeySequence.StandardKey.ZoomOut, self.mw.canvas.gv.scale_down_signal)
        self._add_shortcut("Ctrl+D", self._shortcut_ctrl_d)
        self._add_shortcut("Space", self._shortcut_space)
        self._add_shortcut(QKeySequence.StandardKey.SelectAll, self._shortcut_select_all)
        self._add_shortcut("Escape", self._shortcut_escape)

        # Format shortcuts
        self._add_shortcut(QKeySequence.StandardKey.Bold, self._shortcut_bold)
        self._add_shortcut(QKeySequence.StandardKey.Italic, self._shortcut_italic)
        self._add_shortcut(QKeySequence.StandardKey.Underline, self._shortcut_underline)
        self._add_shortcut(QKeySequence.StandardKey.Delete, self._shortcut_delete)

        # Drawing panel shortcuts
        drawpanel_shortcuts = {'hand': 'H', 'rect': 'R', 'inpaint': 'J', 'pen': 'B'}
        for tool_name, shortcut_key in drawpanel_shortcuts.items():
            shortcut = QShortcut(QKeySequence(shortcut_key), self.mw)
            shortcut.activated.connect(partial(self.mw.drawingPanel.shortcutSetCurrentToolByName, tool_name))
            self.mw.drawingPanel.setShortcutTip(tool_name, shortcut_key)

    def _add_shortcut(self, key, slot):
        """Добавляет горячую клавишу."""
        shortcut = QShortcut(QKeySequence(key), self.mw)
        shortcut.activated.connect(slot)
        self._shortcuts.append(shortcut)

    def _check_sender_key(self, expected_key: str) -> bool:
        """Проверяет, была ли нажата определённая клавиша."""
        from qtpy.QtWidgets import QShortcut as QS
        sender = self.mw.sender()
        if isinstance(sender, QS):
            if sender.key() == expected_key:
                if self.mw.canvas.editing_textblkitem is not None:
                    return True
        return False

    def _shortcut_next(self):
        """Следующий блок или страница."""
        if self._check_sender_key(QKEY.Key_D):
            return
        if self.mw.centralStackWidget.currentIndex() == 0:
            focus_widget = self.app.focusWidget()
            if self.mw.st_manager.is_editting():
                self.mw.st_manager.on_switch_textitem(1)
            elif isinstance(focus_widget, (self.mw.st_manager.pairwidget_list[0].e_trans.__class__
                                          if self.mw.st_manager.pairwidget_list else tuple())):
                self.mw.st_manager.on_switch_textitem(1, current_editing_widget=focus_widget)
            else:
                index = self.mw.pageList.currentIndex()
                page_count = self.mw.pageList.count()
                if index.isValid():
                    row = index.row()
                    row = (row + 1) % page_count
                    self.mw.pageList.setCurrentRow(row)

    def _shortcut_before(self):
        """Предыдущий блок или страница."""
        if self._check_sender_key(QKEY.Key_A):
            return
        if self.mw.centralStackWidget.currentIndex() == 0:
            focus_widget = self.app.focusWidget()
            if self.mw.st_manager.is_editting():
                self.mw.st_manager.on_switch_textitem(-1)
            elif isinstance(focus_widget, (self.mw.st_manager.pairwidget_list[0].e_trans.__class__
                                          if self.mw.st_manager.pairwidget_list else tuple())):
                self.mw.st_manager.on_switch_textitem(-1, current_editing_widget=focus_widget)
            else:
                index = self.mw.pageList.currentIndex()
                page_count = self.mw.pageList.count()
                if index.isValid():
                    row = index.row()
                    row = (row - 1 + page_count) % page_count
                    self.mw.pageList.setCurrentRow(row)

    def _shortcut_textedit(self):
        """Переключение в режим редактирования текста."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            self.mw.bottomBar.texteditChecker.click()

    def _shortcut_textblock(self):
        """Переключение в режим текстового блока."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            if self.mw.bottomBar.texteditChecker.isChecked():
                self.mw.bottomBar.textblockChecker.click()

    def _shortcut_drawboard(self):
        """Переключение в режим рисования."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            self.mw.bottomBar.paintChecker.click()

    def _shortcut_ctrl_d(self):
        """Удаление текущего блока."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            if self.mw.drawingPanel.isVisible():
                if self.mw.drawingPanel.currentTool == self.mw.drawingPanel.rectTool:
                    self.mw.drawingPanel.rectPanel.delete_btn.click()
            elif self.mw.canvas.textEditMode():
                self.mw.canvas.delete_textblks.emit(0)

    def _shortcut_select_all(self):
        """Выделить все блоки."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            if self.mw.textPanel.isVisible():
                self.mw.st_manager.set_blkitems_selection(True)

    def _shortcut_space(self):
        """Пробел — инпейнт в режиме rect."""
        if self.mw.centralStackWidget.currentIndex() == 0:
            if self.mw.drawingPanel.isVisible():
                if self.mw.drawingPanel.currentTool == self.mw.drawingPanel.rectTool:
                    self.mw.drawingPanel.rectPanel.inpaint_btn.click()

    def _shortcut_bold(self):
        """Жирный текст."""
        if self.mw.textPanel.formatpanel.isVisible():
            self.mw.textPanel.formatpanel.formatBtnGroup.boldBtn.click()

    def _shortcut_italic(self):
        """Курсив."""
        if self.mw.textPanel.formatpanel.isVisible():
            self.mw.textPanel.formatpanel.formatBtnGroup.italicBtn.click()

    def _shortcut_underline(self):
        """Подчёркивание."""
        if self.mw.textPanel.formatpanel.isVisible():
            self.mw.textPanel.formatpanel.formatBtnGroup.underlineBtn.click()

    def _shortcut_delete(self):
        """Удалить выделенные блоки."""
        if self.mw.canvas.gv.isVisible():
            self.mw.canvas.delete_textblks.emit(1)

    def _shortcut_escape(self):
        """Escape — отмена текущего действия."""
        if self.mw.drawingPanel.isVisible():
            if self.mw.drawingPanel.rectPanel.rect_drawing:
                self.mw.drawingPanel.rectPanel.cancel_rect_drawing()
