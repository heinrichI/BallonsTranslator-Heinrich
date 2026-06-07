from ui.SpellCheckDialog import SpellCheckDialog
from spylls.hunspell.dictionary import Dictionary
from utils.logger import logger as LOGGER
from typing import Dict, List, Union, Optional
import os
import json
from utils.download_util import download_and_check_files

en_flist = [
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/en/index.aff',
        'sha256_pre_calculated': ['8ae1f19d4840d957728ad90555d5a8dff6cc5c046279c95ff0c00fc0a0136c7b'],
        'files': 'data/spellcheck/en/index.aff'
    },
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/en/index.dic',
        'sha256_pre_calculated': ['f0b1a234bd178bdd01875b2a392a9647f888b8fe879f79c52aae62c2759b3647'],
        'files': 'data/spellcheck/en/index.dic'
    },
]
fr_flist = [
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/fr/index.aff',
        'sha256_pre_calculated': ['05a735d34c912e4e381ff08ee7c747923ccf5cf9dca81d8467982fa1ca51c2b7'],
        'files': 'data/spellcheck/fr/index.aff'
    },
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/fr/index.dic',
        'sha256_pre_calculated': ['984e933237bc1224a48f42828233be9b03228260ef67aa8e2bdddcd03a26230d'],
        'files': 'data/spellcheck/fr/index.dic'
    },
]
it_flist = [
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/it/index.aff',
        'sha256_pre_calculated': ['5770cd3e16d494c045b4a9a4a9fcd7962577e642d0384a7129c020a12cdd2c79'],
        'files': 'data/spellcheck/it/index.aff'
    },
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/it/index.dic',
        'sha256_pre_calculated': ['b1348fbdb6f441ea9dd7e33b2cfcb96ead39ccd5e48bf894972774cd5aa86abb'],
        'files': 'data/spellcheck/it/index.dic'
    },
]
de_flist = [
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/de/index.aff',
        'sha256_pre_calculated': ['57fdd1b16aac2131003c91e0cf2a488becb970382a402a9ce089307301cb3ef0'],
        'files': 'data/spellcheck/de/index.aff'
    },
    {
        'url': 'https://github.com/wooorm/dictionaries/raw/refs/heads/main/dictionaries/de/index.dic',
        'sha256_pre_calculated': ['b5c781a0cf6f285fb6b9b8ab02fbea104b987104a1efdda8a835837e89e3ec77'],
        'files': 'data/spellcheck/de/index.dic'
    },
]
SUPPORTED_LANGS = ['en','fr','it','de']
_ENGINE: Optional['SpellCheckEngine'] = None

def get_spellcheck_engine(lang: Union[str, None] = None):
    """
    Return a singleton SpellCheckEngine. If an engine doesn't exist, create one.
    If lang is provided and differs from current engine language, reload it.
    """
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SpellCheckEngine(lang)
    else:
        if lang is not None and getattr(_ENGINE, "lang", None) != lang:
            _ENGINE.reload_language(lang)
    return _ENGINE

def reload_spellcheck_language(lang: str):
    """
    Force reload/create the module-level SpellCheckEngine with the given language.
    """
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SpellCheckEngine(lang)
    else:
        _ENGINE.reload_language(lang)
    return _ENGINE

