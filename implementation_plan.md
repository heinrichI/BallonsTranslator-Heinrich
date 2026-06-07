# Implementation Plan

[Overview]
Add a user-configurable spellcheck language option in the UI and ensure the running SpellCheckEngine respects and can be reloaded when the language setting changes.

This change wires the existing UI combobox (ui/configpanel.py) to an engine lifecycle that supports runtime language reloads, centralizes engine creation/lookup, updates callers to use the central engine, and persists per-language skipped-word data. It avoids disrupting existing behavior by preserving the current config flag checks and by providing a safe singleton accessor to minimize duplicate dictionaries and downloads.

[Types]  
Introduce no new static type system; augment runtime interfaces for SpellCheckEngine and a new accessor API.

- SpellCheckEngine (existing)
  - Fields:
    - lang: str — language code ('en','fr','it','de')
    - dictionary: spylls.hunspell.dictionary.Dictionary
    - data_file: str — "SpellCheckEngine_{lang}.json"
    - skipped_words: List[str]
    - replace_words: List[Tuple[str,str]]
  - Validation rules:
    - lang must be one of supported codes; fallback to 'en'
    - data_file exists or created on first save
    - dictionary must be loaded before calls to lookup/suggest
- New module-level accessor functions (utils/spell_check_engine.py)
  - get_spellcheck_engine(lang: Union[str,None]=None) -> SpellCheckEngine
    - Returns singleton engine; if lang provided and differs, reload or recreate engine.
  - reload_spellcheck_language(lang: str) -> SpellCheckEngine
    - Forces engine to reload dictionaries and data for given lang.
- No enums required; supported language codes documented in module-level SUPPORTED_LANGS = ['en','fr','it','de'].

[Files]  
Describe files to create/modify.

- New files to be created:
  - tests/test_spell_check_engine.py — unit tests for engine creation, reload_language, and GetUnknownWordsViaDictionaryFromList.
- Existing files to be modified:
  - utils/spell_check_engine.py
    - Add module-level SUPPORTED_LANGS and a module-level _ENGINE: Optional[SpellCheckEngine] singleton.
    - Add get_spellcheck_engine(lang: Union[str,None]=None) and reload_spellcheck_language(lang: str) functions.
    - Make __init__ keep current signature (lang optional) and ensure it uses self.lang consistently (already present).
    - Ensure reload_language remains method on instance and is used by reload_spellcheck_language.
    - Add thread-safety note (simple locking) if desired (optional).
    - Ensure data_file per-language behavior is preserved.
  - ui/configpanel.py
    - on_spellcheck_language_changed: after updating pcfg and saving, call utils.spell_check_engine.reload_spellcheck_language(sel) (or get_spellcheck_engine(sel)) to reload the running engine if present.
    - Ensure no heavy blocking UI work — operations use the existing download_and_check_files which may block; keep calls synced but consider running download in background later (not required now).
  - ui/scenetext_manager.py
    - Replace direct SpellCheckEngine() instantiation with from utils.spell_check_engine import get_spellcheck_engine and call get_spellcheck_engine() to obtain engine.
    - Ensure code that calls self.SpellCheckEngine = SpellCheckEngine() becomes self.SpellCheckEngine = get_spellcheck_engine().
  - ui/mainwindow.py (optional)
    - If uncommented spellcheck code instantiates SpellCheckEngine, update to use accessor.
- Files to be deleted or moved:
  - None.
- Configuration updates:
  - No config file schema changes; existing utils/config.py already stores spellcheck_language and enable_spellcheck.
  - Document in README or doc/ changelog about runtime language reload behavior (optional).

[Functions]  
High-level description of function changes.

