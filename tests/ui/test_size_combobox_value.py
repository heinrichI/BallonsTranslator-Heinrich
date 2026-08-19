"""SizeComboBox.value() must parse RU-locale decimal input and tolerate
an in-progress trailing decimal separator.

Regression: typing '24,' (decimal comma, RU locale) used to raise
ValueError: could not convert string to float: '24,' from value(); after
the crash was guarded, the typed value was silently dropped and the
param_changed signal kept emitting the previous value.
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
