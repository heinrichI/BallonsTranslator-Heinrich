r"""
Тесты TransGemmaTranslator для провайдера llama-server (raw /v1/completions).

Live-интеграционные тесты ходят на реальный llama-server (127.0.0.1:1234) и
пропускаются, если сервер не запущен. Остальные тесты — unit (мок клиента).

Запуск:
    myenv\Scripts\python.exe -m pytest tests/test_trans_gemma_llama_server.py -v
"""

import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import httpx

from modules.translators.trans_llm_api_transgemma import (
    TransGemmaTranslator,
    TranslationElement,
    TranslationResponse,
    TranslationAbortedError,
    MAX_CONSECUTIVE_CONNECTION_ERRORS,
    _normalize_translation_payload,
)
from utils import shared

shared.HEADLESS = True

SERVER_URL = "http://127.0.0.1:1234"


def make_translator() -> TransGemmaTranslator:
    return TransGemmaTranslator(
        lang_source="English",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )


class FakeCompletion:
    def __init__(self, text: str):
        self.choices = [SimpleNamespace(text=text, message=None)]
        self.usage = SimpleNamespace(total_tokens=7)


class FakeCompletions:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.response_text)


@pytest.fixture
def mock_llama_client(monkeypatch):
    """Stub client so _request_translation talks to a fake completions endpoint."""
    def _make(response_text: str):
        tr = make_translator()
        completions = FakeCompletions(response_text)
        tr.client = SimpleNamespace(completions=completions, chat=None)
        monkeypatch.setattr(tr, "_initialize_client", lambda api_key: True)
        return tr, completions
    return _make


@pytest.fixture(scope="session")
def llama_server():
    """Skip all live tests when the llama-server is not reachable."""
    try:
        r = httpx.get(f"{SERVER_URL}/v1/models", timeout=3)
        if r.status_code != 200:
            pytest.skip(f"llama-server not ready (HTTP {r.status_code})")
    except Exception:
        pytest.skip("llama-server is not running on 127.0.0.1:1234")
    return SERVER_URL


# ---------- unit: raw prompt on completions endpoint ----------

def test_llama_request_raw_prompt(mock_llama_client):
    tr, completions = mock_llama_client(
        '{"translations":[{"id":1,"translation":"Привет"}]}'
    )
    tr._request_translation("Hello!")

    assert len(completions.calls) == 1
    kwargs = completions.calls[0]
    assert "messages" not in kwargs
    assert "prompt" in kwargs
    prompt = kwargs["prompt"]
    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>\n<start_of_turn>model" in prompt
    assert "You are a professional English (en) to Russian (ru) translator" in prompt
    assert kwargs["temperature"] == tr.temperature
    assert kwargs["top_p"] == tr.top_p
    assert kwargs["max_tokens"] == tr.max_tokens
    schema = kwargs.get("extra_body", {}).get("json_schema", {}).get("schema")
    assert schema is not None
    assert "translations" in schema.get("properties", {})


def test_prompt_has_id_prefixes_for_batch(mock_llama_client):
    tr, completions = mock_llama_client(
        '{"translations":[{"id":1,"translation":"Привет"},{"id":2,"translation":"Пока"}]}'
    )
    tr._request_translation("id=1: Hello\nid=2: Goodbye\n")
    prompt = completions.calls[0]["prompt"]
    assert "id=1: Hello" in prompt
    assert "id=2: Goodbye" in prompt
    assert "messages" not in completions.calls[0]