- New functions:
  - get_spellcheck_engine(lang: Union[str,None]=None) -> SpellCheckEngine
    - File: utils/spell_check_engine.py
    - Purpose: return or create module-level singleton and ensure language matches requested lang (if provided). If lang differs, call engine.reload_language(lang).
  - reload_spellcheck_language(lang: str) -> SpellCheckEngine
    - File: utils/spell_check_engine.py
    - Purpose: convenience wrapper that forces engine to load for given language and returns it.
- Modified functions:
  - SpellCheckEngine.__init__(self, lang: Union[str,None]=None)
    - File: utils/spell_check_engine.py
    - Changes: keep as-is but ensure self.lang assigned from param or config; ensure no side effects beyond current behavior.
  - SpellCheckEngine.reload_language(self, lang: str)
    - File: utils/spell_check_engine.py
    - Changes: retain existing logic; ensure it updates self.lang and self.data_file and _load_data after loading dictionary.
  - ui/configpanel.on_spellcheck_language_changed(self)
    - File: ui/configpanel.py
    - Changes: after saving pcfg, call reload_spellcheck_language(sel) and handle exceptions (log and show brief message if reload fails).
  - ui/scenetext_manager.__init__ (or where engine is created)
    - File: ui/scenetext_manager.py
    - Changes: use get_spellcheck_engine() instead of direct class instantiation. No semantic changes to how unknown words are requested.
- Removed functions:
  - None.

[Classes]  
Describe class modifications.

- Modified classes:
  - SpellCheckEngine (utils/spell_check_engine.py)
    - Specific modifications:
      - No API surface removal. Add module-level factory/accessor; ensure instance methods DoSuggest, GetUnknownWordsViaDictionaryFromList, onWordDeleted, reload_language remain stable.
      - Document public API: should_run(), DoSuggest(word), GetUnknownWordsViaDictionaryFromList(words_with_objects), onWordDeleted(word), reload_language(lang).
- New classes:
  - None.
- Removed classes:
  - None.

[Dependencies]  
Single sentence: No new package dependencies required.

- The implementation uses existing spylls and utilities. No new pip packages are required.
- If background downloading is later desired, consider adding PyQt worker or threading; not part of this change.

[Testing]  
Single sentence: Add unit tests verifying engine creation, language reload, and unknown-word detection.

- tests/test_spell_check_engine.py:
  - Test cases:
    - test_engine_default_language_reads_config: ensure when no lang passed, engine.lang == pcfg.spellcheck_language.
    - test_engine_get_suggest_and_lookup: DoSuggest and dictionary.lookup behave for known/unknown word.
    - test_reload_language_switches_datafile: create engine, call reload_language('fr'), assert engine.lang == 'fr' and data file name updated.
    - test_get_unknown_words_via_list_respects_skipped_words: add a skipped word to engine.skipped_words and ensure it is not returned.
  - Use pytest and monkeypatch to avoid actual network downloads:
    - Monkeypatch download_and_check_files to a no-op.
    - If needed, monkeypatch Dictionary.from_files to a lightweight fake that supports lookup/suggest.
  - Keep tests idempotent and avoid writing to user home; tests should create temporary data directories if they write files.

[Implementation Order]  
Single sentence: Make minimal sequential edits to engine, wiring, and tests to enable safe, incremental integration.

1. Add module-level accessor functions and SUPPORTED_LANGS to utils/spell_check_engine.py and export get_spellcheck_engine and reload_spellcheck_language.
2. Update ui/scenetext_manager.py to use get_spellcheck_engine() instead of direct SpellCheckEngine instantiation.
3. Update ui/configpanel.py.on_spellcheck_language_changed to call reload_spellcheck_language(sel) after persisting the setting; handle exceptions and log.
4. Add tests/tests_spell_check_engine.py with monkeypatches to avoid network downloads; run tests and iterate until passing.
5. Run quick manual smoke test in app UI: change language in config panel and verify scene text spellcheck reflects new language; ensure skipped words are per-language files (SpellCheckEngine_{lang}.json).
6. Optional: if UI blocks too long during download, consider moving download logic into background task (follow-up task).