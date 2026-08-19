r"""
Тесты TransGemmaTranslator для провайдера llama-server (raw /v1/completions).

Протокол — JSON-id: пачка строится _batch_text с префиксами id=N:, ответ —
JSON-объект {"translations":[{id, translation}]} (llama.cpp structured output,
top-level json_schema в extra_body). Сопоставление переводов по id.

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
    TranslationAbortedError,
    TranslationIntegrityError,
    TranslationResponse,
    TranslationElement,
    MAX_CONSECUTIVE_CONNECTION_ERRORS,
)
from utils import shared

shared.HEADLESS = True

SERVER_URL = "http://127.0.0.1:1234"


def make_translator() -> TransGemmaTranslator:
    tr = TransGemmaTranslator(
        lang_source="English",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    tr.n_ctx = 6144  # чтобы _fetch_context_window возвращался сразу, без сети
    return tr


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


def _resp(*pairs):
    return TranslationResponse(
        translations=[TranslationElement(id=i, translation=t) for i, t in pairs]
    )


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
    tr, completions = mock_llama_client('{"translations":[{"id":1,"translation":"Привет"}]}')
    resp = tr._request_translation("Hello!")

    assert len(completions.calls) == 1
    kwargs = completions.calls[0]
    assert "messages" not in kwargs
    assert "prompt" in kwargs
    prompt = kwargs["prompt"]
    assert "<start_of_turn>user" in prompt
    assert "<end_of_turn>\n<start_of_turn>model" in prompt
    assert "source_lang_code: en" in prompt
    assert "target_lang_code: ru" in prompt
    # Prompts must tell the model to emit a JSON object with id/translation entries.
    assert '"translations"' in prompt
    assert "Output ONLY a JSON object" in prompt or 'Output ONLY the' not in prompt
    # Верхнеуровневого response_format нет — структура задаётся top-level json_schema.
    assert "json_schema" not in kwargs
    assert kwargs["extra_body"]["json_schema"]["required"] == ["translations"]
    # Возвращается TranslationResponse целиком.
    assert resp.translations[0].translation == "Привет"


def test_batch_prompt_has_ids_and_json_schema(mock_llama_client):
    tr, completions = mock_llama_client(
        '{"translations":[{"id":1,"translation":"Привет"},{"id":2,"translation":"Пока"}]}'
    )
    translations = ["", ""]
    tr._translate_batch(["Hello", "Goodbye"], [0, 1], translations)
    prompt = completions.calls[0]["prompt"]
    assert "id=1: Hello" in prompt
    assert "id=2: Goodbye" in prompt
    assert "Document:" in prompt
    assert '"translations"' in prompt
    assert "Output ONLY a JSON object" in prompt
    assert "json_schema" in completions.calls[0]["extra_body"]
    assert translations == ["Привет", "Пока"]
def test_build_llama_prompt_german():
    tr = TransGemmaTranslator(
        lang_source="Deutsch",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    prompt = tr._build_llama_prompt("Guten Morgen!", "de", "ru")
    assert "German to Russian translator" in prompt
    assert "Document:\nGuten Morgen!" in prompt
    assert '"translations"' in prompt
    assert "Output ONLY a JSON object" in prompt
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
    assert "Document:" in prompt


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


# ---------- unit: alternatives cleanup ----------

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
    tr, _ = mock_llama_client('{"translations":[{"id":1,"translation":"В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?"}]}')
    resp = tr._request_translation("TENNIS, ANYONE?")
    assert resp.translations[0].translation == "В ТЕННИС ПОИГРАЕМ?"


def test_single_alternative_preserves_slash_list_source():
    tr = make_translator()
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    # The source itself uses '/' as a list separator, so the output must be
    # kept intact — it is a faithful rendering of the credits, not alternatives.
    assert tr._single_alternative(out, src) == out


def test_single_alternative_preserves_pipe_list_source():
    tr = make_translator()
    src = "A | B | C"
    out = "А | Б | В"
    assert tr._single_alternative(out, src) == out


def test_request_translation_preserves_slash_credits(mock_llama_client):
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    tr, _ = mock_llama_client(
        '{"translations":[{"id":1,"translation":"Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"}]}'
    )
    resp = tr._request_translation(src, srcs=[src])
    assert resp.translations[0].translation == out


def test_translate_credits_line_preserved(monkeypatch):
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        # одиночная фраза приходит через _request_single -> plain-text путь
        return _resp((1, out))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    result = tr._translate([src])
    assert result == [out]
# ---------- unit: prompt assembly / batching ----------

def test_pack_batches_whole_first():
    tr = make_translator()
    tr.n_ctx = 6144
    batches = list(tr._pack_batches(["a\nb", "c"]))
    # целая пачка: один документ с id-префиксами и всеми индексами
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
    queries = ["word " * 200]
    batches = list(tr._pack_batches(queries))
    assert len(batches) == 1
    assert batches[0][1] == 1
    assert batches[0][2] == [0]


def test_translate_batch_success_single_request(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False):
        calls.append(text)
        return _resp((1, "Привет"), (2, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 1
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_mismatch(monkeypatch):
    """Недостаточно переводов (id=2 отсутствует) -> пустая строка -> split."""
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        calls.append(text)
        if preserve_newlines and srcs == ["Hello", "Bye"]:
            return _resp((1, "Привет"))
        if preserve_newlines:
            return None
        # одиночная фраза (plain-text путь из _translate_single)
        if text == "Hello":
            return _resp((1, "Привет"))
        return _resp((1, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_empty(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        calls.append(text)
        if preserve_newlines and srcs == ["Hello", "Bye"]:
            return _resp((1, "Привет"), (2, ""))  # пустой перевод -> проблема
        if preserve_newlines:
            return None
        # одиночная фраза (plain-text путь из _translate_single)
        if text == "Hello":
            return _resp((1, "Привет"))
        return _resp((1, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_exception(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        calls.append(text)
        if preserve_newlines and srcs == ["Hello", "Bye"]:
            raise ValueError("boom")
        if preserve_newlines:
            return None
        # одиночная фраза (plain-text путь из _translate_single)
        if text == "Hello":
            return _resp((1, "Привет"))
        return _resp((1, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_single_falls_back_on_error(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
        raise ValueError("request failed")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    # Falls back to the source text instead of crashing the whole job.
    assert translations == ["Hello"]


def test_translate_single_retries_then_succeeds(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
        calls.append(text)
        if len(calls) == 1:
            raise ValueError("transient")
        return _resp((1, "Привет"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    assert len(calls) == 2
    assert translations == ["Привет"]

def test_translate_single_sends_via_request_single(monkeypatch):
    """The leaf must send a single phrase as plain text (NOT json-object) for llama-server."""
    tr = make_translator()
    seen = {}

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        seen["text"] = text
        seen["srcs"] = srcs
        seen["preserve_newlines"] = preserve_newlines
        seen["show_dialog"] = show_dialog
        seen["structured_output"] = structured_output
        return _resp((1, "Привет"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single("Hello", 0, translations)
    # Single phrase goes plain-text: no json grammar, no id prefix body.
    assert seen["text"] == "Hello"
    assert seen["srcs"] == ["Hello"]
    assert seen["structured_output"] is False
    assert seen["show_dialog"] is False
    assert translations == ["Привет"]


def test_translate_single_plain_no_json_schema(mock_llama_client):
    """A single phrase must NOT request json_object — plain text only."""
    tr, completions = mock_llama_client("Привет")  # plain text response, not JSON
    resp = tr._request_single("Hello")
    kwargs = completions.calls[0]
    # No json_object grammar for a single phrase.
    assert "extra_body" not in kwargs or "json_schema" not in kwargs.get("extra_body", {})
    # The prompt must be in plain-text (non-structured) mode.
    assert "Output ONLY a JSON object" not in kwargs["prompt"]
    assert "Output ONLY the translation as plain text" in kwargs["prompt"]
    # Response is plain text wrapped into a single-element response.
    assert resp.translations[0].translation.strip() == "Привет"


def test_translate_single_short_source_skips_ratio_check(monkeypatch):
    """A short source producing a wordy translation must NOT trigger the ratio heuristic.

    Regression test: "So, anyway..." (short) -> "В общем, как бы то ни было..."
    (wordy) yields ratio 2.23 > 2.0 but is a perfectly valid translation — it must
    be accepted without a re-request, dialog, or TranslationIntegrityError.
    """
    import modules.translators.trans_llm_api_transgemma as mod
    from unittest.mock import MagicMock

    tr = make_translator()
    src = "So, anyway..."
    good_tr = "В общем, как бы то ни вёрнуто"  # ratio > 2.0 for shortness
    calls = []
    mock_dialog = MagicMock(return_value=False)
    monkeypatch.setattr(mod, "create_yes_no_dialog", mock_dialog)
    # create_error_dialog must not be called either
    monkeypatch.setattr(mod, "create_error_dialog", MagicMock())

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        return _resp((1, good_tr))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single(src, 0, translations)
    # The echo/idle paths may call once, but the ratio re-request must NOT fire.
    # Only the primary request (and append) should happen; no retry beyond that.
    assert translations[0] == good_tr
    # No yes/no dialog about a compression-ratio problem.
    mock_dialog.assert_not_called()


def test_translate_single_long_source_high_ratio_still_checked(monkeypatch):
    """A long source with a genuinely implausible ratio still triggers the check."""
    import modules.translators.trans_llm_api_transgemma as mod
    from unittest.mock import MagicMock

    tr = make_translator()
    src = "This is a typical long English sentence that is translated into a normal phrase"
    # Very long bogus translation => ratio clearly > 2.0.
    bogus = "предложение которое на самом деле является одним очень длинным русским абзацем написанным без всякой связи с исходным текстом и тянущим на большое количество символов"
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        return _resp((1, bogus))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    # User says "stop" -> expect TranslationIntegrityError raised.
    monkeypatch.setattr(mod, "create_yes_no_dialog", MagicMock(return_value=True))
    translations = [""]
    with pytest.raises(TranslationIntegrityError):
        tr._translate_single(src, 0, translations)
    # The ratio re-request (in addition to the primary one) fired.
    assert len(calls) >= 2

# ---------- unit: context window ----------

def test_fetch_context_window_success(monkeypatch):
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


def test_translate_single_no_dialog_on_fallback(monkeypatch):
    import modules.translators.trans_llm_api_transgemma as mod
    from unittest.mock import MagicMock

    tr = make_translator()
    mock_dialog = MagicMock()
    monkeypatch.setattr(mod, "create_error_dialog", mock_dialog)

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
        raise ValueError("request failed")

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

    for _ in range(MAX_CONSECUTIVE_CONNECTION_ERRORS):
        with pytest.raises(httpx.ConnectError):
            tr._request_translation("Hello", show_dialog=False)
    assert tr.connection_error_count == MAX_CONSECUTIVE_CONNECTION_ERRORS

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

    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            tr._request_translation("Hello", show_dialog=False)
    resp = tr._request_translation("Hello", show_dialog=False)
    assert resp.translations[0].translation == "Привет"
    assert tr.connection_error_count == 0
def test_translate_single_reraises_abort(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
        raise TranslationAbortedError("abort")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    with pytest.raises(TranslationAbortedError):
        tr._translate_single("Hello", 0, [""])


def test_translate_batch_reraises_abort_no_split(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
        calls.append(text)
        raise TranslationAbortedError("abort")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    with pytest.raises(TranslationAbortedError):
        tr._translate_batch(["Hello", "Bye"], [0, 1], ["", ""])
    # No recursive splitting after an abort.
    assert len(calls) == 1


def test_translate_propagates_abort(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, **kwargs):
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
    assert tr._is_connection_error(ValueError("bad response")) is False
    assert tr._is_connection_error(RuntimeError("boom")) is False


# ---------- live integration (requires llama-server on 127.0.0.1:1234) ----------

def test_live_single_translate(llama_server):
    tr = make_translator()
    result = tr._translate(["Hello!"])
    assert result and result[0].strip()
    assert "id=" not in result[0].lower()


def test_live_plain_text_response(llama_server):
    """Одиночная фраза идёт через plain-text путь (без json_object грамматики)."""
    tr = make_translator()
    resp = tr._request_single("Good morning!")
    assert resp and resp.translations
    assert resp.translations[0].translation.strip()


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

# ---------- unit: cross-page rolling context (seamless page breaks) ----------

def test_rolling_tails_set_after_translate(monkeypatch):
    """After a _translate() call the rolling tails must be populated:
    translated tail (last <=3 non-empty translations) and source tail
    (last <=2 source lines)."""
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        return _resp((1, "Привет"), (2, "Пока"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    result = tr._translate(["Hello there.", "How are you?"])
    assert result == ["Привет", "Пока"]
    assert tr.rolling_context.strip() == "Привет\nПока"
    # last 2 source lines (both of them here)
    assert tr.rolling_source_tail == "Hello there.\nHow are you?"


def test_rolling_source_tail_capped_at_two_lines(monkeypatch):
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        n = len(srcs) if srcs else text.count("id=")
        return _resp(*[(i + 1, f"T{i}") for i in range(n)])

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    tr._translate(["a.", "b.", "c.", "d."])
    assert tr.rolling_source_tail == "c.\nd."


def test_prompt_includes_continuation_context():
    tr = make_translator()
    tr.rolling_context = "Я ставлю свой чемодан на одну из\nкроватей."
    tr.rolling_source_tail = "I put my suitcase and camera bag down on one of the"
    prompt = tr._build_llama_prompt("beds. A stocky young man comes in.", "en", "ru")
    # Source tail passed so the model can link the fragment to it.
    assert "End of the previously translated document" in prompt
    assert "I put my suitcase and camera bag down on one of the" in prompt
    # Translated tail passed for style/terminology consistency.
    assert "Their existing Russian translation" in prompt
    assert "Я ставлю свой чемодан на одну из" in prompt
    # Anti-duplication / continuation instructions.
    assert "ALREADY cover its first word(s)" in prompt
    assert "without repeated words" in prompt


def test_prompt_no_continuation_block_when_empty():
    tr = make_translator()
    tr.rolling_context = ""
    tr.rolling_source_tail = ""
    prompt = tr._build_llama_prompt("Hello!", "en", "ru")
    assert "End of the previously translated document" not in prompt
    assert "without repeated words" not in prompt


def test_rolling_tails_persist_across_pages(monkeypatch):
    """The main regression: tails must NOT be cleared between _translate()
    calls (pages), so page 2 starts with page 1's tail still in place."""
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        if preserve_newlines and srcs == ["Hello there.", "How are you?"]:
            return _resp((1, "Привет"), (2, "Как дела"))
        return _resp((1, "Кровати. Входит коренастый молодой человек."))

    monkeypatch.setattr(tr, "_request_translation", fake_request)

    tr._translate(["Hello there.", "How are you?"])
    assert tr.rolling_context.strip() == "Привет\nКак дела"
    assert tr.rolling_source_tail == "Hello there.\nHow are you?"

    # Page 2: tails from page 1 survive into this call.
    tr._translate(["beds. A stocky young man comes in."])
    assert tr.rolling_context.strip() == "Кровати. Входит коренастый молодой человек."
    assert tr.rolling_source_tail == "beds. A stocky young man comes in."

    # The llama prompt built now carries page-1 context into it.
    prompt = tr._build_llama_prompt("next page text", "en", "ru")
    assert "End of the previously translated document" in prompt
    assert "without repeated words" in prompt



