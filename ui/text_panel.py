import copy
import inspect
import logging
import sys
from typing import List, Optional

LOGGER = logging.getLogger('BallonTranslator')

QUIET_UI = True  # Set to False for verbose UI debug logging

def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)

DEBUG_FONTSIZE = False  # Set to True for font size debug logging

_LOG_TARGET = "BUT OF COURSE!"

def _is_log_target(blk):
    if not DEBUG_FONTSIZE:
        return False
    if blk is None:
        return False
    try:
        text = blk.get_text() if hasattr(blk, 'get_text') else ''
        return text.startswith(_LOG_TARGET)
    except Exception:
        return False

from qtpy.QtWidgets import QLineEdit, QSizePolicy, QHBoxLayout, QVBoxLayout, QFrame, QFontComboBox, QApplication, QPushButton, QLabel, QGroupBox, QCheckBox, QSlider, QListWidget, QWidget
from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QFocusEvent, QMouseEvent, QTextCursor, QKeyEvent, QColor
from qtpy import sip

from utils import shared
from utils import config as C
from utils.fontformat import FontFormat, px2pt, LineSpacingType
from .custom_widget import Widget, ColorPickerLabel, ClickableLabel, CheckableLabel, TextCheckerLabel, AlignmentChecker, QFontChecker, SizeComboBox, SizeControlLabel
from .textitem import TextBlkItem
from .text_advanced_format import TextAdvancedFormatPanel, WordListPanel
from .text_style_presets import TextStylePresetPanel
from . import funcmaps as FM


class LineEdit(QLineEdit):

    return_pressed_wochange = Signal()
    return_pressed = Signal()

    def __init__(self, content: str = None, parent = None):
        super().__init__(content, parent)
        self.textChanged.connect(self.on_text_changed)
        self._text_changed = False
        self.editingFinished.connect(self.on_editing_finished)
        # self.returnPressed.connect(self.on_return_pressed)

    def on_text_changed(self):
        self._text_changed = True

    def on_editing_finished(self):
        self._text_changed = False

    def focusOutEvent(self, e: QFocusEvent) -> None:
        self._text_changed = False
        return super().focusOutEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        super().keyPressEvent(e)
        if e.key() == Qt.Key.Key_Return:
            self.return_pressed.emit()
            if not self._text_changed:
                self.return_pressed_wochange.emit()


