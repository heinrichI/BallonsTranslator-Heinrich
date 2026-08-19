r"""
Тесты пакетного JSON-id протокола TransGemmaTranslator:
- пачка — текст с id=N: префиксами;
- ответ — JSON-объект {"translations":[{id, translation}]} с проставленными id;
- сопоставление переводов с источниками по id;
- rolling context между пачками;
- эхо-ретрай в _translate_single.

Запуск:
    myenv\Scripts\python.exe -m pytest tests/test_transgemma_batch_formats.py -v
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.translators.trans_llm_api_transgemma import (
    TransGemmaTranslator,
    TranslationResponse,
    TranslationElement,
)

from utils import shared

shared.HEADLESS = True


def make_translator() -> TransGemmaTranslator:
    tr = TransGemmaTranslator(
        lang_source="English",
        lang_target="русский язык",
        raise_unsupported_lang=False,
    )
    tr.n_ctx = 6144  # чтобы _fetch_context_window возвращался сразу, без сети
    return tr


class FakeCompletion:
    def __init__(self, content: str):
        self.choices = [SimpleNamespace(text=content, message=None)]
        self.usage = SimpleNamespace(total_tokens=7)


class SequentialCompletions:
    """Возвращает заготовленные JSON-ответы по очереди (последний — повторно)."""

    def __init__(self, response_jsons):
        self.response_jsons = list(response_jsons)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.response_jsons) - 1)
        return FakeCompletion(self.response_jsons[idx])


def _resp(*pairs):
    """Собрать TranslationResponse из пар (id, translation)."""
    return TranslationResponse(
        translations=[TranslationElement(id=i, translation=t) for i, t in pairs]
    )


def make_mock(response_jsons):
    tr = make_translator()
    completions = SequentialCompletions(response_jsons)
    tr.client = SimpleNamespace(completions=completions, chat=None)
    tr._initialize_client = lambda api_key: True
    return tr, completions


# ---------- batch body / ordering ----------

def test_batch_text_has_ids():
    tr = make_translator()
    body = tr._batch_text(["Hello", "Goodbye"])
    assert body == "id=1: Hello\nid=2: Goodbye\n"


def test_ordered_translations_by_id():
    tr = make_translator()
    resp = _resp((2, "Пока"), (1, "Привет"))
    assert tr._ordered_translations(resp, 2) == ["Привет", "Пока"]


def test_ordered_translations_missing_id_yields_empty():
    tr = make_translator()
    resp = _resp((1, "Привет"))
    # Отсутствующий id не роняет маппинг — на его месте пустая строка.
    assert tr._ordered_translations(resp, 2) == ["Привет", ""]


def test_ordered_translations_count_mismatch_no_raise():
    tr = make_translator()
    resp = _resp((1, "x"), (2, "y"))
    # Вместо исключения возвращаем столько строк, сколько просили; лишние id игнорируются.
    assert tr._ordered_translations(resp, 3) == ["x", "y", ""]
def test_ordered_translations_count_mismatch_no_raise():
    tr = make_translator()
    resp = _resp((1, "x"), (2, "y"))
    # Вместо исключения возвращаем столько строк, сколько просили; лишние id игнорируются.
    assert tr._ordered_translations(resp, 3) == ["x", "y", ""]


# ---------- find_problems: ratio heuristics ----------

def test_find_problems_short_source_wordy_translation_not_flagged():
    """Регрессия на high-ratio false positive для коротких источников.

    'So,\nanyway...' (13 симв.) -> 'В общем, как бы то ни было...' (28 симв.)
    даёт ratio 2.23 > 2.0, но это легитимный перевод: короткие источники
    вообще не проходят ratio-проверку в _find_problems (guard len(src) > 25),
    как и в исправленном _translate_single. Раньше этот случай флагался через
    абсолютный порог MIN_ABS_LEN_FOR_HIGH_RATIO и вызывал лишние binary split'ы.
    """
    tr = make_translator()
    srcs = ["So,\nanyway...", "Okay."]
    result = ["В общем, как бы то ни было...", "Ладно."]
    assert tr._find_problems(srcs, result) == []


def test_find_problems_long_source_implausible_ratio_still_flagged():
    """Длинный источник с неадекватным отношением длин по-прежнему флагается."""
    tr = make_translator()
    src = "The quick brown fox jumps over the lazy dog near the river bank"  # 64 симв.
    hallucinated = "A" * 200  # ratio > 2.0 и длина перевода > 20 символов
    srcs = [src]
    result = [hallucinated]
    problems = tr._find_problems(srcs, result)
    assert problems == [0]


def test_find_problems_short_source_hallucinated_title_not_flagged():
    """Короткий источник + выдуманный длинный заголовок НЕ флагается батч-проверкой.

    Поведение согласовано с _translate_single: короткие источники обходят все
    ratio-проверки; единственная оставшаяся защита от такой галлюцинации —
    эхо-детекция (_is_echo), которая здесь неприменима (текст не совпадает).
    """
    tr = make_translator()
    assert tr._find_problems(["THE"], ["Очень длинный выдуманный заголовок истории"]) == []


# ---------- request parsing / prompting ----------

def test_request_translation_parses_json_response():
    tr, completions = make_mock(['{"translations":[{"id":1,"translation":"Привет"}]}'])
    resp = tr._request_translation("Hello")
    assert resp.translations[0].translation == "Привет"
    kwargs = completions.calls[0]
    assert "messages" not in kwargs
    assert "prompt" in kwargs
    assert kwargs["extra_body"]["json_schema"]["required"] == ["translations"]


def test_single_phrase_still_strips_newlines():
    tr, completions = make_mock(['{"translations":[{"id":1,"translation":"Привет мир"}]}'])
    tr._request_translation("Hello\nWorld")
    prompt = completions.calls[0]["prompt"]
    assert "Hello World" in prompt


def test_request_translation_cleans_alternatives():
    tr, _ = make_mock(['{"translations":[{"id":1,"translation":"В ТЕННИС ПОИГРАЕМ? / КТО ЗА ТЕННИС?"}]}'])
    resp = tr._request_translation("TENNIS, ANYONE?")
    assert resp.translations[0].translation == "В ТЕННИС ПОИГРАЕМ?"


def test_request_translation_preserves_slash_credits():
    src = "F. Doyle / D. DeCarlo / R. Lapick / V. DeCarlo"
    out = "Ф. Дойл / Д. ДеКарло / Р. Лапик / В. ДеКарло"
    tr, _ = make_mock([json.dumps({"translations": [{"id": 1, "translation": out}]}, ensure_ascii=False)])
    resp = tr._request_translation(src, srcs=[src])
    assert resp.translations[0].translation == out


# ---------- batch translation ----------

# Plain-text ответы для одиночных фраз, приходящих через _request_single
# (structured_output=False после бинарного сплита до len==1).
SINGLE_TEXT_MAP = {"Hello": "Привет", "Bye": "Пока"}


def _single_call(text):
    """Стандартная ветка мока для одиночного запроса (plain-text путь)."""
    return _resp((1, SINGLE_TEXT_MAP.get(text, "?")))


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


def test_translate_batch_splits_on_empty(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        if not structured_output:  # plain-text путь одиночной фразы
            return _single_call(text)
        return _resp((1, "Привет"), (2, ""))  # пустой перевод -> проблема

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_mismatch(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        if not structured_output:
            return _single_call(text)
        return _resp((1, "Привет"))  # id=2 отсутствует -> позиция 2 пустая

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_splits_on_exception(monkeypatch):
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        if not structured_output:
            return _single_call(text)
        raise ValueError("boom")

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""] * 2
    tr._translate_batch(["Hello", "Bye"], [0, 1], translations)
    assert len(calls) == 3
    assert translations == ["Привет", "Пока"]


def test_translate_batch_single_element_skips_json_batch_path(monkeypatch):
    """Батч из одного элемента НЕ должен идти через id=N:/json_schema — сразу в plain-text single-путь.

    Регрессия на llama.cpp sentinel -1000000000000000.0: грамматика json_schema
    заходила в тупик на 1-элементных батчах.
    """
    tr = make_translator()
    batch_calls = []
    single_calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        batch_calls.append(text)
        return _resp((1, "НЕ ДОЛЖНО БЫТЬ ВЫЗВАНО"))

    def fake_single(src, idx, translations_list):
        single_calls.append((src, idx))
        translations_list[idx] = f"single:{src}"

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    monkeypatch.setattr(tr, "_translate_single", fake_single)

    translations = [""] * 8   # orig_indices указывают на позиции 0..7
    tr._translate_batch(["Hello"], [7], translations)

    assert batch_calls == []          # JSON-путь не задействован
    assert single_calls == [("Hello", 7)]
    assert translations[7] == "single:Hello"
    assert all(t == "" for t in translations[:7])


# ---------- echo retry ----------

def test_translate_single_echo_retry_uses_second_response(monkeypatch):
    src = "The quick brown fox jumps over the lazy dog"
    tr = make_translator()
    calls = []

    def fake_request(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        calls.append(text)
        if len(calls) == 1:
            return _resp((1, src))          # echo — identical to source
        return _resp((1, "Быстрая бурая лиса прыгает через ленивого пса"))

    monkeypatch.setattr(tr, "_request_translation", fake_request)
    translations = [""]
    tr._translate_single(src, 0, translations)
    assert len(calls) == 2
    assert translations[0] == "Быстрая бурая лиса прыгает через ленивого пса"


def test_translate_single_persistent_echo_keeps_source_gracefully(monkeypatch):
    echoed = "the quick brown fox jumps over the lazy dog"
    src = echoed.capitalize()
    tr = make_translator()

    def fake_send(text, show_dialog=True, srcs=None, preserve_newlines=False, structured_output=True):
        return _resp((1, echoed))  # always echoes

    monkeypatch.setattr(tr, "_request_translation", fake_send)
    translations = [""]
    tr._translate_single(src, 0, translations)
    # Модель так и не перестала повторять исходник — оставляем его как запасной вариант.
    assert translations[0].strip().lower() == echoed.lower()


def test_temperature_defaults_to_greedy():
    tr = make_translator()
    assert float(tr.temperature) == 0.0