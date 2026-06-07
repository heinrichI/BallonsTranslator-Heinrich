import json
import importlib
import sys
import types

import pytest

from types import SimpleNamespace

def make_fake_dict():
    class FakeDict:
        def lookup(self, word):
            return word == "known"

        def suggest(self, word):
            return ["suggestion_for_" + word]
    return FakeDict()

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # provide dummy ui.SpellCheckDialog to avoid import-time GUI dependency
    sys.modules['ui.SpellCheckDialog'] = SimpleNamespace(SpellCheckDialog=type('DummySpellCheckDialog', (), {}))

    # inject proper module objects for spylls.hunspell.dictionary.Dictionary.from_files
    spylls_mod = types.ModuleType('spylls')
    hun_mod = types.ModuleType('spylls.hunspell')
    dict_mod = types.ModuleType('spylls.hunspell.dictionary')

    class Dictionary:
        @staticmethod
        def from_files(path):
            return make_fake_dict()

    dict_mod.Dictionary = Dictionary
    sys.modules['spylls'] = spylls_mod
    sys.modules['spylls.hunspell'] = hun_mod
    sys.modules['spylls.hunspell.dictionary'] = dict_mod

    # prevent actual downloads and dictionary loading
    monkeypatch.setattr("utils.spell_check_engine.download_and_check_files", lambda **kwargs: None)
    # reset module-level engine between tests
    import utils.spell_check_engine as sce
    sce._ENGINE = None
    yield
    sce._ENGINE = None
    importlib.reload(sce)

def test_singleton_and_reload():
    from utils.spell_check_engine import get_spellcheck_engine, reload_spellcheck_language
    import utils.spell_check_engine as sce

    e1 = get_spellcheck_engine("en")
    e2 = get_spellcheck_engine()
    assert e1 is e2
    assert e1.lang == "en"

    reload_spellcheck_language("fr")
    e3 = get_spellcheck_engine()
    assert e3.lang == "fr"
    assert e3 is sce._ENGINE

def test_lookup_and_suggest_behavior():
    from utils.spell_check_engine import get_spellcheck_engine
    eng = get_spellcheck_engine("en")
    # lookup: known vs unknown
    assert eng.dictionary.lookup("known") is True
    assert eng.dictionary.lookup("unknown") is False
    # DoSuggest forwards to dictionary.suggest
    res = eng.DoSuggest("anything")
    assert res == ["suggestion_for_anything"]

def test_onWordDeleted_writes_skipped_words(tmp_path):
    from utils.spell_check_engine import get_spellcheck_engine
    eng = get_spellcheck_engine("en")
    # redirect data_file to tmp to avoid repository mutation
    eng.data_file = str(tmp_path / "SpellCheckEngine_en_test.json")
    if (tmp_path / "SpellCheckEngine_en_test.json").exists():
        (tmp_path / "SpellCheckEngine_en_test.json").unlink()
    eng.onWordDeleted("to_skip")
    # file should be created and contain skipped_words
    with open(eng.data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "skipped_words" in data
