import logging
from difflib import SequenceMatcher
from typing import List, Set

from utils.textblock import TextBlock

LOGGER = logging.getLogger('BallonTranslator')


def _bbox_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0


def _text_similarity(text1: str, text2: str) -> float:
    t1 = text1.replace('\n', '')
    t2 = text2.replace('\n', '')
    return SequenceMatcher(None, t1, t2).ratio()


def deduplicate_blocks(
    blk_list: List[TextBlock],
    iou_threshold: float = 0.8,
    text_similarity_threshold: float = 0.85,
) -> List[TextBlock]:
    if len(blk_list) < 2:
        return blk_list

    to_remove: Set[int] = set()
    for i in range(len(blk_list) - 1):
        if i in to_remove:
            continue
        text_i = blk_list[i].get_text()
        if not text_i:
            continue
        j = i + 1
        if j in to_remove:
            continue
        text_j = blk_list[j].get_text()
        if not text_j:
            continue
        similarity = _text_similarity(text_i, text_j)
        # LOGGER.debug(f'deduplicate_blocks block: "{text_i[:50]}" "{text_j[:50]}" similarity={similarity}')
        if similarity < text_similarity_threshold:
            continue
        iou = _bbox_iou(blk_list[i].xyxy, blk_list[j].xyxy)
        if iou > iou_threshold:
            LOGGER.warning(
                f'Duplicate block detected: "{text_i[:50]}" '
                f'(IoU={iou:.2f}, similarity={similarity:.2f}). '
                f'Removing block #{j}, keeping #{i}.'
            )
            to_remove.add(j)
        # else:
        #     LOGGER.debug(f'deduplicate_blocks block: "{text_i[:50]}" (IoU={iou:.2f}, similarity={similarity:.2f})')


    if not to_remove:
        return blk_list

    return [blk for idx, blk in enumerate(blk_list) if idx not in to_remove]
