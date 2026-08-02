import traceback
from typing import Callable, List, Dict

from . import shared
from .shared import _yesno_result, _yesno_event
from .logger import logger as LOGGER


def create_error_dialog(exception: Exception, error_msg: str = None, exception_type: str = None):
    '''
        Popup a error dialog in main thread
    Args:
        error_msg: Description text prepend before str(exception)
        exception_type: Specify it to avoid errors dialog of the same type popup repeatedly 
    '''

    detail_traceback = traceback.format_exc()
    
    if exception_type is None:
        exception_type = ''

    exception_type_empty = exception_type == ''
    show_exception = exception_type_empty or exception_type not in shared.showed_exception

    if show_exception:
        if error_msg is None:
            error_msg = str(exception)
        else:
            error_msg = str(exception) + '\n' + error_msg
        LOGGER.error(error_msg + '\n')
        LOGGER.error(detail_traceback)

        if not shared.HEADLESS:
            shared.create_errdialog_in_mainthread(error_msg, detail_traceback, exception_type)


def create_info_dialog(info_msg, btn_type=None, modal: bool = False, frame_less: bool = False, signal_slot_map_list: List[Dict] = None):
    '''
        Popup a info dialog in main thread
    '''
    LOGGER.info(info_msg)
    if not shared.HEADLESS:
        shared.create_infodialog_in_mainthread({'info_msg': info_msg, 'btn_type': btn_type, 'modal': modal, 'frame_less': frame_less, 'signal_slot_map_list': signal_slot_map_list})


def create_yes_no_dialog(question_msg: str, default_yes: bool = False) -> bool:
    """Show a yes/no question dialog in the main thread and return the user's choice.
    Returns True if Yes, False if No or in headless mode.
    """
    if shared.HEADLESS:
        return default_yes
    import uuid
    dialog_id = str(uuid.uuid4())
    shared.create_yesno_dialog_in_mainthread({'question': question_msg, 'dialog_id': dialog_id})
    _yesno_event.wait(timeout=60)
    result = _yesno_result.pop(dialog_id, default_yes)
    _yesno_event.clear()
    return result


def connect_once(signal, exec_func: Callable):
    '''
    signal.emit will only trigger exec_func once
    '''

    def _disconnect_after_called(*func_args, **func_kwargs):

        def _try_disconnect():
            try:
                signal.disconnect(connect_func)
            except:
                print('Failed to disconnect')
                print(traceback.format_exc())

        try:
            exec_func(*func_args, **func_kwargs)
        except Exception as e:
            _try_disconnect()
            raise e
        _try_disconnect()

    connect_func = _disconnect_after_called
    signal.connect(_disconnect_after_called)