class SpellCheckEngine:
    def __init__(self, lang: Union[str, None] = None) -> None:
        # If lang not provided, read default from program config
        try:
            from utils.config import pcfg as _pcfg  # local import to avoid cycles
            cfg_lang = _pcfg.spellcheck_language
        except Exception:
            cfg_lang = 'en'

        self.logger = LOGGER
        self.lang = lang if lang is not None else cfg_lang

        # download and load dictionary for selected language
        if self.lang == 'en':
            for files_download_kwargs in en_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/en/index')
        elif self.lang == 'fr':
            for files_download_kwargs in fr_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/fr/index')
        elif self.lang == 'it':
            for files_download_kwargs in it_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/it/index')
        elif self.lang == 'de':
            for files_download_kwargs in de_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/de/index')
        else:
            # fallback to English
            for files_download_kwargs in en_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/en/index')

        # Define the path for saving/loading data (one per language)
        self.data_file = f"SpellCheckEngine_{self.lang}.json"
        self._load_data()
        # replace_words is a list of tuples like this:
        # self.replace_words = [('wrng', 'wrong'), ('teh', 'the')]
        self.replace_words = []

    def _load_data(self):
        """Loads skipped_words and replace_words from the JSON file."""
        default_skipped = []
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    self.skipped_words = data.get('skipped_words', default_skipped)
                    # replace_words is a list of tuples like: [('wrng', 'wrong'), ('teh', 'the')]
                    # JSON stores tuples as lists, so we convert them back if needed.
                    # loaded_replace = data.get('replace_words', default_replace)
                    # self.replace_words = [tuple(item) if isinstance(item, list) else item for item in loaded_replace]
                    
                self.logger.info(f"Successfully loaded data from {self.data_file}")
                
            except json.JSONDecodeError:
                self.logger.error(f"Error decoding JSON from {self.data_file}. Using default values.")
                self.skipped_words = default_skipped
                # self.replace_words = default_replace
            except Exception as e:
                self.logger.error(f"An unexpected error occurred while loading {self.data_file}: {e}. Using defaults.")
                self.skipped_words = default_skipped
                # self.replace_words = default_replace
        else:
            self.logger.info(f"Data file {self.data_file} not found. Initializing with defaults.")
            self.skipped_words = default_skipped
            # self.replace_words = default_replace

    def _save_data(self):
        """Saves the current skipped_words and replace_words to the JSON file."""
        data_to_save = {
            'skipped_words': self.skipped_words,
            # Convert tuples in replace_words to lists for JSON compatibility
            # 'replace_words': [list(item) for item in self.replace_words]
        }
        
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Successfully saved data to {self.data_file}")
        except IOError as e:
            self.logger.error(f"Failed to save data to {self.data_file}: {e}")

    def DoSuggest(self, word: str):
        return self.dictionary.suggest(word)

    # def UnknownWords(self, text: str):
    #     """
    #     Generator that iterates over unknown words in the provided text.
        
    #     It splits the text on whitespace, strips each word of punctuation defined in
    #     'split_chars', and then yields the word if it isn't a number and it is not
    #     found in the dictionary.
    #     """

    #     """
    #     Replace each word from replace_words in the given text and store the result in self.fixed_text.
    #     """
    #     self.fixed_text = text
    #     for wrong, correct in self.replace_words:
    #         self.fixed_text = self.fixed_text.replace(wrong, correct)

    #     split_chars = set(' -.?,!;:\"“”()[]{}|<>/+¿¡…—–♪♫„«»‹›؛،؟')
    #     self.stop = False
    #     for word in self.fixed_text.split():
    #         if (self.stop):
    #             break
    #         word = word.strip(''.join(split_chars))
    #         if not self.is_number(word):
    #             # if len(word) == 1 or not self.dictionary.lookup(word):
    #             if (word is '&'):
    #                 continue
    #             if (word in self.skipped_words):
    #                 self.logger.debug(f'word {word} skipped')
    #                 continue
    #             if not self.dictionary.lookup(word):
    #                 self.logger.debug(f'word {word} unknown')
    #                 yield word
    #                 # unknown_words.append(word)
    #     # return unknown_words

    # def Handle(self, spellCheckDialog: SpellCheckDialog):
    #     if (spellCheckDialog.state == SpellCheckDialog.SkipAll):
    #         self.logger.debug('Handle SkipAll')
    #         self.logger.debug(f'word {spellCheckDialog.word_line_edit.text()} added to skipped')
    #         self.skipped_words.append(spellCheckDialog.word_line_edit.text())
    #     elif (spellCheckDialog.state == SpellCheckDialog.ReplaceAll):
    #         self.logger.debug('Handle ReplaceAll')
    #         self.replace_words.append((spellCheckDialog.before_word, spellCheckDialog.word_line_edit.text()))
    #     elif (spellCheckDialog.state == SpellCheckDialog.EditAllText):
    #         self.logger.debug('Handle EditAllText')
    #         self.fixed_text = spellCheckDialog.text_edit.toPlainText()
    #         self.stop = True

    def GetUnknownWordsViaDictionaryFromList(self, words_with_objects: List) -> list:
        split_chars = set('!?,:.\"\'();')
        unknown_words = []
        for item_tuple in words_with_objects:
            text_content, textblock_obj = item_tuple # Unpack the tuple

            for word in text_content.split():
                word = word.strip(''.join(split_chars))

                if (word in self.skipped_words):
                    # self.logger.debug(f'word {word} skipped')
                    continue
                if self.is_number(word):
                    # self.logger.debug(f'number {word} skipped')
                    # unknown_words.append((word, textblock_obj))
                    continue
                    # if len(word) == 1 or not self.dictionary.lookup(word):
                try:
                    if not self.dictionary.lookup(word.lower()):
                        unknown_words.append((word, textblock_obj))
                except Exception as e:
                    unknown_words.append((word, textblock_obj))
                    print(f"spylls error: {e}")
        return unknown_words  

    def onWordDeleted(self, word: str):
        self.skipped_words.append(word)
        self._save_data()

    def reload_language(self, lang: str):
        """
        Reload dictionary and data for a different language at runtime.
        """
        self.logger.info(f"Reloading SpellCheckEngine language -> {lang}")
        self.lang = lang
        if self.lang == 'en':
            for files_download_kwargs in en_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/en/index')
        elif self.lang == 'fr':
            for files_download_kwargs in fr_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/fr/index')
        elif self.lang == 'it':
            for files_download_kwargs in it_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/it/index')
        elif self.lang == 'de':
            for files_download_kwargs in de_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/de/index')
        else:
            for files_download_kwargs in en_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/en/index')

        # update data file and reload data
        self.data_file = f"SpellCheckEngine_{self.lang}.json"
        self._load_data()

    def should_run(self) -> bool:
        try:
            from utils.config import pcfg
            return bool(pcfg.enable_spellcheck)
        except Exception:
            # if config not available, default to enabled
            return True

    def is_number(self, word):
        """
        Check if a word is known or a number.

        Args:
            word (str): The word to check.
            line (str): The line the word is from.
            word_skip_list (set): A set of words to skip.
            name_list (set): A set of names.
            name_list_uppercase (set): A set of uppercase names.
            name_list_obj: An object with an is_in_names_multi_word_list method.
            spell_check_word_lists: An object with a has_user_word method.

        Returns:
            bool: True if the word is known or a number, False otherwise.
        """
        if word.strip('\'').replace('$', '').replace('£', '').replace('¥', '').replace('¢', '').replace('.', '', 1).isdigit():
            return True

        return False

    # def is_word_known_or_number(word, line, word_skip_list, name_list, name_list_uppercase, name_list_obj, spell_check_word_lists):
    #     """
    #     Check if a word is known or a number.
    #
    #     Args:
    #         word (str): The word to check.
    #         line (str): The line the word is from.
    #         word_skip_list (set): A set of words to skip.
    #         name_list (set): A set of names.
    #         name_list_uppercase (set): A set of uppercase names.
    #         name_list_obj: An object with an is_in_names_multi_word_list method.
    #         spell_check_word_lists: An object with a has_user_word method.
    #
    #     Returns:
    #         bool: True if the word is known or a number, False otherwise.
    #     """
    #     if word.strip('\'').replace('$', '').replace('£', '').replace('¥', '').replace('¢', '').replace('.', '', 1).isdigit():
    #         return True
    #
    #     if word in word_skip_list:
    #         return True
    #
    #     if word.strip('\'') in name_list:
    #         return True
    #
    #     if word.strip('\'') in name_list_uppercase:
    #         return True
    #
    #     if spell_check_word_lists and spell_check_word_lists.has_user_word(word.lower()):
    #         return True
    #
    #     if spell_check_word_lists and spell_check_word_lists.has_user_word(word.strip('\'').lower()):
    #         return True
    #
    #     if len(word) > 2 and word in name_list_uppercase:
    #         return True
    #
    #     if len(word) > 2 and word in name_list_obj.name_list_with_apostrophe:
    #         return True
    #
    #     if name_list_obj and name_list_obj.is_in_names_multi_word_list(line, word):
    #         return True
    #
    #     return False