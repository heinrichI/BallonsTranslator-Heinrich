"""SizeComboBox.value() must parse RU-locale decimal input and tolerate
an in-progress trailing decimal separator.

Regression: typing '24,' (decimal comma, RU locale) used to raise
ValueError: could not convert string to float: '24,' from value(); after
the crash was guarded, the typed value was silently dropped and the
param_changed signal kept emitting the previous value.

error28: the panel writes multi-size display text with a '+' suffix
('15.3+') into the focused box; float('15.3+') raised internally on every
focus-in refresh — the except masked it for the app, but a debugger
breaking on exceptions (pydevd 'Exception has occurred') stopped on it
and value() returned the stale _value instead of the displayed number.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from ui.custom_widget.combobox import SizeComboBox


@pytest.fixture
def combo(qapp) -> SizeComboBox:
    c = SizeComboBox(val_range=[0, 200], param_name="test", init_value=10)
    c.value()  # establish _value from the displayed init text
    return c


@pytest.mark.parametrize("text,expected", [
    ("24", 24.0),
    ("24.5", 24.5),
    ("24,5", 24.5),   # RU decimal comma
    ("24,", 24.0),    # in-progress input: must not raise, keeps int part
    ("24.", 24.0),
    ("", 10.0),       # empty -> previous value
    ("abc", 10.0),    # garbage -> previous value, must not raise
    ("0,1", 0.1),
    ("15.3+", 15.3),  # panel multi-size display text: '+' suffix, no raise
    ("15+", 15.0),
])
def test_value_parses(qapp, combo: SizeComboBox, text: str, expected: float) -> None:
    combo.setCurrentText(text)
    assert combo.value() == pytest.approx(expected)


def test_on_text_changed_emits_comma_decimal(qapp, combo: SizeComboBox) -> None:
    """Focused typing of '24,5' must emit the NEW value, not the old one."""
    emitted = []
    combo.param_changed.connect(lambda name, val: emitted.append(val))
    combo.hasFocus = lambda: True  # offscreen window never gets real focus
    combo.setCurrentText("24,5")
    combo.on_text_changed()
    assert emitted and emitted[-1] == pytest.approx(24.5)


def test_multisize_display_text_parses_not_stale(qapp, combo: SizeComboBox) -> None:
    """'15.3+' must yield the displayed number (15.3), not the previous
    value (error28: the internal ValueError dropped it to stale _value)."""
    combo.setValue(12.0)
    combo.setCurrentText("15.3+")
    assert combo.value() == pytest.approx(15.3)
    # The parsed display number becomes the stored value:
    combo.setCurrentText("")
    assert combo.value() == pytest.approx(15.3)


def test_multisize_display_write_raises_nothing(qapp, combo: SizeComboBox) -> None:
    """Full chain from error28's traceback: focused box +
    setCurrentText('15.3+') -> editTextChanged -> on_text_changed -> value()
    must raise NOTHING — even the internally caught ValueError makes a
    debugger breaking on exceptions stop on it."""
    import sys as _sys

    combo.setValue(12.0)
    combo.hasFocus = lambda: True  # offscreen window never gets real focus
    raised = []

    def globaltrace(frame, event, arg):
        if event == "call":
            return localtrace
        return None

    def localtrace(frame, event, arg):
        # arg is an exc_info tuple: (type, instance, tb) — test the instance
        if event == "exception" and isinstance(arg[1], ValueError) \
                and frame.f_code.co_filename.endswith("combobox.py"):
            raised.append((frame.f_code.co_name, frame.f_lineno, arg[1]))
        return localtrace

    prev = _sys.gettrace()
    _sys.settrace(globaltrace)
    try:
        combo.setCurrentText("15.3+")
    finally:
        _sys.settrace(prev)
    assert not raised, f"ValueError raised inside combobox.py: {raised}"
