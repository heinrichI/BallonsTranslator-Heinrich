import re
import time
import json
import math
import difflib
import traceback
from typing import List, Dict, Optional, Type, Tuple, Generator

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from .base import BaseTranslator, register_translator

from utils.message import create_error_dialog, create_yes_no_dialog

MAX_LEN_APPROX = 36000

# Stop the whole translation run after this many consecutive connection errors.
# The counter resets on the first successful request, so rare transient failures
# do not abort the session.
MAX_CONSECUTIVE_CONNECTION_ERRORS = 3

# Token-budget constants for whole-first batching (see _pack_batches).
PROMPT_OVERHEAD = 150          # tokens for the _build_llama_prompt template
BATCH_SAFETY_FACTOR = 0.9      # 10% safety margin when packing
OUTPUT_PER_ELEMENT = 15        # tokens for the {"id":N,"translation":"..."} wrapper
OUTPUT_GROWTH_FACTOR = 1.3     # translation length growth factor
MIN_BUDGET = 256               # lower bound for the token budget
HIGH_RATIO_THRESHOLD = 2.0     # translation/source length ratio considered suspicious
MIN_ABS_LEN_FOR_HIGH_RATIO = 20  # absolute floor on translation length (secondary condition; ratio checks only run for sources > 25 chars)
ECHO_SIMILARITY = 0.90         # normalized similarity treated as an echo (source copied as translation)
ECHO_MIN_LEN = 16              # minimum normalized length before the similarity comparison applies

class InvalidNumTranslations(Exception):
    """Exception raised when the number of translations does not match the number of sources."""
    pass

class TranslationIntegrityError(Exception):
    """Exception raised when a translation fragment is suspiciously short or empty."""
    pass

class TranslationAbortedError(Exception):
    """Raised when the server is unreachable too many times in a row.

    This exception is deliberately NOT swallowed by the retry/fallback logic in
    _translate_single / _translate_batch. It propagates all the way up to the
    pipeline loop, which stops the whole translation run (all pages).
    """
    pass

class TranslationElement(BaseModel):
    id: int = Field(..., description="The original numeric ID of the text snippet.")
    translation: str = Field(..., description="The translated text corresponding to the id.")

class TranslationResponse(BaseModel):
    translations: List[TranslationElement] = Field(..., description="A list of all translated elements.")

# Full English language names used in the raw prompt for llama-server (code -> name).
# TranslateGemma was trained on this wording; the code is used as a fallback name.
_LANG_NAMES = {
    'en': 'English', 'ru': 'Russian', 'zh': 'Chinese', 'ja': 'Japanese', 'ko': 'Korean',
    'vi': 'Vietnamese', 'cs': 'Czech', 'nl': 'Dutch', 'fr': 'French', 'de': 'German',
    'hu': 'Hungarian', 'it': 'Italian', 'pl': 'Polish', 'pt': 'Portuguese', 'ro': 'Romanian',
    'es': 'Spanish', 'tr': 'Turkish', 'ar': 'Arabic', 'ml': 'Malayalam', 'ta': 'Tamil', 'hi': 'Hindi',
}


def _normalize_translation_payload(data):
    """Convert the native single-object output {"id","speaker","dialogue"} to the wrapper format."""
    if isinstance(data, dict) and 'dialogue' in data and 'translations' not in data:
        return {"translations": [{"id": data.get('id', 1), "translation": data['dialogue']}]}
    return data


def _extract_json_object(raw: str) -> Optional[str]:
    """Extract the outermost balanced JSON object {...} from a raw model response.

    Handles markdown fences and ignores braces inside quoted strings. Returns
    the JSON substring, or None when no valid object is present.
    """
    text = raw.strip()
    # Strip a markdown code fence if present.
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None

