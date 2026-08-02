import re
import time
import json
import math
import traceback
from typing import List, Dict, Optional, Type, Tuple, Generator

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from .base import BaseTranslator, register_translator

from utils.message import create_error_dialog, create_yes_no_dialog

MAX_LEN_APPROX = 36000

# Token-budget constants for whole-first batching (see _pack_batches).
PROMPT_OVERHEAD = 150          # tokens for the _build_llama_prompt template
BATCH_SAFETY_FACTOR = 0.9      # 10% safety margin when packing
OUTPUT_PER_ELEMENT = 15        # tokens for the {"id":N,"translation":"..."} wrapper
OUTPUT_GROWTH_FACTOR = 1.3     # translation length growth factor
MIN_BUDGET = 256               # lower bound for the token budget
HIGH_RATIO_THRESHOLD = 2.0     # translation/source length ratio considered suspicious
MIN_ABS_LEN_FOR_HIGH_RATIO = 20  # absolute floor so short sources are still protected

class InvalidNumTranslations(Exception):
    """Exception raised when the number of translations does not match the number of sources."""
    pass

class TranslationIntegrityError(Exception):
    """Exception raised when a translation fragment is suspiciously short or empty."""
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
            "value": 0.3,
            "description": "Sampling temperature. Lower values are recommended for structured output.",
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

    def _find_problems(self, srcs: List[str], result: List[str]) -> List[int]:
        """Return indices of phrases whose translation is suspicious.

        A problem is: empty translation for a non-empty source, an id leak
        (non-llama-server only), an echoed id=N: prefix (all providers), or a
        compression ratio outside [0.40, 2.0] for sources longer than 25 chars
        (short phrases skip the ratio check).
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
                problems.append(i)
                continue
            if len(src) > 25:
                ratio = len(tr) / len(src)
                if ratio < 0.40:
                    self.logger.debug(f"find_problems: idx={i} flagged (low-ratio {ratio:.2f}): {tr!r}")
                    problems.append(i)
                    continue
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

    def _build_llama_prompt(self, text: str, from_lang: str, to_lang: str) -> str:
        """Build the raw prompt for /v1/completions (Gemma3 turn markup, no chat template)."""
        from_name = _LANG_NAMES.get(from_lang.split('_')[0].split('-')[0], from_lang)
        to_name = _LANG_NAMES.get(to_lang.split('_')[0].split('-')[0], to_lang)
        context = self.context.strip()
        context_line = f"Context: {context}.\n" if context else ""
        return (
            "<start_of_turn>user\n"
            f"You are a professional {from_name} ({from_lang}) to {to_name} ({to_lang}) translator. "
            f"Your goal is to accurately convey the meaning and nuances of the original {from_name} "
            f"text while adhering to {to_name} grammar, vocabulary, and cultural sensitivities.\n"
            f"Produce only the {to_name} translation, without any additional explanations or commentary. "
            "Provide exactly one translation variant per segment; do not give alternatives and do not use '/' or '|'.\n"
            f"{context_line}"
            'The output must be a valid JSON object: {"translations":[{"id":1,"translation":"<translated text>"},{"id":2,"translation":"..."}, ...]}.\n'
            f"Please translate the following {from_name} text into {to_name}:\n\n\n"
            f"{text}\n"
            "<end_of_turn>\n"
            "<start_of_turn>model"
        )

    def _request_translation(self, text: str, show_dialog: bool = True, srcs: Optional[List[str]] = None) -> Optional[TranslationResponse]:
        current_api_key = "lm-studio"
        text = text.replace("\n", " ")

        # Map element id -> source text so _single_alternative can tell apart
        # model-provided alternatives ("A / B") from a faithful slash-separated
        # list in the source (e.g. credits "F. Doyle / D. DeCarlo / ...").
        src_by_id = {i + 1: s for i, s in enumerate(srcs or [])}
        if not srcs:
            src_by_id[1] = text

        if not self._initialize_client(current_api_key):
             raise ConnectionError("Failed to initialize API client.")

        self._fetch_context_window()

        model_name = 'translategemma-27b-it'

        from_lang = self.lang_map.get(self.lang_source, self.lang_source)
        to_lang = self.lang_map.get(self.lang_target, self.lang_target)

        provider = self.provider
        raw_content = None
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
                if show_dialog:
                    create_error_dialog(e, 'Translation failed.')
                raise

            if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                raw_content = completion.choices[0].message.content
        else:
            # llama-server: raw /v1/completions with a self-built prompt (no chat template).
            # Top-level json_schema is the native llama.cpp structured-output parameter
            # (response_format is ignored on /v1/completions in current builds).
            prompt = self._build_llama_prompt(text, from_lang, to_lang)
            api_args = {
                "model": model_name,
                "prompt": prompt,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_tokens": self.max_tokens,
                "extra_body": {
                    "json_schema": {
                        "schema": _LLAMA_JSON_SCHEMA
                    },
                },
            }
            self.logger.debug("Using raw '/v1/completions' with top-level json_schema for llama-server.")
            try:
                completion = self.client.completions.create(**api_args)
            except Exception as e:
                self.logger.error(f"API request failed: {e}")
                if show_dialog:
                    create_error_dialog(e, 'Translation failed.')
                raise

            if completion.choices and completion.choices[0].text:
                raw_content = completion.choices[0].text

        if raw_content is None:
            self.logger.warning("No valid message content in API response.")
            return None

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
            for item in validated_response.translations:
                item.translation = self._single_alternative(item.translation, src_by_id.get(item.id, ""))
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Pydantic validation or JSON parsing failed: {e}")
            self.logger.debug(f"Raw JSON content from API: {raw_content}")
            if show_dialog:
                create_error_dialog(e, 'Translation failed.')
            raise

        if hasattr(completion, 'usage') and completion.usage:
            self.token_count += completion.usage.total_tokens
            self.token_count_last = completion.usage.total_tokens
        else:
            self.token_count_last = 0
            
        return validated_response

    def _translate_single(self, src: str, idx: int, translations: List[str]) -> None:
        """Leaf of the recursive binary split: translate one phrase with dialogs."""
        # show_dialog=False so the graceful retry/fallback below stays silent;
        # a dialog is only shown for genuine, unrecoverable errors.
        try:
            parsed = self._request_translation(src, show_dialog=False)
        except Exception as e:
            self.logger.warning(f"ID {idx}: request failed ({e}). Retrying once...")
            try:
                parsed = self._request_translation(src, show_dialog=False)
            except Exception as e2:
                self.logger.warning(f"ID {idx}: retry failed ({e2}). Falling back to source text.")
                translations[idx] = src
                return
        if not parsed or not parsed.translations:
            self.logger.warning(f"ID {idx}: empty/invalid response. Falling back to source text.")
            translations[idx] = src
            return
        tr: str = parsed.translations[0].translation

        # Empty translation for a non-empty source
        if not tr.strip() and src.strip():
            self.logger.warning(f"Empty translation for source: '{src[:20]}...'")
            empty_response = self._request_translation(src, show_dialog=True)
            tr = empty_response.translations[0].translation
            if not tr:
                create_error_dialog(f"ID {idx}: Empty translation for source '{src[:20]}...'")
                raise TranslationIntegrityError(f"ID {idx}: Empty translation for source '{src[:20]}...'")

        # ID leak: echoed id=N: prefix (all providers) or full leak (non-llama-server)
        if self._has_id_prefix_leak(tr) or (self.provider != "llama-server" and self._has_id_leak(tr)):
            self.logger.warning(f"ID leak detected in translation #{idx+1}: '{tr[:100]}'. Retrying individually...")
            id_leak_response = self._request_translation(src, show_dialog=False)
            tr = id_leak_response.translations[0].translation
            if not tr or self._has_id_prefix_leak(tr) or (self.provider != "llama-server" and self._has_id_leak(tr)):
                create_error_dialog(f"ID {idx}: ID leak detected in translation '{tr[:20]}...'", 'Translation failed.')
                raise TranslationIntegrityError(f"ID {idx}: ID leak detected in translation '{tr[:20]}...'")

        # Compression ratio heuristic
        LOW_RATIO_THRESHOLD = 0.40
        HIGH_RATIO_THRESHOLD = 2.0
        current_ratio = len(tr) / len(src)
        if current_ratio < LOW_RATIO_THRESHOLD:
            self.logger.warning(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
            ratio_response = self._request_translation(src, show_dialog=True)
            tr = ratio_response.translations[0].translation
            current_ratio = len(tr) / len(src)
            if current_ratio < LOW_RATIO_THRESHOLD and (len(src) > 25):
                if create_yes_no_dialog(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}).\nSrc={src}\nTrans={tr}\n\nStop translation?"):
                    raise TranslationIntegrityError(f"ID {idx}: Low compression ratio ({current_ratio:.2f} < {LOW_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                else:
                    self.logger.warning(f"Low compression ignored by user, continuing with: {tr}.")
        elif current_ratio > HIGH_RATIO_THRESHOLD:
            self.logger.warning(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
            ratio_response = self._request_translation(src, show_dialog=True)
            tr = ratio_response.translations[0].translation
            current_ratio = len(tr) / len(src)
            if self._is_high_ratio_problem(src, tr):
                if create_yes_no_dialog(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}).\nSrc={src}\nTrans={tr}\n\nStop translation?"):
                    raise TranslationIntegrityError(f"ID {idx}: High compression ratio ({current_ratio:.2f} > {HIGH_RATIO_THRESHOLD}). \nSrc={src} \nTrans={tr}")
                else:
                    self.logger.warning(f"High compression ignored by user, continuing with: {tr}.")

        if not src.endswith("{}") and tr.endswith("{}"):
            self.logger.warning("Удален суффикс {}.")
            tr = tr.removesuffix("{}")

        translations[idx] = tr

    def _translate_batch(self, srcs: List[str], orig_indices: List[int], translations: List[str]) -> None:
        """Recursively translate a batch: whole-first, then binary split on any problem."""
        try:
            parsed = self._request_translation(self._batch_text(srcs), show_dialog=False, srcs=srcs)
            result = self._ordered_translations(parsed, len(srcs))
            problems = self._find_problems(srcs, result)
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

    def _translate(self, src_list: List[str]) -> List[str]:
        if not src_list: return []
        # Filter out empty or trivially short texts — don't send them to the translator
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
            self._translate_batch(batch_src, batch_orig, translations)

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

        Uses an absolute-length floor so short sources (e.g. "THE") are still
        protected from hallucinated long titles, while legitimate short
        translations like "OK" -> "Хорошо" are not flagged.
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