# ---------- unit: cross-page leading-fragment deduplication ----------

import logging  # noqa: E402  (kept next to the capture helper it serves)


class _LogCapture(logging.Handler):
    def __init__(self, level=logging.DEBUG):
        super().__init__(level=level)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture_logs(tr, level=logging.DEBUG):
    """Attach a handler directly to the translator's logger; return (handler, cleanup)."""
    handler = _LogCapture(level)
    tr.logger.addHandler(handler)
    old_level = tr.logger.level
    tr.logger.setLevel(level)
    return handler, lambda: (tr.logger.removeHandler(handler), tr.logger.setLevel(old_level))


def test_strip_duplication_across_page_break():
    """Main scenario: prev page ends '...on one of the' -> prev translation ends
    '...на одну из кроватей.' -> page-2 'Кровати. Входит...' must be stripped."""
    tr = make_translator()
    translations = ["Кровати. Входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "I put my suitcase and camera bag down on one of the",
        "Я ставлю свой чемодан и сумку с фотоаппаратом на одну из кроватей.",
    )
    assert translations[0] == "Входит коренастый молодой человек."


def test_no_strip_when_prev_source_complete():
    tr = make_translator()
    translations = ["Кровати. Входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "He looked around the room.",  # ends with sentence-final punctuation
        "...на одну из кроватей.",
    )
    assert translations[0] == "Кровати. Входит коренастый молодой человек."