class IncrementalBtn(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFixedSize(13, 13)


class AlignmentBtnGroup(QFrame):
    param_changed = Signal(str, int)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alignLeftChecker = AlignmentChecker(self)
        self.alignLeftChecker.clicked.connect(self.alignBtnPressed)
        self.alignCenterChecker = AlignmentChecker(self)
        self.alignCenterChecker.clicked.connect(self.alignBtnPressed)
        self.alignRightChecker = AlignmentChecker(self)
        self.alignRightChecker.clicked.connect(self.alignBtnPressed)
        self.alignLeftChecker.setObjectName("AlignLeftChecker")
        self.alignRightChecker.setObjectName("AlignRightChecker")
        self.alignCenterChecker.setObjectName("AlignCenterChecker")

        hlayout = QHBoxLayout(self)
        hlayout.addWidget(self.alignLeftChecker)
        hlayout.addWidget(self.alignCenterChecker)
        hlayout.addWidget(self.alignRightChecker)
        hlayout.setSpacing(0)

    def alignBtnPressed(self):
        btn = self.sender()
        if btn == self.alignLeftChecker:
            self.alignLeftChecker.setChecked(True)
            self.alignCenterChecker.setChecked(False)
            self.alignRightChecker.setChecked(False)
            self.param_changed.emit('alignment', 0)
        elif btn == self.alignRightChecker:
            self.alignRightChecker.setChecked(True)
            self.alignCenterChecker.setChecked(False)
            self.alignLeftChecker.setChecked(False)
            self.param_changed.emit('alignment', 2)
        else:
            self.alignCenterChecker.setChecked(True)
            self.alignLeftChecker.setChecked(False)
            self.alignRightChecker.setChecked(False)
            self.param_changed.emit('alignment', 1)
    
    def setAlignment(self, alignment: int):
        if alignment == 0:
            self.alignLeftChecker.setChecked(True)
            self.alignCenterChecker.setChecked(False)
            self.alignRightChecker.setChecked(False)
        elif alignment == 1:
            self.alignLeftChecker.setChecked(False)
            self.alignCenterChecker.setChecked(True)
            self.alignRightChecker.setChecked(False)
        else:
            self.alignLeftChecker.setChecked(False)
            self.alignCenterChecker.setChecked(False)
            self.alignRightChecker.setChecked(True)


class FormatGroupBtn(QFrame):
    param_changed = Signal(str, bool)
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.boldBtn = QFontChecker(self)
        self.boldBtn.setObjectName("FontBoldChecker")
        self.boldBtn.clicked.connect(self.setBold)
        self.italicBtn = QFontChecker(self)
        self.italicBtn.setObjectName("FontItalicChecker")
        self.italicBtn.clicked.connect(self.setItalic)
        self.underlineBtn = QFontChecker(self)
        self.underlineBtn.setObjectName("FontUnderlineChecker")
        self.underlineBtn.clicked.connect(self.setUnderline)
        hlayout = QHBoxLayout(self)
        hlayout.addWidget(self.boldBtn)
        hlayout.addWidget(self.italicBtn)
        hlayout.addWidget(self.underlineBtn)
        hlayout.setSpacing(0)

    def setBold(self):
        self.param_changed.emit('bold', self.boldBtn.isChecked())

    def setItalic(self):
        self.param_changed.emit('italic', self.italicBtn.isChecked())

    def setUnderline(self):
        self.param_changed.emit('underline', self.underlineBtn.isChecked())
    

class FontSizeBox(QFrame):
    param_changed = Signal(str, float)
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.upBtn = IncrementalBtn(self)
        self.upBtn.setObjectName("FsizeIncrementUp")
        self.downBtn = IncrementalBtn(self)
        self.downBtn.setObjectName("FsizeIncrementDown")
        self.upBtn.clicked.connect(self.onUpBtnClicked)
        self.downBtn.clicked.connect(self.onDownBtnClicked)
        self.fcombobox = SizeComboBox([1, 1000], 'font_size', self)
        self.fcombobox.addItems([
            "5", "5.5", "6.5", "7.5", "8", "9", "10", "10.5",
            "11", "12", "14", "16", "18", "20", '22', "26", "28",
            "36", "48", "56", "72", "93", "123", "163"
        ])
        self.fcombobox.param_changed.connect(self.param_changed)

        hlayout = QHBoxLayout(self)
        vlayout = QVBoxLayout()
        vlayout.addWidget(self.upBtn)
        vlayout.addWidget(self.downBtn)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(0)
        hlayout.addLayout(vlayout)
        hlayout.addWidget(self.fcombobox)
        hlayout.setSpacing(3)
        hlayout.setContentsMargins(0, 0, 0, 0)

    def getFontSize(self) -> str:
        return self.fcombobox.currentText()

    def onUpBtnClicked(self):
        raito = 1.25
        size = self.getFontSize()
        multi_size=False
        if "+" in size:
            size = size.strip("+")
            multi_size=True
        size = float(size)
        newsize = int(round(size * raito))
        if newsize == size:
            newsize += 1
        newsize = min(1000, newsize)
        if newsize != size:
            if not multi_size:
                self.param_changed.emit('font_size', newsize)
                self.fcombobox.setCurrentText(str(newsize))
            else:
                self.param_changed.emit('rel_font_size', raito)
                self.fcombobox.setCurrentText(str(newsize)+"+")

    def onDownBtnClicked(self):
        raito = 0.75
        size = self.getFontSize()
        multi_size=False
        if "+" in size:
            size = size.strip("+")
            multi_size=True
        size = float(size)
        newsize = int(round(size * raito))
        if newsize == size:
            newsize -= 1
        newsize = max(1, newsize)
        if newsize != size:
            if not multi_size:
                self.param_changed.emit('font_size', newsize)
                self.fcombobox.setCurrentText(str(newsize))
            else:
                self.param_changed.emit('rel_font_size', raito)
                self.fcombobox.setCurrentText(str(newsize)+"+")
    

class FontFamilyComboBox(QFontComboBox):
    param_changed = Signal(str, object)
    def __init__(self, emit_if_focused=True, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.currentFontChanged.connect(self.on_fontfamily_changed)
        self.lineedit = lineedit = LineEdit(parent=self)
        lineedit.return_pressed.connect(self.on_return_pressed)
        self.setLineEdit(lineedit)
        self.emit_if_focused = emit_if_focused
        self.return_pressed = False
        
    def apply_fontfamily(self):
        ffamily = self.currentFont().family()
        if ffamily in shared.FONT_FAMILIES:
            self.param_changed.emit('font_family', ffamily)

    def update_font_list(self, font_list):
        self.currentFontChanged.disconnect(self.on_fontfamily_changed)
        current_font = self.currentFont().family()
        self.clear()
        self.addItems(font_list)
        self.addItems([current_font])
        self.setCurrentText(current_font)
        self.currentFontChanged.connect(self.on_fontfamily_changed)

    def on_return_pressed(self):
        self.return_pressed = True
        self.apply_fontfamily()

    def on_fontfamily_changed(self):
        if self.return_pressed:
            self.return_pressed = False
        else:
            self.apply_fontfamily()


class FontFormatPanel(Widget):
    
    textblk_item: TextBlkItem = None
    text_cursor: QTextCursor = None
    global_format: FontFormat = None
    restoring_textblk: bool = False

    def __init__(self, app: QApplication, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.app = app

        self.vlayout = QVBoxLayout(self)
        self.vlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.familybox = FontFamilyComboBox(emit_if_focused=True, parent=self)
        self.familybox.setContentsMargins(0, 0, 0, 0)
        self.familybox.setObjectName("FontFamilyBox")
        self.familybox.setToolTip(self.tr("Font Family"))
        self.familybox.param_changed.connect(self.on_param_changed)
        self.familybox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.fontsizebox = FontSizeBox(self)
        self.fontsizebox.setToolTip(self.tr("Font Size"))
        self.fontsizebox.setObjectName("FontSizeBox")
        self.fontsizebox.fcombobox.setToolTip(self.tr("Change font size"))
        self.fontsizebox.param_changed.connect(self.on_param_changed)
        self.fontsizebox.fcombobox.installEventFilter(self)
        
        self.lineSpacingLabel = SizeControlLabel(self, direction=1, transparent_bg=False)
        self.lineSpacingLabel.setObjectName("lineSpacingLabel")
        self.lineSpacingLabel.size_ctrl_changed.connect(self.onLineSpacingCtrlChanged)
        self.lineSpacingLabel.btn_released.connect(lambda : self.on_param_changed('line_spacing', self.lineSpacingBox.value()))

        self.lineSpacingBox = SizeComboBox([0, 100], 'line_spacing', self)
        self.lineSpacingBox.addItems(["1.0", "1.1", "1.2"])
        self.lineSpacingBox.setToolTip(self.tr("Change line spacing"))
        self.lineSpacingBox.param_changed.connect(self.on_param_changed)
        
        self.colorPicker = ColorPickerLabel(self, param_name='frgb')
        self.colorPicker.setToolTip(self.tr("Change font color"))
        self.colorPicker.changingColor.connect(self.changingColor)
        self.colorPicker.colorChanged.connect(self.onColorLabelChanged)
        self.colorPicker.apply_color.connect(self.on_apply_color)

        self.alignBtnGroup = AlignmentBtnGroup(self)
        self.alignBtnGroup.param_changed.connect(self.on_param_changed)

        self.formatBtnGroup = FormatGroupBtn(self)
        self.formatBtnGroup.param_changed.connect(self.on_param_changed)

        self.verticalChecker = QFontChecker(self)
        self.verticalChecker.setObjectName("FontVerticalChecker")
        self.verticalChecker.clicked.connect(lambda : self.on_param_changed('vertical', self.verticalChecker.isChecked()))

        self.strokeWidthBox = SizeComboBox([0, 10], 'stroke_width', self)
        self.strokeWidthBox.addItems(["0.1"])
        self.strokeWidthBox.setToolTip(self.tr("Change stroke width"))
        self.strokeWidthBox.param_changed.connect(self.on_param_changed)

        self.fontStrokeLabel = SizeControlLabel(self, 0, self.tr("Stroke"))
        self.fontStrokeLabel.setObjectName("fontStrokeLabel")
        font = self.fontStrokeLabel.font()
        font.setPointSizeF(shared.CONFIG_FONTSIZE_CONTENT * 0.95)
        self.fontStrokeLabel.setFont(font)
        self.fontStrokeLabel.size_ctrl_changed.connect(self.strokeWidthBox.changeByDelta)
        self.fontStrokeLabel.btn_released.connect(lambda : self.on_param_changed('stroke_width', self.strokeWidthBox.value()))
        
        self.strokeColorPicker = ColorPickerLabel(self, param_name='srgb')
        self.strokeColorPicker.setToolTip(self.tr("Change stroke color"))
        self.strokeColorPicker.changingColor.connect(self.changingColor)
        self.strokeColorPicker.colorChanged.connect(self.onColorLabelChanged)
        self.strokeColorPicker.apply_color.connect(self.on_apply_color)

        stroke_hlayout = QHBoxLayout()
        stroke_hlayout.addWidget(self.fontStrokeLabel)
        stroke_hlayout.addWidget(self.strokeWidthBox)
        stroke_hlayout.addWidget(self.strokeColorPicker)
        stroke_hlayout.setSpacing(shared.WIDGET_SPACING_CLOSE)

        self.letterSpacingBox = SizeComboBox([0, 10], "letter_spacing", self)
        self.letterSpacingBox.addItems(["0.0"])
        self.letterSpacingBox.setToolTip(self.tr("Change letter spacing"))
        self.letterSpacingBox.setMinimumWidth(int(self.letterSpacingBox.height() * 2.5))
        self.letterSpacingBox.param_changed.connect(self.on_param_changed)

        self.letterSpacingLabel = SizeControlLabel(self, direction=0, transparent_bg=False)
        self.letterSpacingLabel.setObjectName("letterSpacingLabel")
        self.letterSpacingLabel.size_ctrl_changed.connect(self.letterSpacingBox.changeByDelta)
        self.letterSpacingLabel.btn_released.connect(lambda : self.on_param_changed('letter_spacing', self.letterSpacingBox.value()))

        lettersp_hlayout = QHBoxLayout()
        lettersp_hlayout.addWidget(self.letterSpacingLabel)
        lettersp_hlayout.addWidget(self.letterSpacingBox)
        lettersp_hlayout.setSpacing(shared.WIDGET_SPACING_CLOSE)
        
        self.global_fontfmt_str = self.tr("Global Font Format")
        self.textstyle_panel = TextStylePresetPanel(
            self.global_fontfmt_str,
            config_name='show_text_style_preset',
            config_expand_name='expand_tstyle_panel'
        )
        self.textstyle_panel.active_text_style_label_changed.connect(self.on_active_textstyle_label_changed)
        self.textstyle_panel.active_stylename_edited.connect(self.on_active_stylename_edited)

        self.textadvancedfmt_panel = TextAdvancedFormatPanel(
            self.tr('Advanced Text Format'),
            config_name='text_advanced_format_panel',
            config_expand_name='expand_tadvanced_panel',
            on_format_changed=self.on_param_changed
        )
        color_label = self.textadvancedfmt_panel.shadow_group.color_label
        color_label.changingColor.connect(self.changingColor)
        color_label.colorChanged.connect(self.onColorLabelChanged)
        color_label.apply_color.connect(self.on_apply_color)

        color_label = self.textadvancedfmt_panel.gradient_group.start_picker
        color_label.changingColor.connect(self.changingColor)
        color_label.colorChanged.connect(self.onColorLabelChanged)
        color_label.apply_color.connect(self.on_apply_color)
        
        color_label = self.textadvancedfmt_panel.gradient_group.end_picker
        color_label.changingColor.connect(self.changingColor)
        color_label.colorChanged.connect(self.onColorLabelChanged)
        color_label.apply_color.connect(self.on_apply_color)
        
        self.foldTextBtn = CheckableLabel(self.tr("Unfold"), self.tr("Fold"), False)
        self.sourceBtn = TextCheckerLabel(self.tr("Source"))
        self.transBtn = TextCheckerLabel(self.tr("Translation"))

        # Add list widget for words
        # self.wordListWidget = QListWidget(self)
        # self.wordListWidget.setObjectName("WordListWidget")
        # self.wordListWidget.setToolTip(self.tr("List of Words"))
        # self.wordListWidget.addItems(["Word1", "Word2", "Word3", "Word4"])

        # Create an instance of the WordListPanel
        # Provide the necessary names (adjust as per your PanelArea needs)
        self.word_panel = WordListPanel(
            panel_name="SpellCheck",
            config_name="vocab_list_config",
            config_expand_name="vocab_list_expand_state"
        )


        # Connect the panel's signal to our handler slot
        # self.word_panel.word_selected.connect(handle_word_selected)

        FONTFORMAT_SPACING = 6

        vl0 = QVBoxLayout()
        vl0.addWidget(self.textstyle_panel.view_widget)
        vl0.addWidget(self.textadvancedfmt_panel.view_widget)
        vl0.addWidget(self.word_panel.view_widget)  # Add the word list widget here
        vl0.setSpacing(0)
        vl0.setContentsMargins(0, 0, 0, 0)
        hl1 = QHBoxLayout()
        hl1.addWidget(self.familybox)
        hl1.addWidget(self.fontsizebox)
        hl1.addWidget(self.lineSpacingLabel)
        hl1.addWidget(self.lineSpacingBox)
        hl1.setSpacing(4)
        hl1.setContentsMargins(0, 12, 0, 0)
        hl2 = QHBoxLayout()
        hl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl2.addWidget(self.colorPicker)
        hl2.addWidget(self.alignBtnGroup)
        hl2.addWidget(self.formatBtnGroup)
        hl2.addWidget(self.verticalChecker)
        hl2.setSpacing(FONTFORMAT_SPACING)
        hl2.setContentsMargins(0, 0, 0, 0)
        hl3 = QHBoxLayout()
        hl3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl3.addLayout(stroke_hlayout)
        hl3.addLayout(lettersp_hlayout)
        hl3.setContentsMargins(3, 0, 3, 0)
        hl3.setSpacing(13)
        hl4 = QHBoxLayout()
        hl4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl4.addWidget(self.foldTextBtn)
        hl4.addWidget(self.sourceBtn)
        hl4.addWidget(self.transBtn)
        hl4.setStretch(0, 1)
        hl4.setStretch(1, 1)
        hl4.setStretch(2, 1)
        hl4.setContentsMargins(0, 12, 0, 0)
        hl4.setSpacing(0)

        self.vlayout.addLayout(vl0)
        self.vlayout.addLayout(hl1)
        self.vlayout.addLayout(hl2)
        self.vlayout.addLayout(hl3)
        self.vlayout.addLayout(hl4)
        self.vlayout.setContentsMargins(0, 0, 7, 0)
        self.vlayout.setSpacing(0)

        self.focusOnColorDialog = False
        C.active_format = self.global_format
        # Feedback-loop guard: while the stroke display is refreshed
        # programmatically (strokeWidthBox.setValue re-triggers
        # SizeComboBox.on_text_changed -> param_changed -> on_param_changed
        # when the box happens to have focus), on_param_changed must not
        # apply the displayed value to the format.
        self._updating_stroke_display = False
        # e_trans editor of the current block whose selectionChanged drives
        # the stroke display refresh; kept so the connection is dropped on
        # block switch instead of accumulating.
        self._stroke_sel_edit: Optional[QWidget] = None

    def global_mode(self):
        return id(C.active_format) == id(self.global_format)
    
    def active_text_style_label(self):
        return self.textstyle_panel.active_text_style_label

    def active_text_style_format(self):
        af = self.active_text_style_label()
        if af is not None:
            return af.fontfmt
        else:
            return None

    def on_param_changed(self, param_name: str, value):
        if self._updating_stroke_display:
            _debug("[stroke] panel on_param_changed SUPPRESSED (stroke display refresh in progress): param=%s value=%s",
                        param_name, value)
            return
        if param_name == 'font_size':
            if _is_log_target(getattr(self, 'textblk_item', None)):
                LOGGER.debug("[FONTSIZE] PANEL on_param_changed: param=%s value=%.1fpt",
                    param_name, value)
        if param_name in ('stroke_width', 'srgb'):
            _debug("[stroke] panel on_param_changed: param=%s value=%s global=%s item_idx=%s active_stroke=%s",
                        param_name, value, self.global_mode(),
                        getattr(self.textblk_item, 'idx', None),
                        getattr(C.active_format, 'stroke_width', None))
        func = FM.handle_ffmt_change.get(param_name)
        func_kwargs = {}
        if param_name in {'font_size', 'rel_font_size'}:
            func_kwargs['clip_size'] = True
        if self.global_mode():
            func(param_name, value, self.global_format, is_global=True, **func_kwargs)
            self.update_text_style_label()
        else:
            func(param_name, value, C.active_format, is_global=False, blkitems=self.textblk_item, set_focus=True, **func_kwargs)
            if param_name in ('font_size', 'rel_font_size'):
                # The op re-sized the selection: re-read the live cursor
                # position so the box shows the (new) size there, and
                # follows the cursor to other words afterwards.
                self._refresh_font_size_display()

    def update_text_style_label(self):
        if self.global_mode():
            active_text_style_label = self.active_text_style_label()
            if active_text_style_label is not None:
                active_text_style_label.update_style(self.global_format)

    def changingColor(self):
        self.focusOnColorDialog = True

    def onColorLabelChanged(self, is_valid=True):
        self.focusOnColorDialog = False
        if is_valid:
            sender: ColorPickerLabel = self.sender()
            rgb = sender.rgb()
            self.on_param_changed(sender.param_name, rgb)

    def on_apply_color(self, param_name, rgb):
        self.on_param_changed(param_name, rgb)

    def onLineSpacingCtrlChanged(self, delta: int):
        if C.active_format.line_spacing_type == LineSpacingType.Distance:
            mul = 0.1
        else:
            mul = 0.01
        self.lineSpacingBox.setValue(self.lineSpacingBox.value() + delta * mul)

    def set_active_format(self, font_format: FontFormat, multi_size=False):
        C.active_format = font_format
        self.familybox.blockSignals(True)
        # Display as points, not pixels — font_format.font_size is in px, size_pt converts to pt
        font_size = round(font_format.size_pt, 1)
        if int(font_size) == font_size:
            font_size = str(int(font_size))
        else:
            font_size = f'{font_size:.1f}'
        if multi_size:
            font_size += "+"
        caller = inspect.stack()[1].function if len(inspect.stack()) > 1 else '?'
        if _is_log_target(getattr(self, 'textblk_item', None)):
            LOGGER.debug("[FONTSIZE] PANEL set_active_format: display_val=%s pt (font_size=%.1fpx, size_pt=%.1fpt) multi_size=%s caller=%s",
                font_size, font_format.font_size, font_format.size_pt, multi_size, caller)
        self.fontsizebox.fcombobox.setCurrentText(font_size)
        self.familybox.setCurrentText(font_format.font_family)
        self.colorPicker.setPickerColor(font_format.foreground_color())
        self.strokeColorPicker.setPickerColor(font_format.stroke_color())
        self.strokeWidthBox.setValue(font_format.stroke_width)
        self.lineSpacingBox.setValue(font_format.line_spacing)
        self.letterSpacingBox.setValue(font_format.letter_spacing)
        self.verticalChecker.setChecked(font_format.vertical)
        self.formatBtnGroup.boldBtn.setChecked(font_format.bold)
        self.formatBtnGroup.underlineBtn.setChecked(font_format.underline)
        self.formatBtnGroup.italicBtn.setChecked(font_format.italic)
        self.alignBtnGroup.setAlignment(font_format.alignment)
        
        self.familybox.blockSignals(False)
        self.textadvancedfmt_panel.set_active_format(font_format)

    def set_globalfmt_title(self):
        active_text_style_label = self.active_text_style_label()
        if active_text_style_label is None:
            self.textstyle_panel.setTitle(self.global_fontfmt_str)
        else:
            title = self.global_fontfmt_str + ' - ' + active_text_style_label.fontfmt._style_name
            valid_title = self.textstyle_panel.elidedText(title)
            self.textstyle_panel.setTitle(valid_title)


    def deactivate_style_label(self):
        if self.active_text_style_label() is not None:
            self.textstyle_panel.on_stylelabel_activated(False)


    def on_active_textstyle_label_changed(self):
        '''
        merge activate textstyle into global format
        '''
        active_text_style_label = self.active_text_style_label()
        if active_text_style_label is not None:
            updated_keys = self.global_format.merge(active_text_style_label.fontfmt, compare=True)
            if self.global_mode() and len(updated_keys) > 0:
                self.set_active_format(self.global_format)
            self.set_globalfmt_title()
        else:
            if self.global_mode():
                self.set_globalfmt_title()

    def on_active_stylename_edited(self):
        if self.global_mode():
            self.set_globalfmt_title()

    def _get_stroke_selection_editor(self) -> Optional[QWidget]:
        """Paired panel editor (e_trans) of the current block, or None when
        there is no scene text manager / no pair widget for the block / the
        editor's C++ object was already destroyed (a page switch can delete
        the pair widgets while the panel still holds a Python reference)."""
        item = self.textblk_item
        if item is None:
            return None
        from . import shared_widget as SW
        st = SW.st_manager
        if st is not None and getattr(st, 'pairwidget_list', None) \
                and 0 <= item.idx < len(st.pairwidget_list):
            try:
                edit = st.pairwidget_list[item.idx].e_trans
                # A page switch can delete the pair widgets' C++ objects
                # while the panel keeps the Python wrapper: check
                # sip.isdeleted up front so we never raise RuntimeError
                # by touching a dead wrapper (the except below is a
                # backstop for non-sip wrappers / unexpected attrs).
                if sip.isdeleted(edit):
                    _debug("[stroke] panel: e_trans of idx=%s already destroyed, skipping connect",
                           item.idx)
                    return None
                return edit
            except (RuntimeError, AttributeError, TypeError) as exc:
                LOGGER.debug("[stroke] panel: e_trans lookup failed for idx=%s: %r", item.idx, exc)
                return None
        return None

    def _on_stroke_editor_destroyed(self, obj: Optional[object] = None) -> None:
        """Slot for the tracked editor's QObject.destroyed signal. Qt emits
        it when the editor's C++ object dies (a page switch deletes the pair
        widgets) and auto-severs all of that object's signal connections in
        the same moment, so the panel only needs to drop the dangling
        Python reference.

        The ``obj`` argument is intentionally unused: PyQt hands the slot a
        fresh detached wrapper (not ``is``-identical to the one we stored)
        and sip.isdeleted() is not yet set while the slot runs, so
        identifying the dying object is impossible. Clearing unconditionally
        is safe because _connect_stroke_selection_editor /
        _disconnect_stroke_selection_editor keep this subscription in sync
        with _stroke_sel_edit: at any moment only the currently tracked
        editor has this connection (or a dead one whose signal already
        fired)."""
        _debug("[stroke] panel: e_trans destroyed, reference cleared")
        self._stroke_sel_edit = None

    def _disconnect_stroke_selection_editor(self) -> None:
        prev = self._stroke_sel_edit
        self._stroke_sel_edit = None
        if prev is None:
            return
        if sip.isdeleted(prev):
            # A dead editor can only be here if its destroyed signal did
            # not reach us; Qt already auto-severed its connections,
            # so there is nothing to disconnect.
            _debug("[stroke] panel: previous e_trans already deleted, nothing to disconnect")
            return
        for signal, slot in ((prev.selectionChanged, self._refresh_stroke_display),
                             (prev.selectionChanged, self._refresh_font_size_display),
                             (prev.destroyed, self._on_stroke_editor_destroyed)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                # Backstop: a slot may legitimately be absent (e.g. the
                # reference predates the destroyed subscription).
                pass

    def _connect_stroke_selection_editor(self) -> None:
        """Connect the current block's e_trans selectionChanged to the
        stroke and font-size display refreshes. The previously connected
        editor is disconnected first, so switching blocks does not
        accumulate connections. The editor's QObject.destroyed signal is
        also subscribed so the panel proactively clears its reference when
        the editor's C++ object dies (page switch) — no code path ever
        touches a dead wrapper, which is what used to raise RuntimeError
        'wrapped C/C++ object ... has been deleted'."""
        self._disconnect_stroke_selection_editor()
        e_trans = self._get_stroke_selection_editor()
        if e_trans is None:
            return
        e_trans.selectionChanged.connect(self._refresh_stroke_display)
        e_trans.selectionChanged.connect(self._refresh_font_size_display)
        e_trans.destroyed.connect(self._on_stroke_editor_destroyed)
        self._stroke_sel_edit = e_trans
        _debug("[stroke] panel selectionChanged connected: idx=%s",
                    self.textblk_item.idx)

    def _refresh_stroke_display(self) -> None:
        """Re-sync the stroke width box / color picker with the outline of
        the current block's effective selection.

        Called from set_textblk_item (initial display) and from the paired
        e_trans editor's selectionChanged signal (the user changed the
        selection without switching blocks). When the effective selection
        has its own outline the panel shows it; otherwise the display falls
        back to the block-level scalars — the same base values
        set_active_format(blk_fmt) puts into the box/picker. C.active_format
        keeps the block scalars in either case (focus-out copy-back).

        The programmatic writes run under _updating_stroke_display so a
        re-triggered editTextChanged on the (possibly focused) stroke box
        cannot feed back into on_param_changed and change the format."""
        item = self.textblk_item
        if item is None:
            return
        sel_outline = item.get_selection_outline()
        self._updating_stroke_display = True
        try:
            if sel_outline is not None:
                self.strokeWidthBox.setValue(sel_outline[0])
                r, g, b = [int(x) for x in sel_outline[1]]
                self.strokeColorPicker.setPickerColor(QColor(r, g, b))
                _debug("[stroke] panel display override: idx=%s box=%s (block scalar stays %s)",
                            item.idx, sel_outline[0],
                            item.get_fontformat().stroke_width)
            else:
                blk_fmt = item.get_fontformat()
                self.strokeWidthBox.setValue(blk_fmt.stroke_width)
                self.strokeColorPicker.setPickerColor(blk_fmt.stroke_color())
                _debug("[stroke] panel display fallback to block scalar: idx=%s box=%s",
                            item.idx, blk_fmt.stroke_width)
        finally:
            self._updating_stroke_display = False

    def eventFilter(self, obj, event) -> bool:
        # Refresh the font-size display when the user focuses the size box:
        # canvas-editor cursor moves emit no signal, so without this the box
        # would keep showing the size left by the last size op until the
        # user interacts with it.
        if obj is self.fontsizebox.fcombobox and \
                isinstance(event, QFocusEvent) and event.type() == QFocusEvent.Type.FocusIn:
            self._refresh_font_size_display()
        return super().eventFilter(obj, event)

    @staticmethod
    def _format_size_text(pt: float, multi: bool = False) -> str:
        """Font-size display text: one decimal at most, '+' suffix when the
        range spans several sizes (the up/down buttons then use
        rel_font_size scaling)."""
        size = round(float(pt), 1)
        if int(size) == size:
            text = str(int(size))
        else:
            text = f'{size:.1f}'
        if multi:
            text += '+'
        return text

    def _refresh_font_size_display(self) -> None:
        """Re-sync the font-size box with the size at the LIVE cursor
        position.

        Per-range sizes (setFontSize on a selection) live in the block
        document's char formats, while the block scalar (and the box left by
        the last size op) only track the latest change — without this refresh
        the box keeps showing the changed word's size after the cursor moves
        to an unchanged word. Display-only: C.active_format keeps the block
        scalar, so the focus-out copy-back is unaffected. The programmatic
        write runs under _updating_stroke_display so a re-triggered
        editTextChanged on the (possibly focused) box cannot feed back into
        on_param_changed.

        Called from set_textblk_item (initial display), the paired e_trans
        selectionChanged signal, the size box focusIn (eventFilter) and
        after font-size ops (on_param_changed)."""
        item = self.textblk_item
        if item is None:
            return
        result = item.get_cursor_font_size()
        if result is None:
            pt, multi = item.get_fontformat().size_pt, False
        else:
            pt, multi = result
        text = self._format_size_text(pt, multi)
        box = self.fontsizebox.fcombobox
        if text == box.currentText():
            return
        self._updating_stroke_display = True
        try:
            box.setCurrentText(text)
            _debug("[FONTSIZE] panel display refresh: idx=%s text=%r (block scalar %.1fpt)",
                        item.idx, text, item.get_fontformat().size_pt)
        finally:
            self._updating_stroke_display = False

    def set_textblk_item(self, textblk_item: TextBlkItem = None, multi_select:bool=False):
        if textblk_item is None:
            focus_w = self.app.focusWidget()
            focus_p = None if focus_w is None else focus_w.parentWidget()
            focus_on_fmtoptions = False
            if self.focusOnColorDialog:
                focus_on_fmtoptions = True
            elif focus_p:
                if focus_p == self or focus_p.parentWidget() == self:
                    focus_on_fmtoptions = True
            if not focus_on_fmtoptions:
                # Store the current text block's format before switching to global
                if self.textblk_item is not None:
                    _debug("[stroke] panel focus-out COPY-BACK: idx=%s active_stroke=%s item_stroke=%s -> %s blk_stroke=%s ranges=%s",
                                self.textblk_item.idx,
                                getattr(C.active_format, 'stroke_width', None),
                                self.textblk_item.fontformat.stroke_width,
                                C.active_format.stroke_width,
                                (self.textblk_item.blk.fontformat.stroke_width
                                 if self.textblk_item.blk is not None else None),
                                getattr(self.textblk_item.blk, 'outline_ranges', None))
                    # Save all format properties including gradient state
                    self.textblk_item.fontformat = copy.deepcopy(C.active_format)
                self.textblk_item = None
                self._disconnect_stroke_selection_editor()
                self.set_active_format(self.global_format, multi_select)
                self.set_globalfmt_title()
            
        else:
            if not self.restoring_textblk:
                blk_fmt = textblk_item.get_fontformat()
                if _is_log_target(textblk_item.blk if hasattr(textblk_item, 'blk') else None):
                    LOGGER.debug("[FONTSIZE] PANEL set_textblk_item: idx=%d fontformat.font_size=%.1fpx size_pt=%.1fpt",
                        textblk_item.idx, textblk_item.fontformat.font_size, textblk_item.fontformat.size_pt)
                _debug("[stroke] panel set_textblk_item: idx=%s display_stroke=%s selection_outline=%s item_stroke=%s blk_stroke=%s ranges=%s",
                            textblk_item.idx, blk_fmt.stroke_width,
                            textblk_item.get_selection_outline(),
                            textblk_item.fontformat.stroke_width,
                            (textblk_item.blk.fontformat.stroke_width
                             if textblk_item.blk is not None else None),
                            getattr(textblk_item.blk, 'outline_ranges', None))
                # Preserve gradient properties from the text block's format
                if hasattr(textblk_item.fontformat, 'gradient_enabled'):
                    blk_fmt.gradient_enabled = textblk_item.fontformat.gradient_enabled
                    blk_fmt.gradient_start_color = textblk_item.fontformat.gradient_start_color
                    blk_fmt.gradient_end_color = textblk_item.fontformat.gradient_end_color
                    blk_fmt.gradient_angle = textblk_item.fontformat.gradient_angle
                    blk_fmt.gradient_size = textblk_item.fontformat.gradient_size
                self.textblk_item = textblk_item
                multi_size = not textblk_item.isEditing() and textblk_item.isMultiFontSize()
                self.set_active_format(blk_fmt, multi_size)
                # Follow selection changes made in the paired editor
                # (e_trans) without a block switch: the stroke display must
                # reflect the (new) selection's outline, not the values the
                # previous selection left in the box/picker.
                self._connect_stroke_selection_editor()
                # If the effective selection has its own outline, the panel
                # must show THAT part's outline, not the block-level scalar.
                # C.active_format deliberately keeps the block scalar so the
                # focus-out copy-back does not clobber it.
                self._refresh_stroke_display()
                # Same for the font size: per-range sizes (per-word
                # setFontSize) live in the document's char formats, not in
                # the block scalar the box was just filled with.
                self._refresh_font_size_display()
                self.textstyle_panel.setTitle(f'TextBlock #{textblk_item.idx}')

    def handle_word_selected(word: str):
        print(f"Main window received signal: Selected word is '{word}'")
        selected_word_display_label.setText(f"Selected word: <b>{word}</b>")