# Inline JSON schema for llama-server (no $ref/$defs): llama.cpp's json_schema
# converter cannot resolve pydantic's "#/$defs/..." references.
#
# КОРЕНЬ ПРОБЛЕМЫ (найден live-экспериментом против llama-server, см.
# scripts/test_llama_json_variants.py):
#
#   llama.cpp ждёт схему как ПРЯМОЕ значение топ-уровневого параметра тела
#   запроса "json_schema". Раньше схема передавалась завёрнутой:
#
#       {"json_schema": {"schema": _LLAMA_JSON_SCHEMA}}   # НЕПРАВИЛЬНО
#
#   Сервер при такой форме МОЛЧА ИГНОРИРУЕТ грамматику: никакой ошибки не
#   возвращается, но модель декодирует свободно. Симптомы были такие:
#     * обрезанный не-JSON в ответе, например:  "translations: [ { "
#     * sentinel-число от llama.cpp:  -1000000000000000.0
#     * парсинг падал -> батч бинарил на одиночные фразы -> fallback на исходник
#
#   Правильная форма (используется сейчас):
#
#       {"json_schema": _LLAMA_JSON_SCHEMA}               # ПРАВИЛЬНО
#
#   При ней сервер жёстко ограничивает вывод грамматикой и всегда возвращает
#   валидный {"translations":[{"id":N,"translation":"..."}]}.
#
# Отдельные запросы одной фразы (structured_output=False) вообще не используют
# json_schema — модель TransGemma надёжнее отвечает обычным текстом; принуждение
# к JSON-грамматике на коротком промпте давало тот же sentinel -1e15.
_LLAMA_JSON_SCHEMA = {
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


@register_translator("TransGemma")
class TransGemmaTranslator(BaseTranslator):
    concate_text = False
    cht_require_convert = True
    params: Dict = {
        "provider": {
            "type": "selector",
            "options": ["llama-server", "LM Studio"],
            "value": "llama-server",
            "description": "Select the backend provider for TranslateGemma.",
        },
        "endpoint": {
            "value": "",
            "description": "Base URL for the API. Leave empty for provider default.",
        },
            # "value": "Please help me to translate the following text from a manga to {to_lang} (if it's already in {to_lang} or looks like gibberish you have to output it as it is instead):\n",
            # "value": "Please help me to translate the following text from a comics to {to_lang}. If the input text is presented in segments, each marked with <|NUMBER|>, then your output MUST strictly follow this format: <|1|>TRANSLATION_FOR_SEGMENT_1<|2|>TRANSLATION_FOR_SEGMENT_2<|3|>... and so on for all segments.\nDo NOT add any other numbering (like \"1.\", \"2.\") or introductory/concluding text.\nPreserve newlines within a single translation if they were present in the original segment's meaning.",
            #"value": "Please help me to translate the following text from a comics to {to_lang}. If the input text is presented in segments, each marked with <|NUMBER|>, then your output MUST strictly follow this format: <|1|>TRANSLATION_FOR_SEGMENT_1<|2|>TRANSLATION_FOR_SEGMENT_2<|3|>... and so on for all segments.\nDo NOT add any other numbering (like \"1.\", \"2.\") or introductory/concluding text.",
        "invalid repeat count": {
            "value": 2,
            "description": "Number of retries if the count of translations mismatches the source count.",
        },
        "max tokens": {
            "value": 4096,
            "description": "Maximum tokens for the response.",
        },
        "temperature": {
            "value": 0.0,
            "description": "Sampling temperature. Google recommends greedy decoding (0.0) for TranslateGemma.",
        },
        "top p": {
            "value": 1.0,
            "description": "Top P for sampling.",
        },
        "context": {
            "value": "",
            "description": "Дополнительный контекст/стиль, например: юмористический подростковый комикс. Вставляется в промпт (только llama-server). Оставьте пустым, если не нужен.",
        },
        "retry attempts": {
            "value": 1,
            "description": "Number of retry attempts on API connection or parsing failures.",
        },
        "retry timeout": {
            "value": 15,
            "description": "Timeout between retry attempts (seconds).",
        },
        "frequency penalty": {"value": 0.0, "description": "Frequency penalty (OpenAI)."},
        "presence penalty": {"value": 0.0, "description": "Presence penalty (OpenAI)."},
        'low vram mode': {
            'value': True,
            'description': 'check it if you\'re running it locally on a single device and encountered a crash due to vram OOM',
            'type': 'checkbox',
        }
    }

    def _setup_translator(self):
        self.lang_map['简体中文'] = 'zh'
        self.lang_map['日本語'] = 'ja'
        self.lang_map['English'] = 'en'
        self.lang_map['한국어'] = 'ko'
        self.lang_map['Tiếng Việt'] = 'vi'
        self.lang_map['čeština'] = 'cs'
        self.lang_map['Nederlands'] = 'nl'
        self.lang_map['Français'] = 'fr'
        self.lang_map['Deutsch'] = 'de'
        self.lang_map['magyar nyelv'] = 'hu'
        self.lang_map['Italiano'] = 'it'
        self.lang_map['Polski'] = 'pl'
        self.lang_map['Português'] = 'pt'
        self.lang_map['limba română'] = 'ro'
        self.lang_map['русский язык'] = 'ru'
        self.lang_map['Español'] = 'es'
        self.lang_map['Türk dili'] = 'tr'
        self.lang_map['Arabic'] = 'ar'
        self.lang_map['Malayalam'] = 'ml'
        self.lang_map['Tamil'] = 'ta'
        self.lang_map['Hindi'] = 'hi'
        self.token_count = 0
        self.token_count_last = 0
        self.current_key_index = 0
        self.last_request_time = 0
        self.request_count_minute = 0
        self.minute_start_time = time.time()
        self.key_usage = {}
        self.client = None
        self.n_ctx = None
        self.connection_error_count = 0
        # Tail of previously translated lines shown to the next batch as context.
        # Deliberately NOT reset between pages: it persists across _translate()
        # calls so a sentence spanning a page break stays continuous.
        self.rolling_context = ""
        # Source-language counterpart: last source lines of the previous
        # batch/page, used together with rolling_context for continuation.
        self.rolling_source_tail = ""

    def _initialize_client(self, api_key_to_use: str) -> bool:
        endpoint = self.endpoint
        provider = self.provider
        if not endpoint:
            if provider == "LM Studio":
                endpoint = "http://localhost:1234/v1"
            else:  # llama-server
                endpoint = "http://127.0.0.1:1234/v1"

        http_client = httpx.Client()
        self.logger.debug(f"Initializing client for {provider} at endpoint {endpoint}")

        try:
            self.client = OpenAI(api_key=api_key_to_use, base_url=endpoint, http_client=http_client)
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {e}")
            self.client = None
            return False

    def _record_connection_error(self, e: Exception) -> None:
        """Count a connection failure and abort the whole run after the threshold.

        The counter is reset on the first successful request, so a flaky server
        that recovers does not abort the session. Once the threshold is exceeded,
        a TranslationAbortedError is raised and propagates up to the pipeline loop,
        stopping the translation of all remaining pages.
        """
        self.connection_error_count += 1
        self.logger.warning(
            f"Connection error {self.connection_error_count}/{MAX_CONSECUTIVE_CONNECTION_ERRORS}: {e}"
        )
        if self.connection_error_count > MAX_CONSECUTIVE_CONNECTION_ERRORS:
            raise TranslationAbortedError(
                f"Server unreachable after {self.connection_error_count} consecutive connection errors. "
                f"Stopping the whole translation run."
            ) from e

    @staticmethod
    def _is_connection_error(e: Exception) -> bool:
        """True when the exception indicates a connection/transport failure.

        Only these count toward the consecutive-error threshold that aborts the
        whole translation run. Server-side API failures (HTTP 4xx/5xx) are NOT
        treated as connection errors and keep the normal retry/fallback behavior.
        """
        if isinstance(e, (ConnectionError, httpx.TransportError)):
            return True
        try:
            import openai
            if isinstance(e, openai.APIConnectionError):
                return True
        except (ImportError, AttributeError):
            pass
        return False

    def _reset_connection_errors(self) -> None:
        """Reset the consecutive connection-error counter after a successful request."""
        if self.connection_error_count:
            self.logger.info(f"Connection error counter reset (was {self.connection_error_count}).")
        self.connection_error_count = 0

    def _fetch_context_window(self) -> None:
        """Fetch the server's context window (n_ctx) once and cache it in self.n_ctx.

        llama-server exposes it at GET {root}/props -> default_generation_settings.n_ctx.
        LM Studio exposes it at GET {root}/models -> model metadata context_length.
        Falls back to a provider-specific default on any error.
        """
        if self.n_ctx is not None:
            return
        provider = self.provider
        endpoint = self.endpoint
        if not endpoint:
            endpoint = "http://127.0.0.1:1234/v1" if provider == "llama-server" else "http://localhost:1234/v1"
        root = endpoint.rstrip('/')
        if root.endswith('/v1'):
            root = root[:-3]

        try:
            if provider == "llama-server":
                resp = httpx.get(f"{root}/props", timeout=5)
                resp.raise_for_status()
                data = resp.json()
                n_ctx = data.get("default_generation_settings", {}).get("n_ctx")
                if n_ctx:
                    self.n_ctx = int(n_ctx)
                    self.logger.info(f"Fetched n_ctx={self.n_ctx} from llama-server /props")
                    return
            else:  # LM Studio
                resp = httpx.get(f"{root}/models", timeout=5)
                resp.raise_for_status()
                data = resp.json()
                models = data.get("data", []) if isinstance(data, dict) else []
                for m in models:
                    meta = m.get("meta", {}) if isinstance(m, dict) else {}
                    ctx = meta.get("context_length") or m.get("context_length")
                    if ctx:
                        self.n_ctx = int(ctx)
                        self.logger.info(f"Fetched n_ctx={self.n_ctx} from LM Studio /models")
                        return
        except Exception as e:
            self.logger.warning(f"Failed to fetch context window: {e}")

        self.n_ctx = 6144 if provider == "llama-server" else 4096
        self.logger.warning(f"Using fallback n_ctx={self.n_ctx} for provider {provider}")

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: CJK chars ~1 token each, other chars ~4 per token."""
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff' or '\uac00' <= ch <= '\ud7af')
        return cjk + math.ceil((len(text) - cjk) / 4)

    def _batch_text(self, srcs: List[str]) -> str:
        """Build the prompt body with id=N: prefixes (renumbered from 1 within the batch)."""
        return "\n".join(f"id={i + 1}: {s.replace(chr(10), ' ')}" for i, s in enumerate(srcs)) + "\n"

    def _ordered_translations(self, parsed: TranslationResponse, num_src: int) -> List[str]:
        """Order translations by id; missing ids become empty strings."""
        d = {item.id: item.translation for item in parsed.translations}
        return [d.get(i, "") for i in range(1, num_src + 1)]

    def _normalize_for_echo(self, s: str) -> str:
        """Normalize text for echo comparison: drop soft hyphens, collapse
        whitespace, lowercase. Returns the normalized string."""
        s = s.replace('\u00AD', '')
        s = ' '.join(s.split())
        return s.lower()

    def _is_echo(self, src: str, tr: str) -> bool:
        """Detect the model echoing the source as the 'translation'.

        An exact normalized match is always an echo. A near match (difflib
        ratio >= ECHO_SIMILARITY) also counts, but only for strings of at
        least ECHO_MIN_LEN normalized characters, to avoid false positives
        on short, legitimately identical words (brand names, credits, ...).
        """
        n_src = self._normalize_for_echo(src)
        n_tr = self._normalize_for_echo(tr)
        if not n_src or not n_tr:
            return False
        if n_src == n_tr:
            return True
        if min(len(n_src), len(n_tr)) >= ECHO_MIN_LEN:
            return difflib.SequenceMatcher(None, n_src, n_tr).ratio() >= ECHO_SIMILARITY
        return False

    def _find_problems(self, srcs: List[str], result: List[str]) -> List[int]:
        """Return indices of phrases whose translation is suspicious.

        A problem is: empty translation for a non-empty source, an echoed
        source (translation identical or nearly identical to the source вЂ”
        the model copied it instead of translating), or a compression ratio
        outside [0.40, 2.0] for sources longer than 25 chars (short phrases
        skip the ratio check).
        """
        problems = []
        for i, (src, tr) in enumerate(zip(srcs, result)):
            if not tr.strip() and src.strip():
                self.logger.debug(f"find_problems: idx={i} flagged (empty translation): {tr!r}")
                problems.append(i)
                continue
            if self._has_id_prefix_leak(tr):
                # Model echoed the request's id=N: prefix — flagged for all
                # providers so the batch binary-splits down to single elements.
                self.logger.debug(f"find_problems: idx={i} flagged (id-prefix-leak): {tr!r}")
                problems.append(i)
                continue
            if self.provider != "llama-server" and self._has_id_leak(tr):
                self.logger.debug(f"find_problems: idx={i} flagged (id-leak): {tr!r}")
            if self._is_echo(src, tr):
                # Model returned the source text as the translation (ratio ~= 1.0
                # passes the ratio checks) вЂ” flag it so the batch binary-splits
                # down to a per-phrase re-request.
                self.logger.debug(f"find_problems: idx={i} flagged (echo/identity): {tr!r}")
                problems.append(i)
                continue
            if len(src) > 25:
                ratio = len(tr) / len(src)
                if ratio < 0.40:
                    self.logger.debug(f"find_problems: idx={i} flagged (low-ratio {ratio:.2f}): {tr!r}")
                    problems.append(i)
                    continue
                # High-ratio check shares the SAME len(src) > 25 guard as the
                # low-ratio branch above (and mirrors _translate_single).
                # Short sources are never ratio-flagged here: a legitimately
                # wordy translation of e.g. "So,\nanyway..." ("В общем, как бы
                # то ни было...", ratio 2.23) previously triggered this branch
                # via the absolute-length floor in _is_high_ratio_problem,
                # causing pointless binary splits down to per-phrase retries.
                if self._is_high_ratio_problem(src, tr):
                    self.logger.debug(f"find_problems: idx={i} flagged (high-ratio): {tr!r}")
                    problems.append(i)
        return problems

    # --- Property getters ---
    @property
    def provider(self) -> str: return self.get_param_value("provider")
    @property
    def endpoint(self) -> Optional[str]: return self.get_param_value("endpoint") or None
    @property
    def temperature(self) -> float: return float(self.get_param_value("temperature"))
    @property
    def top_p(self) -> float: return float(self.get_param_value("top p"))
    @property
    def context(self) -> str: return str(self.get_param_value("context"))
    @property
    def max_tokens(self) -> int: return int(self.get_param_value("max tokens"))
    @property
    def retry_attempts(self) -> int: return int(self.get_param_value("retry attempts"))
    @property
    def retry_timeout(self) -> int: return int(self.get_param_value("retry timeout"))
    @property
    def invalid_repeat_count(self) -> int: return int(self.get_param_value("invalid repeat count"))
    @property
    def frequency_penalty(self) -> float: return float(self.get_param_value("frequency penalty"))
    @property
    def presence_penalty(self) -> float: return float(self.get_param_value("presence penalty"))
    @property
    def global_delay(self) -> float: return float(self.get_param_value("delay"))

    def _pack_batches(self, queries: List[str]) -> Generator[Tuple[str, int, List[int]], None, None]:
        """Greedily pack phrases into token-budgeted batches (whole-first).

        Yields (text, num_src, batch_orig_idx) where text has id=N: prefixes
        renumbered from 1 within the batch. The whole list is sent as one batch
        when it fits the budget; otherwise it is split into token-aware batches.
        """
        self._fetch_context_window()
        budget = max(MIN_BUDGET, self.n_ctx - self.max_tokens - PROMPT_OVERHEAD)
        limit = budget * BATCH_SAFETY_FACTOR

        current_prompt = ""
        current_indices: List[int] = []
        current_prompt_tokens = 0
        current_output_tokens = 0

        def _flush():
            nonlocal current_prompt, current_indices, current_prompt_tokens, current_output_tokens
            if current_indices:
                yield current_prompt, len(current_indices), list(current_indices)
                current_prompt = ""
                current_indices = []
                current_prompt_tokens = 0
                current_output_tokens = 0

        for i, query in enumerate(queries):
            clean = query.replace('\n', ' ')
            element = f"id={len(current_indices) + 1}: {clean}\n"
            prompt_tokens = self._estimate_tokens(element)
            output_tokens = int(self._estimate_tokens(clean) * OUTPUT_GROWTH_FACTOR) + OUTPUT_PER_ELEMENT

            # Absolute character safety limit (MAX_LEN_APPROX) still applies.
            if current_indices and (
                len(current_prompt) + len(element) > MAX_LEN_APPROX
                or current_prompt_tokens + prompt_tokens + current_output_tokens + output_tokens > limit
            ):
                self.logger.debug(
                    f"Packing split: prompt_tokens={current_prompt_tokens + prompt_tokens}, "
                    f"output_tokens={current_output_tokens + output_tokens}, budget={budget}"
                )
                yield from _flush()

            current_prompt += element
            current_indices.append(i)
            current_prompt_tokens += prompt_tokens
            current_output_tokens += output_tokens

        yield from _flush()

    def _build_llama_prompt(self, text: str, from_lang: str, to_lang: str, structured_output: bool = True) -> str:
        """Build the raw prompt for /v1/completions (Gemma3 turn markup, no chat template).

        When `structured_output` is True (batches), ask for the
        {"translations":[{id, translation}]} JSON object the caller validates.
        When False (single phrase), ask for plain text — so a lone phrase is not
        stuffed through the JSON grammar.
        """
        from_name = _LANG_NAMES.get(from_lang.split('_')[0].split('-')[0], from_lang)
        to_name = _LANG_NAMES.get(to_lang.split('_')[0].split('-')[0], to_lang)
        context = self.context.strip()
        context_line = f"Context: {context}.\n" if context else ""
        # Cross-page / cross-batch continuity: the tail of the previously
        # translated document (its source lines plus their translation) is
        # passed to the prompt so a sentence split across a page boundary is
        # rendered as one seamless continuation instead of two standalone
        # fragments (e.g. "...on one of the" / "beds." -> "...на одну из
        # кроватей", not "...на одну из них." + "Кровати.").
        prev_src = getattr(self, "rolling_source_tail", "").strip()
        prev_tr = getattr(self, "rolling_context", "").strip()
        prev_parts = []
        if prev_src:
            prev_parts.append(
                f"End of the previously translated document (last {from_name} lines):\n{prev_src}\n"
            )
        if prev_tr:
            prev_parts.append(f"Their existing {to_name} translation:\n{prev_tr}\n")
        if prev_parts:
            prev_parts.append(
                "The current document continues immediately after it. Use the above "
                "ONLY as reference for style and terminology consistency - do NOT "
                "re-translate it. The current document may begin mid-sentence, and "
                "the previous translation may ALREADY cover its first word(s). "
                "Compare the beginning of the current document with the previous "
                "translation: if the leading words are already expressed there, "
                "SKIP them and translate only the new content; otherwise start "
                "with their translation to complete the interrupted sentence. "
                "The previous translation and your output, read one after "
                "another, must form one continuous text without repeated words "
                "or duplicated fragments. Keep gender, number and case consistent."
            )
            prev_line = "\n".join(prev_parts) + "\n"
        else:
            prev_line = ""
        num_lines = len([ln for ln in text.split("\n") if ln.strip()])
        if structured_output:
            output_instruction = (
                f"The document has {num_lines} lines; each line (starting with its id prefix, e.g. 'id=1: ') is a separate phrase. "
                "Output ONLY a JSON object with a single key \"translations\": an array of "
                f"exactly {num_lines} objects, each with \"id\" (the line's number/its id=N prefix) "
                f"and \"translation\" (the {to_name} translation of that line). "
                "Do not merge, split, renumber, or add any lines. Keep each translation as one "
                "string in its own \"translation\" field, even if the phrase is long. "
                "Do not add explanations or alternatives.\n"
            )
        else:
            output_instruction = (
                f"The document has {num_lines} lines. Translate the whole document into {to_name}. "
                "Output ONLY the translation as plain text, exactly one line per source phrase, "
                "in the same order, without any numbering, explanations or alternatives.\n"
            )
        prompt = (
            "<start_of_turn>user\n"
            f"source_lang_code: {from_lang}\n"
            f"target_lang_code: {to_lang}\n"
            f"You are a professional {from_name} to {to_name} translator. "
            f"Translate the following {from_name} document into {to_name}, "
            f"accurately conveying meaning and nuance while adhering to {to_name} grammar, vocabulary, and cultural sensitivities.\n"
            f"{output_instruction}"
            f"{context_line}"
            f"{prev_line}"
            f"Document:\n{text}"
            "<end_of_turn>\n"
            "<start_of_turn>model"
        )
        return prompt

    def _request_translation(self, text: str, show_dialog: bool = True, srcs: Optional[List[str]] = None, preserve_newlines: bool = False, structured_output: bool = True) -> Optional[TranslationResponse]:
        """Send one request and return the validated TranslationResponse.

        `preserve_newlines=True` for batch bodies (newlines separate elements).
        `structured_output` only affects llama-server: False (single phrase)
        sends plain text with no json_object grammar; True (batches) pins the
        {"translations":[...]} schema.
        """
        current_api_key = "lm-studio"
        # Only flatten newlines for single-phrase requests. Batch bodies built by
        # _batch_text() rely on newlines to separate lines.
        if not preserve_newlines:
            text = text.replace("\n", " ")

        # Positional source list so _single_alternative can tell apart
        # model-provided alternatives ("A / B") from a faithful slash-separated
        # list in the source (e.g. credits "F. Doyle / D. DeCarlo / ...").
        if not srcs:
            srcs = [text]

        if not self._initialize_client(current_api_key):
            client_error = ConnectionError("Failed to initialize API client.")
            self._record_connection_error(client_error)
            raise client_error

        self._fetch_context_window()

        model_name = 'translategemma-27b-it'

        from_lang = self.lang_map.get(self.lang_source, self.lang_source)
        to_lang = self.lang_map.get(self.lang_target, self.lang_target)

        provider = self.provider
        raw_content = None
        completion = None
        if provider == "LM Studio":
            # LM Studio uses <|source_lang|> delimiter format with custom Jinja template
            prompt = (
                f"<|source_lang|>{from_lang}<|target_lang|>{to_lang}\n"
                f"{text}"
            )
            messages = [
                {"role": "user", "content": prompt},
            ]
            api_args = {
                "model": model_name,
                "messages": messages,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_tokens": self.max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "schema": TranslationResponse.model_json_schema()
                    },
                },
            }
            self.logger.debug("Using 'json_schema' mode for LM Studio.")
            try:
                completion = self.client.chat.completions.create(**api_args)
            except Exception as e:
                self.logger.error(f"API request failed: {e}")
                if self._is_connection_error(e):
                    self._record_connection_error(e)
                if show_dialog:
                    create_error_dialog(e, 'Translation failed.')
                raise
            self._reset_connection_errors()

            if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                raw_content = completion.choices[0].message.content
        else:
            # llama-server: raw /v1/completions with a self-built prompt (no chat template).
            # For batches (structured_output=True) the top-level json_schema pins the
            # {"translations":[...]} grammar. For a single phrase (False) no json_object
            # is requested — the bare text is enough and far more reliable with this model.
            prompt = self._build_llama_prompt(text, from_lang, to_lang, structured_output=structured_output)
            api_args = {
                "model": model_name,
                "prompt": prompt,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_tokens": self.max_tokens,
            }
            if structured_output:
                # llama.cpp expects the schema DIRECTLY as the value of the
                # top-level "json_schema" body parameter. Wrapping it as
                # {"schema": ...} makes the server silently IGNORE the grammar
                # (verified live: output degenerates to garbage / sentinel
                # -1000000000000000.0), while the unwrapped form enforces it.
                api_args["extra_body"] = {
                    "json_schema": _LLAMA_JSON_SCHEMA,
                }
                self.logger.debug("Using raw '/v1/completions' with top-level json_schema for llama-server.")
            else:
                self.logger.debug("Using raw '/v1/completions' in plain-text mode for llama-server.")
            try:
                completion = self.client.completions.create(**api_args)
            except Exception as e:
                self.logger.error(f"API request failed: {e}")
                if self._is_connection_error(e):
                    self._record_connection_error(e)
                if show_dialog:
                    create_error_dialog(e, 'Translation failed.')
                raise
            self._reset_connection_errors()

            if completion.choices and completion.choices[0].text:
                raw_content = completion.choices[0].text

        if raw_content is None:
            self.logger.warning("No valid message content in API response.")
            return None

        if not structured_output:
            # Plain-text single phrase: the model returns the translation as bare
            # text (possibly wrapped/echoed with 'id=1:' or extra whitespace). Wrap
            # it in a one-element response for the existing downstream handling.
            validated_response = TranslationResponse(
                translations=[
                    TranslationElement(id=1, translation=raw_content.strip())
                ]
            )
        else:
            try:
                # The model may wrap the object in a JSON string (escaped braces, no
                # literal '{'), so try parsing the raw content directly first.
                data_to_validate = json.loads(raw_content)
                if isinstance(data_to_validate, str):
                    data_to_validate = json.loads(data_to_validate)
            except (json.JSONDecodeError, ValueError):
                # Fall back to extracting a balanced {...} object from surrounding text.
                json_to_parse = _extract_json_object(raw_content)
                if json_to_parse is None:
                    self.logger.error(f"No JSON object found in API response: {raw_content[:200]!r}")
                    if show_dialog:
                        create_error_dialog(ValueError("No JSON object found in API response."), 'Translation failed.')
                    raise ValueError("No JSON object found in API response.")
                data_to_validate = json.loads(json_to_parse)

            try:
                if not isinstance(data_to_validate, dict):
                    raise ValueError(f"Expected a JSON object, got {type(data_to_validate).__name__}: {data_to_validate!r}")
                data_to_validate = _normalize_translation_payload(data_to_validate)
                validated_response = TranslationResponse.model_validate(data_to_validate)
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                self.logger.error(f"Pydantic validation or JSON parsing failed: {e}")
                self.logger.debug(f"Raw JSON content from API: {raw_content}")
                if show_dialog:
                    create_error_dialog(e, 'Translation failed.')
                raise

        # Map batch ids (1..len(srcs)) to their source strings so _single_alternative
        # can tell real "A / B" credits from model-provided alternative variants.
        src_by_id = {i + 1: s for i, s in enumerate(srcs)}
        for item in validated_response.translations:
            item.translation = self._single_alternative(item.translation, src_by_id.get(item.id, ""))

        if hasattr(completion, 'usage') and completion.usage:
            self.token_count += completion.usage.total_tokens
            self.token_count_last = completion.usage.total_tokens
        else:
            self.token_count_last = 0

        return validated_response

    def _request_single(self, src: str, show_dialog: bool = True):
        """Translate a single phrase (leaf of the binary split).

        For llama-server the phrase is sent as plain text via raw /v1/completions
        with NO json_object grammar — the JSON wrapper is only pinned for batches,
        and a lone phrase is far more reliable without it. For LM Studio the chat
        completions path with its JSON schema is used, as that provider needs it.
        Returns a TranslationResponse in both cases.
        """
        if self.provider == "llama-server":
            return self._request_translation(
                src,
                show_dialog=show_dialog,
                srcs=[src],
                structured_output=False,
            )
        return self._request_translation(
            self._batch_text([src]),
            show_dialog=show_dialog,
            srcs=[src],
            preserve_newlines=True,
        )

    def _translate_single(self, src: str, idx: int, translations: List[str]) -> None:
        """Leaf of the recursive binary split: translate one phrase with dialogs."""
        # show_dialog=False so the graceful retry/fallback below stays silent;
        # a dialog is only shown for genuine, unrecoverable errors.
        try:
            parsed = self._request_single(src, show_dialog=False)
        except TranslationAbortedError:
            raise
        except Exception as e:
            self.logger.warning(f"ID {idx}: request failed ({e}). Retrying once...")
            try:
                parsed = self._request_single(src, show_dialog=False)
            except TranslationAbortedError:
                raise
            except Exception as e2:
                self.logger.warning(f"ID {idx}: retry failed ({e2}). Falling back to source text.")
                translations[idx] = src
                return
        if not parsed or not parsed.translations:
            self.logger.warning(f"ID {idx}: empty/invalid response. Falling back to source text.")
            translations[idx] = src
            return
        tr: str = parsed.translations[0].translation

        # Echo: the model copied the source instead of translating. An echo
        # passes the empty and ratio checks silently (ratio ~= 1.0).
        # Retry once; if the model still echoes (legitimate for untranslatable
        # SFX / names like "THE", "FF!"), keep it as a graceful fallback.
        if self._is_echo(src, tr):
            self.logger.warning(f"ID {idx}: model echoed source '{src[:40]}'. Retrying individually...")
            echo_retry = self._request_single(src, show_dialog=False)
            if echo_retry and echo_retry.translations:
                retried_tr: str = echo_retry.translations[0].translation
                if retried_tr and not self._is_echo(src, retried_tr):
                    tr = retried_tr
                else:
                    self.logger.warning(
                        f"ID {idx}: source still echoed after retry, keeping it as fallback: '{tr[:40]}'"
                    )

        # Empty translation for a non-empty source
        if not tr.strip() and src.strip():
            self.logger.warning(f"Empty translation for source: '{src[:20]}...'")
            empty_response = self._request_single(src, show_dialog=True)
            tr = empty_response.translations[0].translation
            if not tr:
                create_error_dialog(f"ID {idx}: Empty translation for source '{src[:20]}...'")
                raise TranslationIntegrityError(f"ID {idx}: Empty translation for source '{src[:20]}...'")

        # ID leak: echoed id=N: prefix (all providers) or full leak (non-llama-server)
        if self._has_id_prefix_leak(tr) or (self.provider != "llama-server" and self._has_id_leak(tr)):
            self.logger.warning(f"ID leak detected in translation #{idx+1}: '{tr[:100]}'. Retrying individually...")
            id_leak_response = self._request_single(src, show_dialog=False)
            tr = id_leak_response.translations[0].translation
            if not tr or self._has_id_prefix_leak(tr) or (self.provider != "llama-server" and self._has_id_leak(tr)):
                create_error_dialog(f"ID {idx}: ID leak detected in translation '{tr[:20]}...'", 'Translation failed.')
                raise TranslationIntegrityError(f"ID {idx}: ID leak detected in translation '{tr[:20]}...'")

        # Compression ratio heuristic.
        # Only run for sufficiently long sources — short phrases ("So, anyway...")
        # legitimately yield wordy translations (e.g. a 13-char source -> a 24-char
        # Russian sentence), so a ratio outside [0.40, 2.0] is expected and NOT a
        # problem. This mirrors the len(src) > 25 guard used by _find_problems.
        if len(src) > 25:
            LOW_RATIO_THRESHOLD = 0.40
            HIGH_RATIO_THRESHOLD = 2.0
            current_ratio = len(tr) / len(src)
            if current_ratio < LOW_RATIO_THRESHOLD:
                self.logger.warning(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                ratio_response = self._request_single(src, show_dialog=True)
                tr = ratio_response.translations[0].translation
                current_ratio = len(tr) / len(src)
                if current_ratio < LOW_RATIO_THRESHOLD:
                    if create_yes_no_dialog(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}).\nSrc={src}\nTrans={tr}\n\nStop translation?"):
                        raise TranslationIntegrityError(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                    else:
                        self.logger.warning(f"Low compression ignored by user, continuing with: {tr}.")
            elif current_ratio > HIGH_RATIO_THRESHOLD:
                self.logger.warning(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                ratio_response = self._request_single(src, show_dialog=True)
                tr = ratio_response.translations[0].translation
                current_ratio = len(tr) / len(src)
                if self._is_high_ratio_problem(src, tr):
                    if create_yes_no_dialog(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}).\nSrc={src}\nTrans={tr}\n\nStop translation?"):
                        raise TranslationIntegrityError(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                    else:
                        self.logger.warning(f"High compression ignored by user, continuing with: {tr}.")

        if not src.endswith("{}") and tr.endswith("{}"):
            self.logger.warning("Удалён суффикс {}.")
            tr = tr.removesuffix("{}")

        translations[idx] = tr

    def _translate_batch(self, srcs: List[str], orig_indices: List[int], translations: List[str]) -> None:
        """Recursively translate a batch: whole-first, then binary split on any problem."""
        # import debugpy
        # debugpy.debug_this_thread()
        # debugpy.breakpoint()
        # A single element must NOT go through the id=N:/json_schema batch path:
        # llama.cpp's grammar dead-ends on 1-element batches and returns the
        # sentinel -1000000000000000.0. Route it to the plain-text single path.
        if len(srcs) == 1:
            self._translate_single(srcs[0], orig_indices[0], translations)
            return

        try:
            parsed = self._request_translation(self._batch_text(srcs), show_dialog=False, srcs=srcs, preserve_newlines=True)
            result = self._ordered_translations(parsed, len(srcs))
            problems = self._find_problems(srcs, result)
        except TranslationAbortedError:
            raise
        except Exception as e:
            self.logger.warning(f"Batch of {len(srcs)} failed: {e}. Splitting.")
            problems = list(range(len(srcs)))

        self.logger.debug(f"translate_batch: batch len={len(srcs)}, problems={problems}")

        if problems:
            if len(srcs) == 1:
                self._translate_single(srcs[0], orig_indices[0], translations)
            else:
                mid = len(srcs) // 2
                self.logger.warning(f"translate batch with binary split on {mid}")
                self._translate_batch(srcs[:mid], orig_indices[:mid], translations)
                self._translate_batch(srcs[mid:], orig_indices[mid:], translations)
            return

        for j, tr in enumerate(result):
            translations[orig_indices[j]] = tr
        self.logger.info(f"Successfully translated batch len={len(srcs)}. Tokens used: {self.token_count_last}")

    # --- Cross-page deduplication (deterministic, instruction-independent) ---
    # TranslateGemma often re-renders a leading word that the previous page's
    # translation already covered ("...на одну из кроватей." + "Кровати.
    # Входит..."). Long English skip-instructions are outside its training
    # distribution and are unreliable, so the duplicate is stripped in code.

    _DEDUP_MAX_WORDS = 3            # cap on how many leading words may be stripped
    _DEDUP_RATIO_THRESHOLD = 0.80   # difflib similarity treated as a duplicate
    _DEDUP_MIN_PREFIX = 5           # min common prefix length (inflectional stem)

    @staticmethod
    def _dedup_norm_word(word: str) -> str:
        """Lowercase and drop everything non-alphanumeric for comparison."""
        return "".join(ch for ch in word.lower() if ch.isalnum())

    @classmethod
    def _is_duplicate_word(cls, prev_word: str, first_word: str) -> Tuple[bool, float]:
        """Fuzzy word comparison tolerant to inflection ('кровати' vs 'кроватей').

        Matches on: exact equality, difflib ratio >= _DEDUP_RATIO_THRESHOLD,
        or a common prefix of >= _DEDUP_MIN_PREFIX chars that covers at least
        one of the words completely (same stem, different ending).
        Returns (match, ratio); empty normalized words never match.
        """
        pw = cls._dedup_norm_word(prev_word)
        fw = cls._dedup_norm_word(first_word)
        if not pw or not fw:
            return False, 0.0
        if pw == fw:
            return True, 1.0
        ratio = difflib.SequenceMatcher(None, pw, fw).ratio()
        if ratio >= cls._DEDUP_RATIO_THRESHOLD:
            return True, ratio
        common = 0
        for a, b in zip(pw, fw):
            if a != b:
                break
            common += 1
        if common >= cls._DEDUP_MIN_PREFIX and (common >= len(pw) or common >= len(fw)):
            return True, ratio
        return False, ratio

    @staticmethod
    def _ends_mid_sentence(text: str) -> bool:
        """True when the text does not finish a sentence (no .!?… terminal
        punctuation, ignoring trailing closing quotes/brackets)."""
        t = text.strip().rstrip("'\u2019\u201d\u00bb\")]").rstrip()
        if not t:
            return False
        return t[-1] not in ".!?\u2026"

    def _maybe_strip_leading_duplication(
        self,
        batch_src: List[str],
        batch_orig: List[int],
        translations: List[str],
        prev_src_tail: str,
        prev_tr_tail: str,
    ) -> None:
        """Strip a leading fragment of this batch's first translation when it
        duplicates the tail of the previous batch/page translation.

        Guards: requires non-empty previous context AND a previous source tail
        that ends mid-sentence (otherwise the new text legitimately starts its
        own sentence and is never touched).
        """
        if not prev_src_tail or not prev_tr_tail:
            self.logger.debug("dedup-check: skipped (no previous context)")
            return
        if not self._ends_mid_sentence(prev_src_tail):
            self.logger.debug(
                "dedup-check: skipped (previous source ends with sentence-final punctuation)"
            )
            return
        # Locate the first translated line of this batch (page continuation).
        first_pos = None
        first_orig = None
        for pos, orig in enumerate(batch_orig):
            if translations[orig].strip():
                first_pos = pos
                first_orig = orig
                break
        if first_orig is None:
            self.logger.debug("dedup-check: skipped (batch has no non-empty translations)")
            return
        self.logger.debug(
            f"dedup-check: prev_src_tail={prev_src_tail!r} | prev_tr_tail={prev_tr_tail!r} "
            f"| first_src={batch_src[first_pos] if first_pos < len(batch_src) else ''!r}"
        )

        prev_words = prev_tr_tail.split()
        if not prev_words:
            return
        prev_idx = len(prev_words) - 1
        body = translations[first_orig]
        stripped_total = []
        first_match_ratio = None
        for _ in range(self._DEDUP_MAX_WORDS):
            body_l = body.lstrip()
            if not body_l:
                break
            first_token = body_l.split(None, 1)[0]
            match, ratio = self._is_duplicate_word(prev_words[prev_idx], first_token)
            if not match:
                if ratio >= 0.5:
                    self.logger.debug(
                        f"dedup-check: near-match but below threshold: {first_token!r} vs "
                        f"{prev_words[prev_idx]!r} (ratio={ratio:.2f}) - kept"
                    )
                break
            rest = body_l[len(first_token):]
            rest = rest.lstrip(".,!?…\u2026«»\"'\u201c\u201d()\u2014- ").lstrip()
            if not rest.strip():
                self.logger.debug("dedup-check: stripping would empty the line - kept")
                break
            stripped_total.append(first_token)
            if first_match_ratio is None:
                first_match_ratio = ratio
            body = rest[0].upper() + rest[1:]
            if prev_idx == 0:
                break  # cannot walk further back into the previous translation
            prev_idx -= 1
        if stripped_total:
            before = translations[first_orig]
            translations[first_orig] = body
            self.logger.warning(
                f"Deduplication: stripped leading fragment {' '.join(stripped_total)!r} from "
                f"page-continuation line (fuzzy-matched last word of previous translation: "
                f"{prev_words[-1]!r}, ratio={first_match_ratio:.2f})\n"
                f"before: {before!r}\nafter: {body!r}"
            )

    def _translate(self, src_list: List[str]) -> List[str]:
        if not src_list: return []
        # Filter out empty or trivially short texts вЂ” don't send them to the translator
        # Strip soft hyphens (\u00AD) and check if meaningful text remains
        def _is_meaningful(s: str) -> bool:
            clean = s.replace('\u00AD', '').strip()
            if not clean:
                return False
            # Must contain at least one letter or digit (not just punctuation/spaces)
            return any(c.isalpha() or c.isdigit() for c in clean)

        non_empty_indices = [i for i, s in enumerate(src_list) if _is_meaningful(s)]
        self.logger.debug(f"_translate: src_list={len(src_list)} items, non_empty={len(non_empty_indices)}")
        for i, s in enumerate(src_list):
            if not s.strip():
                self.logger.debug(f"  filtered out [{i}]: repr={repr(s[:50])}")
        if not non_empty_indices:
            return [""] * len(src_list)
        filtered_src = [src_list[i] for i in non_empty_indices]

        translations = [""] * len(src_list)

        for text, num_src, batch_orig_idx in self._pack_batches(filtered_src):
            batch_src = [filtered_src[k] for k in batch_orig_idx]
            batch_orig = [non_empty_indices[k] for k in batch_orig_idx]
            # Snapshot the tails BEFORE translating this batch: they still hold
            # the end of the previous batch/page and drive both the prompt
            # context and the deterministic leading-fragment deduplication.
            prev_src_tail = self.rolling_source_tail
            prev_tr_tail = self.rolling_context
            self._translate_batch(batch_src, batch_orig, translations)
            self._maybe_strip_leading_duplication(
                batch_src, batch_orig, translations, prev_src_tail, prev_tr_tail
            )
            # Rolling tails are deliberately NOT reset between _translate()
            # calls (i.e. between pages): they persist so a sentence split
            # across a page boundary translates as one seamless continuation.
            translated_tail = [t for t in translations if t.strip()][-3:]
            self.rolling_context = "\n".join(translated_tail)
            self.rolling_source_tail = "\n".join(batch_src[-2:])

        # Fall back to original text when translation is empty
        for i in range(len(translations)):
            if not translations[i].strip() and src_list[i].strip():
                self.logger.warning(f"No translation for '{src_list[i][:30]}', using original text")
                translations[i] = src_list[i]

        return translations
    
    # Паттерн для утечки id-префикса — модель эхом возвращает "id=N: " из запроса.
    # НЕ включает хвостовой артефакт "}]}" — он безобиден для llama-server.
    _ID_PREFIX_LEAK_RE = re.compile(
        r'\{\s*ID\s*[=:]\s*\d+[^}]*\}'    # {ID=2}, {ID: 2}, {ID=2: текст...}, {ID: 3}
        r'|(?:^|\s)id\s*[=:]\s*\d+\s*:',  # id=2: или id: 3: в начале или после пробела
        re.IGNORECASE
    )

    # Паттерн для обнаружения утечки ID в переводе
    _ID_LEAK_RE = re.compile(
        r'\{\s*ID\s*[=:]\s*\d+[^}]*\}'    # {ID=2}, {ID: 2}, {ID=2: текст...}, {ID: 3}
        r'|(?:^|\s)id\s*[=:]\s*\d+\s*:'   # id=2: или id: 3: в начале или после пробела
        r'|\}\s*\]\s*\}\s*$',             # хвостовые JSON-артефакты } ]}
        re.IGNORECASE
    )

    def _single_alternative(self, text: str, src: str = "") -> str:
        """Keep only the first variant when the model returns 'A / B' style alternatives.

        When the source text itself contains the separator (e.g. credits
        "F. Doyle / D. DeCarlo"), slashes in the output are structural — the
        model faithfully renders a list of names — so they are preserved.
        """
        # If the model echoed the request's id=N: prefix, do NOT truncate here.
        # Leave the full text so _find_problems can flag it and the batch
        # binary-splits down to a single element re-translated with its source.
        if self._has_id_prefix_leak(text):
            self.logger.debug(f"id-prefix leak detected, returning text unchanged: {text!r}")
            return text.strip()
        for sep in (" / ", " | "):
            if sep in src:
                self.logger.debug(f"separator {sep!r} present in source, preserving: {text!r}")
                continue
            if sep in text:
                first = text.split(sep, 1)[0].strip()
                self.logger.warning(
                    f"Multiple translation variants detected, keeping the first one: {first!r} (src={src!r})"
                )
                return first
        stripped = text.strip()
        if stripped != text:
            self.logger.debug(f"Trimmed translation whitespace: {text!r} -> {stripped!r}")
        return stripped

    @staticmethod
    def _is_high_ratio_problem(src: str, tr: str) -> bool:
        """True when the translation is implausibly longer than the source.

        Both call sites (_find_problems and _translate_single) only invoke
        this for sources longer than 25 chars, so short sources never reach
        the ratio check at all. The absolute-length floor is kept as a second
        condition: a long source (> 25 chars) with a suspicious >2x ratio
        still only counts as a problem when the translation itself exceeds
        MIN_ABS_LEN_FOR_HIGH_RATIO characters.
        """
        if len(tr) <= len(src) * HIGH_RATIO_THRESHOLD:
            return False
        return len(tr) > MIN_ABS_LEN_FOR_HIGH_RATIO

    @staticmethod
    def _has_id_prefix_leak(text: str) -> bool:
        """True when the translation echoes the request's id=N: / {ID=N} prefix.

        Unlike _has_id_leak, this deliberately matches ONLY the prefix patterns
        and NOT the trailing "}]}" artifact, which llama-server sometimes emits
        as harmless structured-output noise. Checking the prefix leak for ALL
        providers lets _find_problems flag the element so the batch binary-splits
        and the single element is re-translated with its correct source.
        """
        return bool(TransGemmaTranslator._ID_PREFIX_LEAK_RE.search(text))

    @staticmethod
    def _has_id_leak(text: str) -> bool:
        """Check if translation contains ID artifacts from the request."""
        return bool(TransGemmaTranslator._ID_LEAK_RE.search(text))

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        # self.logger.debug(f"Parameter '{param_key}' updated.")
        
        if param_key in ["endpoint", "provider"]:
        #   self.logger.info(f"Client will be re-initialized on next request due to change in '{param_key}'.")
            self.client = None
            self.n_ctx = None

# Командная строка для llama-server
# TranslateGemma llama-server WITHOUT the embedded chat template.
# The GGUF template crashes llama.cpp's parser at init (see er.txt), and the
# app builds the Gemma3 prompt itself for raw /v1/completions.
# llama-server -m "h:\AI_Summarize\models\bullerwins\translategemma-27b-it-GGUF\translategemma-27b-it-Q6_K.gguf" --no-jinja -np 1 --temp 0.3 -b 512 -ub 256 --n-gpu-layers 99 --host 127.0.0.1 --port 1234 --no-mmap
# Для LM Studio заменить template jinja в 
# -%}
# {{ bos_token }}
# {%- if (messages[0]['role'] != 'user') -%}
#     {{ raise_exception("Conversations must start with a user prompt.") }}
# {%- endif -%}
# {%- for message in messages -%}
#     {%- if (message['role'] == 'user') != (loop.index0 % 2 == 0) -%}
#         {{ raise_exception("Conversation roles must alternate user/assistant/user/assistant/...") }}
#     {%- endif -%}
#     {%- if (message['role'] == 'assistant') -%}
#         {%- if message['content'] is none or message['content'] is not string -%}
#             {{ raise_exception("Assistant role must provide content as a string") }}
#         {%- endif -%}
#         {{ '<start_of_turn>model\n'}}
#         {{ message["content"] | trim }}
#     {%- elif (message['role'] == 'user') -%}
#         {% set actual_text = message['content'].split('\n', 1)[1] %}
#         {%- set source_lang_code =  message['content'].split('<|source_lang|>')[1].split('<|target_lang|>')[0] | replace("_", "-")  -%}
#         {%- set source_lang = languages[source_lang_code] -%}
#         {%- set target_lang_code = message['content'].split('<|target_lang|>')[1].split('\n')[0] | replace("_", "-") -%}
#         {%- set target_lang = languages[target_lang_code] -%}
#         {{ '<start_of_turn>user\nYou are a professional ' + source_lang + ' (' + source_lang_code + ') to ' +
#            target_lang + ' (' + target_lang_code + ') translator. Your goal is to accurately convey the meaning and '
#            'nuances of the original ' + source_lang + ' text while adhering to ' + target_lang + ' grammar, '
#            'vocabulary, and cultural sensitivities.\n'
#         }}
#         {{
#             'Produce only the ' + target_lang + ' translation, without any additional explanations or ' +
#             'commentary. Please translate the following ' + source_lang + ' text into ' + target_lang + ':\n\n\n' +
#             actual_text | trim
#         }}
#     {%- else -%}
#         {{ raise_exception("Conversations must only contain user or assistant roles.") }}
#     {%- endif -%}
#     {{ '<end_of_turn>\n' }}
# {%- endfor -%}
# {%- if add_generation_prompt -%}
#     {{'<start_of_turn>model\n'}}
# {%- endif -%}
