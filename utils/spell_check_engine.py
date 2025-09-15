from ui.SpellCheckDialog import SpellCheckDialog
from spylls.hunspell.dictionary import Dictionary
from utils.logger import logger as LOGGER
from typing import Dict, List, Union
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

class SpellCheckEngine:
    def __init__(self, lang = 'en') -> None:
    # def __init__(self, local_no: int, start: int, end: int) -> None:
        # self.local_no = local_no
        # self.start = start
        # self.end = end
        self.logger = LOGGER

        # download https://github.com/wooorm/dictionaries/tree/main/dictionaries/it

        if lang == 'en':
            for files_download_kwargs in en_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/en/index')
        elif lang == 'fr':
            for files_download_kwargs in fr_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/fr/index')
        elif lang == 'it':
            for files_download_kwargs in it_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/it/index')
        elif lang == 'de':
            for files_download_kwargs in de_flist:
                download_and_check_files(**files_download_kwargs)
            self.dictionary = Dictionary.from_files('data/spellcheck/de/index')
        
        # import pathlib
        # path = pathlib.Path(__file__).parent  / 'en_US'
        # dictionary = Dictionary.from_files(str(path))

        # Define the path for saving/loading data
        self.data_file = f"SpellCheckEngine_{lang}.json"
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

    #     split_chars = set(' -.?,!;:\"“”()[]{}|<>/+¿¡…—–♪♫„«»‹›؛،؟\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B\u200E\u200F\u2028\u2029\u202A\u202B\u202C\u202D\u202E\u202F\u3000\uFEFF')
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
                    self.logger.debug(f'word {word} skipped')
                    continue
                if self.is_number(word):
                    self.logger.debug(f'number {word} skipped')
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

    # def GetUnknownWordsViaDictionary(self, text: str) -> list:
    #     split_chars = set(' -.?,!;:\"“”()[]{}|<>/+¿¡…—–♪♫„«»‹›؛،؟\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B\u200E\u200F\u2028\u2029\u202A\u202B\u202C\u202D\u202E\u202F\u3000\uFEFF')
    #     unknown_words = []
    #     for word in text.split():
    #         word = word.strip(''.join(split_chars))
    #         if not self.is_number(word):
    #             # if len(word) == 1 or not self.dictionary.lookup(word):
    #             if not self.dictionary.lookup(word):
    #                 unknown_words.append(word)
    #     return unknown_words

    # def CountUnknownWordsViaDictionary(self, text: str) -> int:
    #     split_chars = set(' -.?,!;:\"“”()[]{}|<>/+¿¡…—–♪♫„«»‹›؛،؟\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B\u200E\u200F\u2028\u2029\u202A\u202B\u202C\u202D\u202E\u202F\u3000\uFEFF')
    #     for word in text.split():
    #         word = word.strip(''.join(split_chars))
    #         if not self.is_word_known_or_number2(word):
    #             # dictionary.lookup(word)
    #             # print(dictionary.lookup('spylls'))
    #             # False
    #             # for suggestion in dictionary.suggest('spylls'):
    #                 # print(suggestion)
    #             correct = len(word) > 1 and dictionary.lookup(word)
    #             # if not correct:
    #             #     correct = len(word) > 2 and hunspell.spell(word.strip('\''))

    #             # if not correct and len(word) == 1 and three_letter_iso_language_name == 'eng' and word in ['I', 'A', 'a']:
    #             #     correct = True

    #             if correct:
    #                 number_of_correct_words += 1
    #             else:
    #                 words_not_found += 1
    #         elif len(word) > 3:
    #             number_of_correct_words += 1

    # def CountUnknownWordsViaDictionary(pattern: re.Pattern, text: str) -> Tuple[int, Dict]:
    # def count_unknown_words_via_dictionary(line, hunspell, three_letter_iso_language_name, word_skip_list, name_list, name_list_uppercase, name_list_obj, spell_check_word_lists):
    #     """
    #     Count the number of unknown words in a line using a dictionary.

    #     Args:
    #         line (str): The line to check.
    #         hunspell: A hunspell object.
    #         three_letter_iso_language_name (str): The three letter ISO language name.
    #         word_skip_list (set): A set of words to skip.
    #         name_list (set): A set of names.
    #         name_list_uppercase (set): A set of uppercase names.
    #         name_list_obj: An object with an is_in_names_multi_word_list method.
    #         spell_check_word_lists: An object with a has_user_word method.

    #     Returns:
    #         int: The number of unknown words.
    #     """
    #     number_of_correct_words = 0
    #     if not hunspell:
    #         return 0

    #     min_length = 2
    #     if True:  # Replace with your configuration
    #         min_length = 1

    #     words_not_found = 0
    #     split_chars = set(' -.?,!;:\"“”()[]{}|<>/+¿¡…—–♪♫„«»‹›؛،؟\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B\u200E\u200F\u2028\u2029\u202A\u202B\u202C\u202D\u202E\u202F\u3000\uFEFF')
    #     words = remove_open_close_tags(line, 'i').split()
    #     for word in words:
    #         word = word.strip(''.join(split_chars))
    #         if len(word) >= min_length:
    #             if not is_word_known_or_number(word, line, word_skip_list, name_list, name_list_uppercase, name_list_obj, spell_check_word_lists):
    #                 correct = len(word) > 1 and hunspell.spell(word)
    #                 if not correct:
    #                     correct = len(word) > 2 and hunspell.spell(word.strip('\''))

    #                 if not correct and len(word) == 1 and three_letter_iso_language_name == 'eng' and word in ['I', 'A', 'a']:
    #                     correct = True

    #                 if correct:
    #                     number_of_correct_words += 1
    #                 else:
    #                     words_not_found += 1
    #             elif len(word) > 3:
    #                 number_of_correct_words += 1

    #     return words_not_found, number_of_correct_words

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

    #     Args:
    #         word (str): The word to check.
    #         line (str): The line the word is from.
    #         word_skip_list (set): A set of words to skip.
    #         name_list (set): A set of names.
    #         name_list_uppercase (set): A set of uppercase names.
    #         name_list_obj: An object with an is_in_names_multi_word_list method.
    #         spell_check_word_lists: An object with a has_user_word method.

    #     Returns:
    #         bool: True if the word is known or a number, False otherwise.
    #     """
    #     if word.strip('\'').replace('$', '').replace('£', '').replace('¥', '').replace('¢', '').replace('.', '', 1).isdigit():
    #         return True

    #     if word in word_skip_list:
    #         return True

    #     if word.strip('\'') in name_list:
    #         return True

    #     if word.strip('\'') in name_list_uppercase:
    #         return True

    #     if spell_check_word_lists and spell_check_word_lists.has_user_word(word.lower()):
    #         return True

    #     if spell_check_word_lists and spell_check_word_lists.has_user_word(word.strip('\'').lower()):
    #         return True

    #     if len(word) > 2 and word in name_list_uppercase:
    #         return True

    #     if len(word) > 2 and word in name_list_obj.name_list_with_apostrophe:
    #         return True

    #     if name_list_obj and name_list_obj.is_in_names_multi_word_list(line, word):
    #         return True

    #     return False


    # def remove_open_close_tags(source, *tags):
    #     """
    #     Remove all of the specified opening and closing tags from the source HTML string.

    #     Args:
    #         source (str): The source string to search for specified HTML tags.
    #         tags (str): The HTML tags to remove.

    #     Returns:
    #         str: A new string without the specified opening and closing tags.
    #     """
    #     if not source or '<' not in source:
    #         return source

    #     pattern = r'<\s*\/?(\w+)[^>]*>'
    #     return re.sub(pattern, lambda m: '' if m.group(1).lower() in [tag.lower() for tag in tags] else m.group(0), source)

    # REGEX_ALONE_IAS_L = re.compile(r"\bl\b", re.IGNORECASE)
    # REGEX_LOWERCASE_L = re.compile(r"[A-ZÆØÅÄÖÉÈÀÙÂÊÎÔÛËÏ]l[A-ZÆØÅÄÖÉÈÀÙÂÊÎÔÛËÏ]", re.IGNORECASE)
    # REGEX_UPPERCASE_I = re.compile(r"[a-zæøåöääöéèàùâêîôûëï]I\.", re.IGNORECASE)
    # REGEX_NUMBER1 = re.compile(r"(?<=\d) 1(?!/\d)", re.IGNORECASE)

    # def count_unknown_words_via_dictionary(line, out_numberOfCorrectWords):
    #     out_numberOfCorrectWords = 0
    #     if _hunspell is None:
    #         return 0

    #     minLength = 2
    #     if Configuration.Settings.Tools.CheckOneLetterWords:
    #         minLength = 1

    #     wordsNotFound = 0
    #     words = HtmlUtil.remove_open_close_tags(line, HtmlUtil.TagItalic).split(" \r\n\t")
    #     for i in range(len(words)):
    #         word = words[i].strip(SpellCheckWordLists.SplitChars)
    #         if len(word) >= minLength:
    #             if not is_word_known_or_number(word, line):
    #                 correct = len(word) > 1 and _hunspell.spell(word)
    #                 if not correct:
    #                     correct = len(word) > 2 and _hunspell.spell(word.replace("'", ""))
    #                 if not correct and len(word) == 1 and _threeLetterIsoLanguageName == "eng" and (word == "I" or word == "A" or word == "a"):
    #                     correct = True
    #                 if correct:
    #                     out_numberOfCorrectWords += 1
    #                 else:
    #                     wordsNotFound += 1
    #             elif len(word) > 3:
    #                 out_numberOfCorrectWords += 1

    #     return wordsNotFound

    # def remove_open_close_tags(source, tags):
    #     if not source or '<' not in source:
    #         return source

    #     # This pattern matches these tag formats:
    #     # <tag*>
    #     # < tag*>
    #     # </tag*>
    #     # < /tag*>
    #     # </ tag*>
    #     # < / tag*>
    #     return re.sub(r'<(\w+)>.*?</\1>', '', source, flags=re.IGNORECASE)

    # ... (rest of the code)

    # def is_word_known_or_number(word, line):
    #     if re.match(r'^\d+(?:\.\d+)?$', word):
    #         return True

    #     if word in _wordSkipList:
    #         return True

    #     if word.strip("'") in _nameList:
    #         return True

    #     if word.strip("'").upper() in _nameListUppercase:
    #         return True

    #     if _spellCheckWordLists is not None and word.lower() in _spellCheckWordLists.user_words:
    #         return True

    #     if _spellCheckWordLists is not None and word.strip("'").lower() in _spellCheckWordLists.user_words:
    #         return True

    #     if len(word) > 2 and word.upper() in _nameListUppercase:
    #         return True

    #     if len(word) > 2 and word in _nameListWithApostrophe:
    #         return True

    #     if _nameListObj is not None and _nameListObj.is_in_names_multi_word_list(line, word):
    #         return True

    #     return False
