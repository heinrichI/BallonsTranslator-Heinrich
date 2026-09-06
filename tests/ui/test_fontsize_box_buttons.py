"""FontSizeBox up/down buttons must parse the box's display text without
crashing.

Regression (error28 family): the buttons called float() on the raw box text.
Multi-size display text ('15.3+') was handled by a strip('+'), but a
RU-locale comma decimal ('12,5' — QDoubleValidator uses the system locale,
which accepts the comma and rejects the dot) raised an uncaught ValueError
and killed the app; an empty box raised too.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from ui.text_panel import FontSizeBox


@pytest.fixture
def box(qapp) -> FontSizeBox:
    return FontSizeBox()


def _emitted(box: FontSizeBox):
    events = []
    box.param_changed.connect(lambda name, val: events.append((name, val)))
    return events


def test_up_on_multisize_uses_rel_factor(box: FontSizeBox) -> None:
    events = _emitted(box)
    box.fcombobox.setCurrentText("15.3+")
    box.onUpBtnClicked()
    assert events == [('rel_font_size', 1.25)]
    assert box.getFontSize() == "19+"  # round(15.3 * 1.25)


def test_down_on_multisize_uses_rel_factor(box: FontSizeBox) -> None:
    events = _emitted(box)
    box.fcombobox.setCurrentText("15.3+")
    box.onDownBtnClicked()
    assert events == [('rel_font_size', 0.75)]
    assert box.getFontSize() == "11+"  # round(15.3 * 0.75)


def test_up_on_comma_decimal(box: FontSizeBox) -> None:
    """RU-locale input '12,5' is Acceptable for the validator; the up
    button used to crash on float('12,5')."""
    events = _emitted(box)
    box.fcombobox.setCurrentText("12,5")
    box.onUpBtnClicked()
    assert events == [('font_size', 16)]  # round(12.5 * 1.25)
    assert box.getFontSize() == "16"


def test_down_on_comma_decimal(box: FontSizeBox) -> None:
    events = _emitted(box)
    box.fcombobox.setCurrentText("12,5")
    box.onDownBtnClicked()
    assert events == [('font_size', 9)]  # round(12.5 * 0.75)
    assert box.getFontSize() == "9"


def test_up_on_empty_box_falls_back_to_last_valid(box: FontSizeBox) -> None:
    events = _emitted(box)
    box.fcombobox.setValue(20.0)
    box.fcombobox.value()  # establish _value from the displayed text
    box.fcombobox.setCurrentText("")
    box.onUpBtnClicked()
    assert events == [('font_size', 25)]  # round(20 * 1.25)
    assert box.getFontSize() == "25"


def test_down_on_garbage_falls_back_to_last_valid(box: FontSizeBox) -> None:
    events = _emitted(box)
    box.fcombobox.setValue(10.0)
    box.fcombobox.value()  # establish _value from the displayed text
    box.fcombobox.setCurrentText("abc")
    box.onDownBtnClicked()
    assert events == [('font_size', 8)]  # round(10 * 0.75)
    assert box.getFontSize() == "8"
