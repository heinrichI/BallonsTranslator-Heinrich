import sys, os, importlib.util
# Load garbage_detection directly by file path to avoid pulling in heavy project dependencies
_mod_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "modules", "ocr", "utils", "garbage_detection.py"
)
_spec = importlib.util.spec_from_file_location("garbage_detection", _mod_path)
_gd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gd)
_is_valid_onomatopoeia = _gd._is_valid_onomatopoeia
is_garbage_text = _gd.is_garbage_text

import pytest


class TestIsValidOnomatopoeia:
    """Test the onomatopoeia detection helper."""

    def test_french_non(self):
        assert _is_valid_onomatopoeia("NON! NON! NON!") == "NON"

    def test_boom(self):
        assert _is_valid_onomatopoeia("BOOM! BOOM! BOOM!") == "BOOM"

    def test_bam(self):
        assert _is_valid_onomatopoeia("BAM BAM BAM") == "BAM"

    def test_zap(self):
        assert _is_valid_onomatopoeia("ZAP! ZAP! ZAP!") == "ZAP"

    def test_whoosh(self):
        assert _is_valid_onomatopoeia("WHOOSH WHOOSH WHOOSH") == "WHOOSH"

    def test_single_char_repeat(self):
        """AAAAA has vowel A but only 1 unique char — not a real word."""
        assert _is_valid_onomatopoeia("AAAAA AAAAA AAAAA") is None

    def test_no_vowel(self):
        """ZZZ has no vowels — not a real word."""
        assert _is_valid_onomatopoeia("ZZZ ZZZ ZZZ") is None

    def test_brackets_not_alpha(self):
        assert _is_valid_onomatopoeia("[n][n][n][n]") is None

    def test_emoji_not_alpha(self):
        assert _is_valid_onomatopoeia("🌳🌳🌳🌳") is None

    def test_musical_notes_not_alpha(self):
        assert _is_valid_onomatopoeia("♪♪♪♪") is None

    def test_normal_text_no_repeat(self):
        assert _is_valid_onomatopoeia("Hello, how are you today?") is None

    def test_too_long_unit(self):
        """Unit >6 chars is not a short SFX word."""
        assert _is_valid_onomatopoeia("CRASHING CRASHING CRASHING") is None

    def test_m_with_no_vowel(self):
        assert _is_valid_onomatopoeia("M M M M M") is None

    def test_multiline_non(self):
        """Real-world case from logs."""
        unit = _is_valid_onomatopoeia("AH N...NOOON!\nNON! NON! NON!\nNON!... NNNOON!")
        assert unit is not None

    def test_case_insensitive_vowel(self):
        assert _is_valid_onomatopoeia("NON! NON! NON!") == "NON"


class TestIsGarbageText:
    """Test the main garbage detection function."""

    def test_empty_text(self):
        assert is_garbage_text("") is False
        assert is_garbage_text(None) is False

    def test_short_text_not_flagged(self):
        assert is_garbage_text("NON! NON!") is False  # below min_len=18

    def test_normal_english(self):
        assert is_garbage_text("HEY, KIDS! I FIGURED, IF I CAN'T BRING THE BEACH CROWD TO ME") is False

    def test_single_char_dominance(self):
        assert is_garbage_text("A" * 50) is True

    def test_emoji_repeat(self):
        assert is_garbage_text("🌳" * 30) is True

    def test_bracket_repeat(self):
        assert is_garbage_text("[n]" * 25) is True

    def test_musical_note_repeat(self):
        assert is_garbage_text("♪" * 40) is True

    def test_no_vowel_repeat(self):
        assert is_garbage_text("ZZZZZZZZZZZZZZZZZZZZ") is True

    def test_french_non_ondatopoeia_allowed(self):
        """The real-world false positive from logs."""
        assert is_garbage_text("AH N...NOOON!\nNON! NON! NON!\nNON!... NNNOON!") is False

    def test_boom_ondatopoeia_allowed(self):
        assert is_garbage_text("BOOM! BOOM! BOOM! BOOM! BOOM! BOOM! BOOM! BOOM! BOOM! BOOM!") is False

    def test_bam_ondatopoeia_allowed(self):
        assert is_garbage_text("BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM BAM") is False

    def test_low_diversity_garbage(self):
        """30+ chars with ≤4 unique chars, no SFX pattern -> garbage."""
        assert is_garbage_text("ABABABABABABABABABABABABABABABAB") is True

    def test_top3_concentration_garbage(self):
        """Top-3 chars cover >75% with no SFX -> garbage."""
        assert is_garbage_text("ABABABABABABABABABABABABABABABABABABABAB") is True

    def test_repeated_pattern_garbage(self):
        """1-6 char non-alphabetic pattern repeated 20+ times."""
        assert is_garbage_text("[n] " * 25) is True

    def test_m_only_no_vowel(self):
        """M-only text has no vowels -> garbage."""
        assert is_garbage_text("M MMM M MM MMM M MM MMM M MM MMM M MM") is True

    def test_logger_receives_warnings(self):
        """Logger gets called when garbage is detected."""
        import logging
        logger = logging.getLogger("test")
        assert is_garbage_text("A" * 50, logger=logger) is True

    def test_zap_allowed(self):
        assert is_garbage_text("ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP! ZAP!") is False

    def test_whoosh_allowed(self):
        assert is_garbage_text("WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH WHOOSH") is False

    def test_custom_min_len(self):
        """Shorter min_len should still allow valid SFX."""
        short_sfx = "NON! NON! NON!"  # 15 chars, below default 18
        assert is_garbage_text(short_sfx, min_len=10) is False
