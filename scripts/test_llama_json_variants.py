"""Эмпирический тест вариантов передачи JSON-схемы в /v1/completions
живого llama-server на 127.0.0.1:1234.

Проверяет, какая форма параметра "json_schema" реально включает принудительную
грамматику вывода у llama.cpp:
    A) {"json_schema": {"schema": S}}  — обёртка (НЕ работает: сервер молча
       игнорирует схему, модель декодирует свободно -> мусор / sentinel -1e15)
    B) {"json_schema": S}              — схема напрямую (правильная форма,
       грамматика применяется строго)
    C) response_format json_object+schema — без грамматики (id строками,
       markdown-фенсы)
    D) вообще без схемы                — базовая линия свободного вывода

Запуск:
    myenv\\Scripts\\python.exe scripts/test_llama_json_variants.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

# Инлайновая схема переводов (без $ref/$defs — конвертер json_schema llama.cpp
# не умеет разрешать pydantic-ссылки "#/$defs/...").
S = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "translation": {"type": "string"},
                },
                "required": ["id", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translations"],
    "additionalProperties": False,
}

URL = "http://127.0.0.1:1234/v1/completions"

# Промпт в разметке Gemma3 (как строит его TransGemmaTranslator):
# документ из двух строк с префиксами id=N:, просьба вернуть JSON с "translations".
prompt = (
    "<start_of_turn>user\n"
    "source_lang_code: en\n"
    "target_lang_code: ru\n"
    "You are a professional English to Russian translator.\n"
    "The document has 2 lines; each line (starting with its id prefix) is a separate phrase.\n"
    "Output ONLY a JSON object with key \"translations\": an array of exactly 2 objects,\n"
    "each with \"id\" and \"translation\" (Russian).\n"
    "Document:\nid=1: Hello!\nid=2: Goodbye.\n"
    "<end_of_turn>\n"
    "<start_of_turn>model"
)


def try_variant(name, body):
    """Отправить один вариант тела запроса и напечатать, вернул ли сервер
    валидный JSON-объект или нет (вместе с сырым текстом для диагностики)."""
    try:
        r = httpx.post(URL, json={**body, "prompt": prompt, "max_tokens": 300,
                                  "temperature": 0.0}, timeout=60)
        data = r.json()
        txt = data.get("choices", [{}])[0].get("text", "")
        ok = "?"
        try:
            obj = json.loads(txt)
            # Валиден только JSON-объект; число -1000000000000000.0 тоже
            # распарсится как float — это sentinel llama.cpp, а не ответ.
            ok = "VALID-JSON" if isinstance(obj, dict) else f"non-dict {type(obj).__name__}"
        except Exception:
            start = txt.find("{")
            end = txt.rfind("}")
            ok = f"parse-FAIL ({'balanced' if start != -1 else 'no brace'})"
        print(f"--- {name}: HTTP {r.status_code}, {ok}")
        print(f"    raw: {txt[:180]!r}")
    except Exception as e:
        print(f"--- {name}: REQUEST FAIL: {e}")


base = {"model": "translategemma-27b-it"}

# A — прежняя (ошибочная) форма модуля: схема под ключом "schema".
# Сервер НЕ ругается, но грамматика не включается.
try_variant("A current  json_schema={'schema':S}", {**base, "json_schema": {"schema": S}})
# B — правильная форма: схема как ПРЯМОЕ значение "json_schema".
try_variant("B direct   json_schema=S",           {**base, "json_schema": S})
# C — OpenAI-совместимый response_format со схемой внутри (грамматики нет).
try_variant("C response_format json_object+schema", {
    **base,
    "response_format": {"type": "json_object", "schema": S},
})
# D — свободный вывод без схемы (базовая линия для сравнения с C).
try_variant("D no schema at all (baseline free-form)", base)
