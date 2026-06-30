import os
import sys
# Ensure project root is importable so `ui.*` modules resolve
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib
from types import SimpleNamespace

import pytest

from utils.config import pcfg
import ui.scenetext_manager as stm_mod

@pytest.fixture(autouse=True)
def reset_pcfg():
    # ensure stable default
    orig = pcfg.enable_spellcheck
    pcfg.enable_spellcheck = True
    yield
    pcfg.enable_spellcheck = orig

def test_updateUnknownWordsPanel_skips_when_panel_hidden():
    called = {"count": 0}

    class FakeEngine:
        def GetUnknownWordsViaDictionaryFromList(self, words):
            called["count"] += 1
            return []

    fake_self = SimpleNamespace()
    fake_self.textpanel = SimpleNamespace(isVisible=lambda: False,
                                         formatpanel=SimpleNamespace(word_panel=SimpleNamespace(set_words=lambda w: None)))
    fake_self.imgtrans_proj = SimpleNamespace(current_block_list=lambda: [])
    fake_self.SpellCheckEngine = FakeEngine()

    # Call unbound method with fake self
    stm_mod.SceneTextManager.updateUnknownWordsPanel(fake_self)
    assert called["count"] == 0

def test_updateUnknownWordsPanel_calls_engine_when_visible():
    called = {"count": 0}

    class FakeEngine:
        def GetUnknownWordsViaDictionaryFromList(self, words):
            called["count"] += 1
            return []

    fake_self = SimpleNamespace()
    fake_self.textpanel = SimpleNamespace(isVisible=lambda: True,
                                         formatpanel=SimpleNamespace(word_panel=SimpleNamespace(set_words=lambda w: None)))
    fake_self.imgtrans_proj = SimpleNamespace(current_block_list=lambda: [])
    fake_self.SpellCheckEngine = FakeEngine()

    stm_mod.SceneTextManager.updateUnknownWordsPanel(fake_self)
    assert called["count"] == 1