import re
import time
import json
import traceback
from typing import List, Dict, Optional, Type

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from .base import BaseTranslator, register_translator


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


@register_translator("TransGemma")
class TransGemmaTranslator(BaseTranslator):
    concate_text = False
    cht_require_convert = True
    params: Dict = {
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
            "value": 0.1,
            "description": "Sampling temperature. Lower values are recommended for structured output.",
        },
        "top p": {
            "value": 1.0,
            "description": "Top P for sampling.",
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

    def _initialize_client(self, api_key_to_use: str) -> bool:
        endpoint = self.endpoint
        if not endpoint:
            endpoint = "http://127.0.0.1:1234/v1"
            # endpoint = "http://127.0.0.1:1234/api/v1/chat

        http_client = httpx.Client()
        self.logger.debug(f"Initializing client with at endpoint {endpoint}")

        try:
            self.client = OpenAI(api_key=api_key_to_use, base_url=endpoint, http_client=http_client)
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {e}")
            self.client = None
            return False

    # --- Property getters ---
    @property
    def endpoint(self) -> Optional[str]: return self.get_param_value("endpoint") or None
    @property
    def temperature(self) -> float: return float(self.get_param_value("temperature"))
    @property
    def top_p(self) -> float: return float(self.get_param_value("top p"))
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

    def _assemble_prompts(self, queries: List[str], to_lang: str, max_len_approx=16000):
        current_prompt_content = ""
        num_src = 0
        i_offset = 0

        for i, query in enumerate(queries):
            query = query.replace('\n', ' ')
            element = f"id={i + 1 - i_offset}: {query}\n"
            # element = f"<ID>{i + 1 - i_offset}</ID>\n<TEXT>{query}</TEXT>\n<<<END>>>"
            if len(current_prompt_content) + len(element) > max_len_approx and num_src > 0:
                yield current_prompt_content, num_src
                current_prompt_content = element
                num_src = 1
                i_offset = i
            else:
                current_prompt_content += element
                num_src += 1

        if num_src > 0:
            yield current_prompt_content, num_src

    def _request_translation(self, text: str) -> Optional[TranslationResponse]:
        current_api_key = "lm-studio"
        text = text.replace("\n", " ")
        # import debugpy
        # debugpy.debug_this_thread()
        # debugpy.breakpoint()

        if not self._initialize_client(current_api_key):
             raise ConnectionError("Failed to initialize API client.")
        
        model_name = 'translategemma-27b-it'

        from_lang = self.lang_map.get(self.lang_source, self.lang_source)
        to_lang = self.lang_map.get(self.lang_target, self.lang_target)
        prompt = (
            f"<|source_lang|>{from_lang}<|target_lang|>{to_lang}\n"
            f"{text}"
        )
        messages = [
            {"role": "user", "content": prompt},
        ]
        # messages = [
            # {"role": "user", 
            #  "content": [
            #     {
            #         "type": "text",
            #         "source_lang_code": "en",
            #         "target_lang_code": "ru",
            #         "text": text
            #     }]
            # }
        # ]
        #   "role": "user",
        # "content": [
        #     {
        #         "type": "text",
        #         "source_lang_code": "en",
        #         "target_lang_code": "es",
        #         "text": text,
        #     }
        # ],
        # print(messages)

        api_args = {
            "model": model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }

        self.logger.debug("Using 'json_schema' mode for LLM Studio.")
        api_args["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "schema": TranslationResponse.model_json_schema()
            },
        }

        # api_args["frequency_penalty"] = self.frequency_penalty
        # api_args["presence_penalty"] = self.presence_penalty
    
        try:
            completion = self.client.chat.completions.create(**api_args)
        except Exception as e:
            self.logger.error(f"API request failed: {e}")
            raise

        if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
            raw_content = completion.choices[0].message.content
            json_to_parse = raw_content.strip()

            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_to_parse, re.DOTALL)
            if match:
                self.logger.debug("Markdown code block detected. Extracting JSON content.")
                json_to_parse = match.group(1)
            else:
                start = json_to_parse.find('{')
                end = json_to_parse.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_to_parse = json_to_parse[start:end+1]

            try:
                data_to_validate = json.loads(json_to_parse)
                validated_response = TranslationResponse.model_validate(data_to_validate)
            except (ValidationError, json.JSONDecodeError) as e:
                self.logger.error(f"Pydantic validation or JSON parsing failed: {e}")
                self.logger.debug(f"Raw JSON content from API: {raw_content}")
                raise
        else:
            self.logger.warning("No valid message content in API response.")
            return None

        if hasattr(completion, 'usage') and completion.usage:
            self.token_count += completion.usage.total_tokens
            self.token_count_last = completion.usage.total_tokens
        else:
            self.token_count_last = 0
            
        return validated_response

    def _translate(self, src_list: List[str]) -> List[str]:
        if not src_list: return []
        translations = []
        to_lang = self.lang_map.get(self.lang_target, self.lang_target)

        for text, num_src in self._assemble_prompts(src_list, to_lang=to_lang):
            # api_retry_attempt = 0
            # mismatch_retry_attempt = 0
            # skipped_translation_retry_attempt = 0
            
            # while True:
                # try:
            parsed_response = self._request_translation(text)
                            
                    # import debugpy
                    # debugpy.debug_this_thread()
                    # debugpy.breakpoint()

            if not parsed_response or not parsed_response.translations:
                raise ValueError("Received empty or invalid parsed response from API.")
            
            translations_dict = {item.id: item.translation for item in parsed_response.translations}

            if len(parsed_response.translations) != num_src:
            #     raise InvalidNumTranslations(f"Expected {num_src}, got {len(parsed_response.translations)}")
                self.logger.warning(f"Translation structure mismatch: scr={num_src}/translations={len(parsed_response.translations)}.")
            
                # Получаем список недостающих ID
                existing_ids = {item.id for item in parsed_response.translations}
                missing_ids = [i for i in range(1, num_src + 1) if i not in existing_ids]
                
                for missing_id in sorted(missing_ids):
                    self.logger.warning(f"Missing ID: {missing_id}. Requesting separately...")
                    # import debugpy
                    # debugpy.debug_this_thread()
                    # debugpy.breakpoint()
                    # Запрашиваем только недостающие элементы
                    missing_text = src_list[missing_id-1]
                    missing_response = self._request_translation(missing_text)
                    tr: str = missing_response.translations[0].translation
                    if (tr.strip()):
                        self.logger.warning(f"Get missing translation: {tr}.")
                        translations_dict[missing_id] = tr
                    else:
                        raise InvalidNumTranslations(f"Missing translation. Can not translate {missing_text}.")

            ordered_translations = [translations_dict.get(i, "") for i in range(1, num_src + 1)]

            for i, (src, trans) in enumerate(zip(src_list, ordered_translations)):
                # Проверка на пустой результат при непустом источнике
                if not trans.strip() and src.strip():
                    self.logger.warning(f"Empty translation for source: '{src[:20]}...'")
                    # import debugpy
                    # debugpy.debug_this_thread()
                    # debugpy.breakpoint()
                    empty_response = self._request_translation(src)
                    tr: str = empty_response.translations[0].translation
                    if not tr:
                        raise TranslationIntegrityError(f"ID {i}: Empty translation for source '{src[:20]}...'")
                    else:
                        ordered_translations[i] = tr

                # if len(src) < 3:
                #     continue

                # Эвристика коэффициента сжатия
                RATIO_THRESHOLD = 0.47
                current_ratio = len(trans) / len(src)
                if current_ratio < RATIO_THRESHOLD:
                    self.logger.warning(f"ID {i}: Low compression ratio ({current_ratio:.2f} < {RATIO_THRESHOLD}). \n{src} \n{trans}")
                    # import debugpy
                    # debugpy.debug_this_thread()
                    # debugpy.breakpoint()
                    ratio_response = self._request_translation(src)
                    tr: str = ratio_response.translations[0].translation
                    current_ratio = len(tr) / len(src)
                    if current_ratio < RATIO_THRESHOLD and (len(src) > 20):
                        raise TranslationIntegrityError(f"ID {i}: Low compression ratio ({current_ratio:.2f} < {RATIO_THRESHOLD}). \n{src} \n{trans}")
                    else:
                        self.logger.warning(f"Get translation for low compression: {tr}.")
                        ordered_translations[i] = tr

            translations.extend(ordered_translations)
            self.logger.info(f"Successfully translated batch of {num_src}. Tokens used: {self.token_count_last}")
            # break

                # except TranslationIntegrityError as e:
                #     skipped_translation_retry_attempt += 1
                #     self.logger.warning(f"Skipped translation: {e}. Attempt {skipped_translation_retry_attempt}/3.")
                #     if skipped_translation_retry_attempt >= 3:
                #         self.logger.error("Failed to translate after retries.")
                #         translations.extend(["[ERROR: Skipped translation]"] * num_src)
                #         raise  
                #     time.sleep(self.retry_timeout / 2)

                # except InvalidNumTranslations as e:
                #     mismatch_retry_attempt += 1
                #     self.logger.warning(f"Translation structure mismatch: {e}. Attempt {mismatch_retry_attempt}/{self.invalid_repeat_count}.")
                #     if mismatch_retry_attempt >= self.invalid_repeat_count:
                #         self.logger.error("Failed to get correct translation structure after retries.")
                #         translations.extend(["[ERROR: Structure Mismatch]"] * num_src)
                #         raise  
                #     time.sleep(self.retry_timeout / 2)
                
                # except Exception as e:
                #     api_retry_attempt += 1
                #     self.logger.warning(f"API request/parsing failed: {e}. Attempt {api_retry_attempt}/{self.retry_attempts}.")
                #     if api_retry_attempt >= self.retry_attempts:
                #         self.logger.error(f"Failed to translate batch after {self.retry_attempts} attempts: {traceback.format_exc()}")
                #         translations.extend([f"[ERROR: API Failed]"] * num_src)
                #         raise  
                #     time.sleep(self.retry_timeout)
                    
        return translations

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        # self.logger.debug(f"Parameter '{param_key}' updated.")
        
        if param_key in ["endpoint"]:
        #   self.logger.info(f"Client will be re-initialized on next request due to change in '{param_key}'.")
            self.client = None

# Заменить template jinja
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