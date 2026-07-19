from typing import List, Callable, Dict
import copy
import inspect
import logging

from qtpy.QtGui import QFont
try:
    from qtpy.QtWidgets import QUndoCommand
except:
    from qtpy.QtGui import QUndoCommand

from . import shared_widget as SW
from utils.fontformat import FontFormat, px2pt
from .textitem import TextBlkItem

LOGGER = logging.getLogger('BallonTranslator')

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

global_default_set_kwargs = dict(set_selected=False, restore_cursor=False)
local_default_set_kwargs = dict(set_selected=True, restore_cursor=True)



class TextStyleUndoCommand(QUndoCommand):

    def __init__(self, style_func: Callable, params: Dict, redo_values: List, undo_values: List):
        super().__init__()
        self.style_func = style_func
        self.params = params
        self.redo_values = redo_values
        self.undo_values = undo_values

    def redo(self) -> None:
        self.style_func(values=self.redo_values, **self.params)

    def undo(self) -> None:
        self.style_func(values=self.undo_values, **self.params)


def wrap_fntformat_input(values: str, blkitems: List[TextBlkItem], is_global: bool):
    if is_global:
        blkitems = SW.canvas.selected_text_items()
    else:
        if not isinstance(blkitems, List):
            blkitems = [blkitems]
    values = [values] * len(blkitems)
    return blkitems, values

def font_formating(push_undostack: bool = False, is_property = True):

    def func_wrapper(formatting_func):

        def wrapper(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem] = None, set_focus: bool = False, *args, **kwargs):
            if is_global and is_property:
                if hasattr(act_ffmt, param_name):
                    # font_size comes from panel in pt, but FontFormat stores px
                    if param_name == 'font_size':
                        act_ffmt[param_name] = pt2px(values)
                    else:
                        act_ffmt[param_name] = values
                else:
                    print(f'undefined param name: {param_name}')

            blkitems, values = wrap_fntformat_input(values, blkitems, is_global)
            if len(blkitems) > 0:
                if is_property:
                    # Do NOT set act_ffmt.font_size here — setFontSize() already
                    # sets self.fontformat.font_size correctly (pt→px conversion).
                    # Setting it here would overwrite the correct px value with the
                    # raw pt value, causing the panel to display the wrong size.
                    if param_name != 'font_size':
                        act_ffmt[param_name] = values[0]
                if push_undostack:
                    params = copy.deepcopy(kwargs)
                    params.update({'param_name': param_name, 'act_ffmt': act_ffmt, 'is_global': is_global, 'blkitems': blkitems})
                    undo_values = [getattr(blkitem.fontformat, param_name) for blkitem in blkitems]
                    # font_size undo values are in px (from fontformat), but function expects pt
                    if param_name == 'font_size':
                        undo_values = [px2pt(v) for v in undo_values]
                    cmd = TextStyleUndoCommand(formatting_func, params, values, undo_values)
                    SW.canvas.push_undo_command(cmd)
                else:
                    formatting_func(param_name, values, act_ffmt, is_global, blkitems, *args, **kwargs)
            if set_focus:
                if not SW.canvas.hasFocus():
                    SW.canvas.setFocus()
        return wrapper
    
    return func_wrapper

@font_formating()
def ffmt_change_font_family(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontFamily(value, **set_kwargs)

@font_formating()
def ffmt_change_italic(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontItalic(value, **set_kwargs)

@font_formating()
def ffmt_change_underline(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontUnderline(value, **set_kwargs)

@font_formating()
def ffmt_change_font_weight(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontWeight(value, **set_kwargs)

@font_formating()
def ffmt_change_bold(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem] = None, **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    values = [QFont.Weight.Bold if value else QFont.Weight.Normal for value in values]
    # ffmt_change_weight('weight', values, act_ffmt, is_global, blkitems, **kwargs)
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontWeight(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_letter_spacing(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setLetterSpacing(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_line_spacing(param_name: str, values: str, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setLineSpacing(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_vertical(param_name: str, values: bool, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    # set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setVertical(value)

@font_formating()
def ffmt_change_frgb(param_name: str, values: tuple, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setFontColor(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_srgb(param_name: str, values: tuple, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setStrokeColor(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_stroke_width(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setStrokeWidth(value, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_font_size(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], clip_size=False, **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        if value < 0:
            continue
        # Panel now provides pt values — pass directly to setFontSize (which expects pt)
        if _is_log_target(blkitem.blk if hasattr(blkitem, 'blk') else None):
            LOGGER.debug("[FONTSIZE] CMD ffmt_change_font_size: idx=%d input=%.1fpt is_global=%s",
                blkitem.idx if hasattr(blkitem, 'idx') else -1, value, is_global)
        blkitem.setFontSize(value, clip_size=clip_size, **set_kwargs)
        blkitem.updateBlkFormat()

@font_formating(is_property=False)
def ffmt_change_rel_font_size(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], clip_size=False, **kwargs):
    set_kwargs = global_default_set_kwargs if is_global else local_default_set_kwargs
    for blkitem, value in zip(blkitems, values):
        blkitem.setRelFontSize(value, clip_size=clip_size, **set_kwargs)

@font_formating(push_undostack=True)
def ffmt_change_alignment(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    restore_cursor = not is_global
    for blkitem, value in zip(blkitems, values):
        blkitem.setAlignment(value, restore_cursor=restore_cursor)

@font_formating(push_undostack=True)
def ffmt_change_opacity(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    for blkitem, value in zip(blkitems, values):
        blkitem.setOpacity(value)

@font_formating(push_undostack=True)
def ffmt_change_line_spacing_type(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    restore_cursor = not is_global
    for blkitem, value in zip(blkitems, values):
        blkitem.setLineSpacingType(value, restore_cursor=restore_cursor)


@font_formating(push_undostack=True)
def ffmt_change_shadow_offset(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    for blkitem, value in zip(blkitems, values):
        blkitem.setBGAttribute(param_name, value)


@font_formating()
def ffmt_change_gradient_enabled(param_name: str, values: float, act_ffmt: FontFormat, is_global: bool, blkitems: List[TextBlkItem], **kwargs):
    for blkitem, value in zip(blkitems, values):
        blkitem.setGradientAttribute(param_name, value)


ffmt_change_shadow_radius = ffmt_change_shadow_offset
ffmt_change_shadow_strength = ffmt_change_shadow_offset
ffmt_change_shadow_color = ffmt_change_shadow_offset

ffmt_change_gradient_start_color = ffmt_change_gradient_enabled
ffmt_change_gradient_end_color = ffmt_change_gradient_enabled
ffmt_change_gradient_angle = ffmt_change_gradient_enabled
ffmt_change_gradient_size = ffmt_change_gradient_enabled