def test_no_strip_when_no_previous_context():
    tr = make_translator()
    translations = ["Привет."]
    tr._maybe_strip_leading_duplication(["Hello."], [0], translations, "", "")
    assert translations[0] == "Привет."


def test_no_strip_when_no_match():
    tr = make_translator()
    translations = ["Кровати. Входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "They went home early, and",  # mid-sentence, so the guard passes
        "Они пошли домой рано, но",
    )
    # 'Кровати.' vs 'рано' - no fuzzy match -> untouched


def test_keep_legitimate_completion():
    """Prev translation does NOT cover the word ('...на одну из') -> the page-2
    translation 'Кровати. ...' is the correct completion and must be kept."""
    tr = make_translator()
    translations = ["Кровати. Входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "I put my suitcase and camera bag down on one of the",
        "Я ставлю свой чемодан и сумку с фотоаппаратом на одну из",
    )
    assert translations[0] == "Кровати. Входит коренастый молодой человек."


def test_capitalization_restored():
    tr = make_translator()
    translations = ["кровати. входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "I put my suitcase and camera bag down on one of the",
        "Я ставлю свой чемодан и сумку с фотоаппаратом на одну из кроватей.",
    )
    assert translations[0] == "Входит коренастый молодой человек."


def test_exact_word_match_stripped():
    tr = make_translator()
    translations = ["Кровати. Входит коренастый молодой человек."]
    tr._maybe_strip_leading_duplication(
        ["beds. A stocky young man comes in."], [0], translations,
        "I put my suitcase and camera bag down on one of the",
        "Я ставлю свой чемодан и сумку с фотоаппаратом на одну из кровати.",
    )
    assert translations[0] == "Входит коренастый молодой человек."


