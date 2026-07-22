import pytest
from utils.textblock import TextBlock
from utils.block_dedup import _bbox_iou, _text_similarity, deduplicate_blocks


def _make_block(text: str, xyxy: list) -> TextBlock:
    blk = TextBlock(xyxy=xyxy)
    blk.text = [text] if text else []
    return blk


class TestBboxIou:
    def test_identical_boxes(self):
        assert _bbox_iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0

    def test_no_overlap(self):
        assert _bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0

    def test_partial_overlap(self):
        iou = _bbox_iou([0, 0, 100, 100], [50, 50, 150, 150])
        assert 0.1 < iou < 0.2

    def test_one_inside_another(self):
        iou = _bbox_iou([0, 0, 100, 100], [10, 10, 90, 90])
        assert iou > 0.5


class TestTextSimilarity:
    def test_identical(self):
        assert _text_similarity("hello", "hello") == 1.0

    def test_completely_different(self):
        assert _text_similarity("aaa", "zzz") < 0.5

    def test_similar(self):
        assert _text_similarity("HE DIDN'T", "HE DIDNT") > 0.8

    def test_newlines_stripped(self):
        assert _text_similarity("HE\nDIDN'T", "HE\nDIDN'T") == 1.0
        assert _text_similarity("HE\nDIDN'T", "HE DIDN'T") > 0.8


class TestDeduplicateBlocks:
    def test_single_block_returned(self):
        blk = _make_block("hello", [0, 0, 100, 100])
        assert deduplicate_blocks([blk]) == [blk]

    def test_empty_list(self):
        assert deduplicate_blocks([]) == []

    def test_exact_duplicates_removed(self):
        b1 = _make_block("HELLO", [0, 0, 100, 100])
        b2 = _make_block("HELLO", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 1
        assert result[0] is b1

    def test_fuzzy_duplicates_removed(self):
        b1 = _make_block("HE DIDN'T MEAN TO", [0, 0, 200, 50])
        b2 = _make_block("HE DIDNT MEAN TO", [0, 0, 200, 50])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 1

    def test_different_texts_kept(self):
        b1 = _make_block("HELLO", [0, 0, 100, 100])
        b2 = _make_block("WORLD", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 2

    def test_same_text_different_position_kept(self):
        b1 = _make_block("HELLO", [0, 0, 100, 100])
        b2 = _make_block("HELLO", [500, 500, 600, 600])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 2

    def test_empty_text_skipped(self):
        b1 = _make_block("", [0, 0, 100, 100])
        b2 = _make_block("HELLO", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 2

    def test_three_blocks_adjacent_only(self):
        b1 = _make_block("TEST", [0, 0, 100, 100])
        b2 = _make_block("TEST", [0, 0, 100, 100])
        b3 = _make_block("TEST", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2, b3])
        assert len(result) == 2
        assert result[0] is b1
        assert result[1] is b3

    def test_newlines_in_text_detected(self):
        b1 = _make_block("HE\nDIDN'T", [0, 0, 100, 100])
        b2 = _make_block("HE DIDN'T", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2])
        assert len(result) == 1

    def test_non_adjacent_not_compared(self):
        b1 = _make_block("HELLO", [0, 0, 100, 100])
        b2 = _make_block("WORLD", [0, 0, 100, 100])
        b3 = _make_block("HELLO", [0, 0, 100, 100])
        result = deduplicate_blocks([b1, b2, b3])
        assert len(result) == 3
