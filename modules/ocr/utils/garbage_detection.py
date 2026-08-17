"""OCR garbage detection with onomatopoeia awareness.

Detects degenerate OCR output (repetitive, low-entropy) while allowing
valid comic sound effects like "NON! NON! NON!", "BOOM! BOOM!", "BAM BAM".
"""

import re
from collections import Counter


def _is_valid_onomatopoeia(text):
    """Check if text contains a repeating short word with vowels (valid comic SFX).
    Returns the repeating word if valid, None otherwise.

    Valid: "NON! NON! NON!" -> "NON", "BOOM! BOOM!" -> "BOOM"
    Invalid: "AAAAA" (single char repeated), "[n][n][n]" (not alpha), "🌳🌳" (not alpha)
    """
    # Match: word(3-6 letters) + (separator + same_word){2+}
    # The separator [^A-Za-z]* absorbs punctuation/spaces/newlines between repetitions
    # {3,6} enforces min length in the regex itself so degenerate single-char repeats
    # (like "OOO" in "NOOON") are skipped and the engine finds the real word later
    m = re.search(r'([A-Za-z]{3,6})(?:[^A-Za-z]*\1){2,}', text)
    if not m:
        return None
    word = m.group(1)
    # Must be a real short word: 3-6 letters, at least one vowel, >=2 unique chars
    if len(word) < 3 or len(word) > 6:
        return None
    if not any(c.lower() in 'aeiou' for c in word):
        return None
    unique = set(word.lower())
    if len(unique) <= 1:
        return None
    # Internal repetition check: if word is mostly repeating sub-patterns (e.g. "ABABAB"), reject
    if len(word) / len(unique) > 2.0:
        return None
    return word


def is_garbage_text(text, min_len=18, logger=None):
    """Check if OCR output is degenerate garbage.
    Returns True if garbage, False if valid text.
    Logger is optional — used for warning messages when garbage is detected.
    """
    if not text:
        return False

    # Remove whitespace to analyze actual characters
    clean_text = "".join(text.split())
    if len(clean_text) < min_len:
        return False

    counts = Counter(clean_text)
    most_common = counts.most_common(1)
    char, count = most_common[0]
    unique_count = len(counts)

    # Detect repeating onomatopoeia early
    sfx_word = _is_valid_onomatopoeia(text)

    # 1. Single character dominance (>60%)
    if count / len(clean_text) > 0.6:
        if sfx_word is None:
            if logger:
                logger.warning("Flagged: Single character dominance")
            return True

    # 2. Low diversity (≤4 unique chars in 30+ text)
    if len(clean_text) > 30 and unique_count <= 4:
        if sfx_word is None:
            if logger:
                logger.warning(f"Flagged: Low character diversity ({unique_count} unique chars)")
            return True

    # 3. Top-3 char concentration (>75%)
    if len(clean_text) > 30:
        top3_count = sum(c for _, c in counts.most_common(3))
        top3_ratio = top3_count / len(clean_text)
        if top3_ratio > 0.75:
            if sfx_word is None:
                if logger:
                    logger.warning(f"Flagged: Top-3 chars cover {top3_ratio:.0%} of text ({counts.most_common(3)})")
                return True

    # 4. Repeated short pattern (1-6 char sequence repeated 20+ times)
    if re.search(r'(.{1,6})\s*(\1[\s]*){19,}', text):
        if sfx_word is None:
            if logger:
                logger.warning("Flagged: Repeated short pattern")
            return True

    return False