def test_build_llama_prompt_german():
    tr = TransGemmaTranslator(
        lang_source="Deutsch",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    prompt = tr._build_llama_prompt("Guten Morgen!", "de", "ru")
    assert "You are a professional German (de) to Russian (ru) translator" in prompt
    assert "Please translate the following German text into Russian" in prompt
    assert "Guten Morgen!" in prompt
    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>\n<start_of_turn>model" in prompt


def test_build_llama_prompt_with_context():
    tr = TransGemmaTranslator(
        lang_source="English",
        lang_target="русский язык",
        raise_unsupported_lang=False,
        context="юмористический подростковый комикс",
    )
    prompt = tr._build_llama_prompt("Hello!", "en", "ru")
    assert "Context: юмористический подростковый комикс." in prompt
    # context goes before the JSON instruction, which stays before "Please translate"
    assert prompt.index("Context:") < prompt.index("The output must be a valid JSON object")
    assert prompt.index("The output must be a valid JSON object") < prompt.index("Please translate")


def test_build_llama_prompt_no_context_by_default():
    tr = TransGemmaTranslator(
        lang_source="English",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    # params are class-shared in this app; reset explicitly to avoid leakage
    # from other tests that set a context value.
    tr.updateParam("context", "")
    prompt = tr._build_llama_prompt("Hello!", "en", "ru")
    assert "Context:" not in prompt


def test_build_llama_prompt_single_variant():
    tr = make_translator()
    prompt = tr._build_llama_prompt("TENNIS, ANYONE?", "en", "ru")
    assert "Provide exactly one translation variant" in prompt
    assert "do not use '/' or '|'" in prompt


# ---------- unit: parsing / normalization ----------

def test_native_single_dict_normalized(mock_llama_client):
    tr, _ = mock_llama_client('{"id":1,"speaker":"A","dialogue":"Привет"}')
    resp = tr._request_translation("Hello!")
    assert resp.translations[0].id == 1
    assert resp.translations[0].translation == "Привет"


def test_native_single_dict_normalization_helper():
    data = _normalize_translation_payload({"id": 1, "speaker": "A", "dialogue": "Привет"})
    assert data == {"translations": [{"id": 1, "translation": "Привет"}]}
    wrapper = {"translations": [{"id": 1, "translation": "Привет"}]}
    assert _normalize_translation_payload(wrapper) == wrapper


def test_wrapper_response(mock_llama_client):
    tr, _ = mock_llama_client('{"translations":[{"id":1,"translation":"Привет"}]}')
    resp = tr._request_translation("Hello!")
    assert resp.translations[0].translation == "Привет"


def test_markdown_fence_wrapper(mock_llama_client):
    tr, _ = mock_llama_client('```json\n{"translations":[{"id":1,"translation":"Привет"}]}\n```')
    resp = tr._request_translation("Hello!")
    assert resp.translations[0].translation == "Привет"


def test_extract_json_object_helper():
    from modules.translators.trans_llm_api_transgemma import _extract_json_object
    # Plain object
    assert _extract_json_object('{"a":1}') == '{"a":1}'
    # Markdown fence
    assert _extract_json_object('```json\n{"a":1}\n```') == '{"a":1}'
    # Braces inside a string are ignored
    assert _extract_json_object('{"a":"{not json}"}') == '{"a":"{not json}"}'
    # No object present
    assert _extract_json_object('just text') is None
    # Truncated object (no closing brace) -> None
    assert _extract_json_object('{"a":1') is None


def test_request_translation_handles_json_encoded_string(mock_llama_client):
    # The model may wrap the object in a JSON string: "{\"translations\":[...]}"
    tr, _ = mock_llama_client('"{\\"translations\\":[{\\"id\\":1,\\"translation\\":\\"Привет\\"}]}"')
    resp = tr._request_translation("Hello!")
    assert resp.translations[0].translation == "Привет"


def test_request_translation_no_json_object_raises(mock_llama_client):
    tr, _ = mock_llama_client("just some text without json")
    with pytest.raises(ValueError):
        tr._request_translation("Hello!")


def test_translate_single_falls_back_on_malformed(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None):
        raise ValueError("No JSON object found in API response.")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    # Falls back to the source text instead of crashing the whole job.
    assert translations == ["Hello"]


def test_translate_single_retries_then_falls_back(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        if len(calls) == 1:
            raise ValueError("transient failure")
        return TranslationResponse(translations=[TranslationElement(id=1, translation="Привет")])

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    assert len(calls) == 2
    assert translations == ["Привет"]


def test_single_alternative_helper():
    tr = make_translator()
    assert tr._single_alternative("В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?") == "В ТЕННИС ПОИГРАЕМ?"
    assert tr._single_alternative("Привет | Пока") == "Привет"
    assert tr._single_alternative("Обычный перевод") == "Обычный перевод"
    assert tr._single_alternative("  С пробелами  ") == "С пробелами"


def test_single_alternative_logs_warning(monkeypatch):
    from unittest.mock import MagicMock

    tr = make_translator()
    mock_warn = MagicMock()
    monkeypatch.setattr(tr.logger, "warning", mock_warn)
    result = tr._single_alternative("В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?")
    assert result == "В ТЕННИС ПОИГРАЕМ?"
    mock_warn.assert_called_once()
    assert "Multiple translation variants detected" in mock_warn.call_args[0][0]


def test_request_translation_cleans_alternatives(mock_llama_client):
    tr, _ = mock_llama_client(
        '{"translations":[{"id":1,"translation":"В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?"}]}'
    )
    resp = tr._request_translation("TENNIS, ANYONE?")
    assert resp.translations[0].translation == "В ТЕННИС ПОИГРАЕМ?"


# ---------- unit: slash-separated lists in the source are preserved ----------

def test_single_alternative_preserves_slash_list_source():
    tr = make_translator()
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    # The source itself uses '/' as a list separator, so the output must be
    # kept intact — it is a faithful rendering of the credits, not alternatives.
    assert tr._single_alternative(out, src) == out


def test_single_alternative_preserves_leaked_credits_line():
    tr = make_translator()
    # When the model echoes the request's id=N: prefix, _single_alternative must
    # NOT truncate — it leaves the full text so _find_problems can flag it and
    # the batch binary-splits down to a single element re-translated with its source.
    leaked = "id=6: Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    assert tr._single_alternative(leaked, "") == leaked


def test_single_alternative_preserves_pipe_list_source():
    tr = make_translator()
    src = "A | B | C"
    out = "А | Б | В"
    assert tr._single_alternative(out, src) == out


def test_single_alternative_still_splits_plain_source():
    tr = make_translator()
    # Regression guard: when the source has no separator, the model-provided
    # alternatives must still be collapsed to the first variant.
    assert tr._single_alternative("В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?", "TENNIS, ANYONE?") == "В ТЕННИС ПОИГРАЕМ?"
    assert tr._single_alternative("Привет | Пока", "Hello") == "Привет"


def test_request_translation_preserves_slash_credits(mock_llama_client):
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    tr, _ = mock_llama_client(f'{{"translations":[{{"id":1,"translation":"{out}"}}]}}')
    resp = tr._request_translation(src, srcs=[src])
    assert resp.translations[0].translation == out


def test_translate_credits_line_preserved(monkeypatch):
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None):
        return TranslationResponse(
            translations=[TranslationElement(id=1, translation=out)]
        )

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    result = tr._translate([src])
    assert result == [out]


# ---------- unit: prompt assembly / id-leak gating ----------

def test_pack_batches_whole_first():
    tr = make_translator()
    tr.n_ctx = 6144
    batches = list(tr._pack_batches(["a\nb", "c"]))
    # whole text first: one batch with id=N: prefixes and all indices
    assert batches == [("id=1: a b\nid=2: c\n", 2, [0, 1])]


def test_estimate_tokens_cjk():
    tr = make_translator()
    # CJK chars ~1 token each
    assert tr._estimate_tokens("日本語") == 3
    # Latin ~4 chars per token
    assert tr._estimate_tokens("hello") == 2  # ceil(5/4)


def test_pack_batches_splits_on_budget():
    tr = make_translator()
    tr.n_ctx = 300
    tr.updateParam("max tokens", 100)
    # budget = max(256, 300 - 100 - 150) = 256; limit = 230.4
    # Each long phrase ~ (40/4)*1.3 + 15 = 28 tokens; 8 phrases exceed the limit.
    queries = ["word " * 10] * 8
    batches = list(tr._pack_batches(queries))
    assert len(batches) > 1
    # All indices covered exactly once, in order
    all_idx = [i for _, _, idx in batches for i in idx]
    assert all_idx == list(range(8))


def test_pack_batches_single_oversized():
    tr = make_translator()
    tr.n_ctx = 300
    tr.updateParam("max tokens", 100)
    # A single phrase larger than the budget is still sent alone.
    queries = ["word " * 200]
    batches = list(tr._pack_batches(queries))
    assert len(batches) == 1
    assert batches[0][1] == 1
    assert batches[0][2] == [0]


def _resp(*items):
    return TranslationResponse(translations=[TranslationElement(id=i, translation=t) for i, t in items])


def test_translate_batch_success_single_request(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        return _resp((1, "Привет"), (2, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 1
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_mismatch(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        # Whole batch returns only one translation -> mismatch -> split
        if "id=1: Hello" in text and "id=2: Bye" in text:
            return _resp((1, "Привет"))
        # Halves succeed
        if "id=1: Hello" in text:
            return _resp((1, "Привет"))
        if "id=1: Bye" in text:
            return _resp((1, "Пока"))
        return _resp((1, "?"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    # 1 whole + 2 halves = 3 requests
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_empty(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        if "id=1: Hello" in text and "id=2: Bye" in text:
            return _resp((1, "Привет"), (2, ""))  # empty translation -> problem
        if "id=1: Hello" in text:
            return _resp((1, "Привет"))
        if "id=1: Bye" in text:
            return _resp((1, "Пока"))
        return _resp((1, "?"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_exception(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        if "id=1: Hello" in text and "id=2: Bye" in text:
            raise ValueError("boom")
        if "id=1: Hello" in text:
            return _resp((1, "Привет"))
        if "id=1: Bye" in text:
            return _resp((1, "Пока"))
        return _resp((1, "?"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_single_leaf_raises(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True):
        return _resp((1, ""))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    with pytest.raises(Exception):
        tr._translate_batch(["Hello"], [0], translations)


def test_find_problems_empty_and_ratio():
    tr = make_translator()
    # empty translation for non-empty source
    assert tr._find_problems(["Hello"], [""]) == [0]
    # short phrase with bad ratio is skipped
    assert tr._find_problems(["OK"], ["Хорошо"]) == []
    # long phrase with low ratio is a problem
    long_src = "This is a fairly long English sentence that should be translated fully"
    assert tr._find_problems([long_src], ["Кратко"]) == [0]


def test_find_problems_high_ratio_short_source():
    tr = make_translator()
    # A short source ("THE") hallucinated into a long title must be flagged,
    # even though len(src) <= 25 (the old guard skipped short sources entirely).
    assert tr._find_problems(["THE"], ["«ИГРА № 1: БЭТТИ И ВЕРОНИКА»"]) == [0]


def test_find_problems_high_ratio_short_source_ok_not_flagged():
    tr = make_translator()
    # Legitimate short translation with a high ratio must NOT be flagged.
    assert tr._find_problems(["OK"], ["Хорошо"]) == []


def test_find_problems_high_ratio_long_source_still_flagged():
    tr = make_translator()
    # Long source with a high ratio is still flagged (existing behavior).
    long_src = "This is a fairly long English sentence that should be translated fully"
    # Translation is 3x the source length -> ratio 3.0 > 2.0 -> flagged.
    assert tr._find_problems([long_src], [long_src * 3]) == [0]


def test_is_high_ratio_problem_helper():
    tr = make_translator()
    # Short source -> long hallucinated title: flagged.
    assert tr._is_high_ratio_problem("THE", "«ИГРА № 1: БЭТТИ И ВЕРОНИКА»") is True
    # Short source -> short legitimate translation: not flagged.
    assert tr._is_high_ratio_problem("OK", "Хорошо") is False
    # Long source -> proportionally long translation: not flagged.
    assert tr._is_high_ratio_problem("Hello world", "Привет мир") is False
    # Long source -> extremely long translation: flagged.
    assert tr._is_high_ratio_problem("Hi", "Это очень длинный перевод короткого слова") is True


def test_fetch_context_window_llama(monkeypatch):
    tr = make_translator()
    tr.n_ctx = None

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"default_generation_settings": {"n_ctx": 6144}}

    monkeypatch.setattr(httpx, "get", lambda url, timeout=5: FakeResp())
    tr._fetch_context_window()
    assert tr.n_ctx == 6144


def test_fetch_context_window_fallback(monkeypatch):
    tr = make_translator()
    tr.n_ctx = None

    def boom(url, timeout=5):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(httpx, "get", boom)
    tr._fetch_context_window()
    assert tr.n_ctx == 6144  # llama-server fallback


def test_request_translation_show_dialog_false(monkeypatch):
    from unittest.mock import MagicMock
    import modules.translators.trans_llm_api_transgemma as mod

    tr = make_translator()
    tr.client = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: FakeCompletion("not json")))
    monkeypatch.setattr(tr, "_initialize_client", lambda api_key: True)
    monkeypatch.setattr(tr, "_fetch_context_window", lambda: None)
    mock_dialog = MagicMock()
    monkeypatch.setattr(mod, "create_error_dialog", mock_dialog)
    with pytest.raises(Exception):
        tr._request_translation("Hello", show_dialog=False)
    mock_dialog.assert_not_called()


def test_id_leak_skipped_for_llama(monkeypatch):
    tr = make_translator()
    assert tr.provider == "llama-server"

    def fake_request(text, show_dialog=True):
        return TranslationResponse(
            translations=[TranslationElement(id=1, translation="Привет мир}]}")]
        )

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    # id-leak regex matches the trailing }]} artifact, but for llama-server the
    # check must be skipped: exactly one request, no retry, no exception.
    result = tr._translate(["Hello world"])
    assert result == ["Привет мир}]}"]


def test_id_leak_regex_still_matches():
    tr = make_translator()
    assert tr._has_id_leak("text }]}")


def test_has_id_prefix_leak_helper():
    tr = make_translator()
    # Echoed id=N: prefix -> True
    assert tr._has_id_prefix_leak("id=6: Ф. Дойл / Д. ДеКарло") is True
    # {ID=N} prefix -> True
    assert tr._has_id_prefix_leak("{ID=2} текст") is True
    # Trailing "}]}" artifact is NOT a prefix leak -> False
    assert tr._has_id_prefix_leak("Привет мир}]}") is False
    # Clean translation -> False
    assert tr._has_id_prefix_leak("Ф. Дойл / Д. ДеКарло") is False


def test_find_problems_id_prefix_leak_llama():
    tr = make_translator()
    assert tr.provider == "llama-server"
    # Even for llama-server, an echoed id=N: prefix must be flagged so the
    # batch binary-splits and the element is re-translated with its source.
    assert tr._find_problems(["F. Doyle / D. DeCarlo"], ["id=6: Ф. Дойл / Д. ДеКарло"]) == [0]


def test_translate_single_no_dialog_on_fallback(monkeypatch):
    import modules.translators.trans_llm_api_transgemma as mod
    from unittest.mock import MagicMock

    tr = make_translator()
    mock_dialog = MagicMock()
    monkeypatch.setattr(mod, "create_error_dialog", mock_dialog)

    def fake_request(text, show_dialog=True, srcs=None):
        raise ValueError("No JSON object found in API response.")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    # Graceful fallback must NOT pop an error dialog.
    assert translations == ["Hello"]
    mock_dialog.assert_not_called()


# ---------- unit: abort whole run after repeated connection errors ----------

def test_request_translation_aborts_after_threshold(monkeypatch):
    """4 consecutive connection errors raise TranslationAbortedError."""
    tr = make_translator()
    tr.client = SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: (_ for _ in ()).throw(httpx.ConnectError("server down"))
    ))
    monkeypatch.setattr(tr, "_initialize_client", lambda api_key: True)
    monkeypatch.setattr(tr, "_fetch_context_window", lambda: None)

    # First 3 failures raise the underlying ConnectionError (counted, not aborted).
    for _ in range(MAX_CONSECUTIVE_CONNECTION_ERRORS):
        with pytest.raises(httpx.ConnectError):
            tr._request_translation("Hello", show_dialog=False)
    assert tr.connection_error_count == MAX_CONSECUTIVE_CONNECTION_ERRORS

    # 4th failure exceeds the threshold -> abort.
    with pytest.raises(TranslationAbortedError):
        tr._request_translation("Hello", show_dialog=False)


def test_request_translation_resets_counter_on_success(monkeypatch):
    """A successful request resets the counter, so a flaky server does not abort."""
    tr = make_translator()
    calls = {"n": 0}

    def flaky_create(**kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ConnectError("transient")
        return FakeCompletion('{"translations":[{"id":1,"translation":"Привет"}]}')

    tr.client = SimpleNamespace(completions=SimpleNamespace(create=flaky_create))
    monkeypatch.setattr(tr, "_initialize_client", lambda api_key: True)
    monkeypatch.setattr(tr, "_fetch_context_window", lambda: None)

    # Two failures, then a success -> counter resets to 0.
    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            tr._request_translation("Hello", show_dialog=False)
    assert tr.connection_error_count == 2
    resp = tr._request_translation("Hello", show_dialog=False)
    assert resp.translations[0].translation == "Привет"
    assert tr.connection_error_count == 0


def test_translate_single_reraises_abort(monkeypatch):
    """_translate_single must NOT fall back to source text on TranslationAbortedError."""
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None):
        raise TranslationAbortedError("abort")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    with pytest.raises(TranslationAbortedError):
        tr._translate_single("Hello", 0, translations)
    # No fallback happened.
    assert translations == [""]


def test_translate_batch_reraises_abort_no_split(monkeypatch):
    """_translate_batch must re-raise TranslationAbortedError without binary-splitting."""
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None):
        calls.append(text)
        raise TranslationAbortedError("abort")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    with pytest.raises(TranslationAbortedError):
        tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    # Exactly one request — no recursive split.
    assert len(calls) == 1


def test_translate_propagates_abort(monkeypatch):
    """_translate propagates TranslationAbortedError so the whole page run stops."""
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None):
        raise TranslationAbortedError("abort")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    with pytest.raises(TranslationAbortedError):
        tr._translate(["Hello", "Bye"])


def test_is_connection_error_helper():
    tr = make_translator()
    assert tr._is_connection_error(ConnectionError("x")) is True
    assert tr._is_connection_error(httpx.ConnectError("x")) is True
    assert tr._is_connection_error(httpx.TimeoutException("x")) is True
    # Server-side API errors are NOT connection errors.
    assert tr._is_connection_error(ValueError("bad json")) is False
    assert tr._is_connection_error(RuntimeError("boom")) is False


# ---------- live integration (requires llama-server on 127.0.0.1:1234) ----------

def test_live_single_translate(llama_server):
    tr = make_translator()
    result = tr._translate(["Hello!"])
    assert result and result[0].strip()
    assert "id=" not in result[0].lower()
    assert "{id" not in result[0].lower()


def test_live_wrapper_json_valid(llama_server):
    tr = make_translator()
    resp = tr._request_translation("Good morning!")
    assert isinstance(resp, TranslationResponse)
    assert len(resp.translations) == 1
    assert resp.translations[0].id == 1
    assert resp.translations[0].translation.strip()


def test_live_no_id_artifacts(llama_server):
    tr = make_translator()
    result = tr._translate(["See you tomorrow."])
    assert result and result[0].strip()
    assert "id=" not in result[0].lower()
    assert "id:" not in result[0].lower()
    assert "{ID" not in result[0]


def test_live_german_translate(llama_server):
    tr = TransGemmaTranslator(
        lang_source="Deutsch",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    result = tr._translate(["Guten Morgen! Wie geht es dir?"])
    assert result and result[0].strip()
    # Must be an actual Russian translation, not an echo of the German source.
    assert any("а" <= ch <= "я" for ch in result[0].lower())
    assert "Guten Morgen" not in result[0]
    assert "id=" not in result[0].lower()
    assert "{ID" not in result[0]


def test_live_german_with_context(llama_server):
    tr = TransGemmaTranslator(
        lang_source="Deutsch",
        lang_target="русский язык",
        raise_unsupported_lang=False,
        context="юмористический подростковый комикс, разговорный сленг",
    )
    result = tr._translate(["Das ist ja der Hammer!"])
    assert result and result[0].strip()
    assert any("а" <= ch <= "я" for ch in result[0].lower())
    # context must not leak into the translation itself
    assert "Context:" not in result[0]
    assert "комикс" not in result[0].lower()
    assert "id=" not in result[0].lower()


def test_live_single_variant_no_alternatives(llama_server):
    tr = make_translator()
    result = tr._translate(["TENNIS, ANYONE?"])
    assert result and result[0].strip()
    assert " / " not in result[0]
    assert " | " not in result[0]


def test_live_batch_translate_multiple(llama_server):
    tr = make_translator()
    result = tr._translate(["Hello!", "Goodbye!", "See you tomorrow."])
    assert len(result) == 3
    for r in result:
        assert r and r.strip()
        assert "id=" not in r.lower()
        assert "{ID" not in r