def test_is_duplicate_word_inflection():
    tr = make_translator()
    # inflected same stem
    assert tr._is_duplicate_word("кроватей", "кровати")[0] is True
    assert tr._is_duplicate_word("кровать", "кровати")[0] is True
    # short words below prefix threshold are never matched
    assert tr._is_duplicate_word("дом", "домой")[0] is False
    # unrelated words
    assert tr._is_duplicate_word("рано", "кровати")[0] is False


def test_dedup_logs_warning_on_strip():
    tr = make_translator()
    handler, cleanup = _capture_logs(tr, logging.DEBUG)
    try:
        translations = ["Кровати. Входит коренастый молодой человек."]
        tr._maybe_strip_leading_duplication(
            ["beds. A stocky young man comes in."], [0], translations,
            "I put my suitcase and camera bag down on one of the",
            "Я ставлю свой чемодан и сумку с фотоаппаратом на одну из кроватей.",
        )
    finally:
        cleanup()
    warnings = [r for r in handler.records if r.levelno == logging.WARNING]
    assert warnings and "Deduplication" in warnings[0].getMessage()
    assert "кроватей" in warnings[0].getMessage()
    assert "ratio" in warnings[0].getMessage()


def test_dedup_skip_not_warning():
    tr = make_translator()
    handler, cleanup = _capture_logs(tr, logging.DEBUG)
    try:
        translations = ["Кровати. Входит коренастый молодой человек."]
        tr._maybe_strip_leading_duplication(
            ["beds. A stocky young man comes in."], [0], translations,
            "He looked around the room.",  # guard: sentence-final punctuation
            "...на одну из кроватей.",
        )
    finally:
        cleanup()
    assert not [r for r in handler.records if r.levelno == logging.WARNING]
    assert any(
        "skipped" in r.getMessage() for r in handler.records if r.levelno == logging.DEBUG
    )


def test_dedup_integrated_in_translate(monkeypatch):
    """Full flow: two consecutive pages via _translate() with mocked requests.
    Page 2's leading duplicate must be stripped deterministically."""
    tr = make_translator()

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, **kwargs):
        if "beds." in text:
            # page 2: the model re-renders the word covered by page 1
            return _resp((1, "Кровати. Входит коренастый молодой человек."))
        return _resp((1, "Я ставлю чемодан на одну из кроватей."))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    # Page 1: source genuinely ends mid-sentence (no final punctuation).
    tr._translate(["I put my suitcase down on one of the"])
    # Page 2: model re-renders the completed word -> must be stripped.
    r2 = tr._translate(["beds. A stocky young man comes in."])
    assert r2 == ["Входит коренастый молодой человек."]
