"""
HuggingFace object-detection text detector for ogkalu/comic-text-and-bubble-detector.

Labels: bubble, text_bubble, text_free (SFX/captions outside bubbles).
All three are treated as text regions and produce TextBlocks.
"""

import copy
import os.path as osp
from typing import Tuple, List

import numpy as np
import cv2

from .base import register_textdetectors, TextDetectorBase, TextBlock, DEVICE_SELECTOR
from utils.textblock import sort_regions

try:
    from transformers import pipeline
    import torch
    from PIL import Image as PILImage
    _HF_AVAILABLE = True
except ImportError:
    _HF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Box helpers
# ---------------------------------------------------------------------------

def _iou_xyxy(a, b):
    """Intersection-over-union for two boxes [x1, y1, x2, y2]."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _clip_blocks_to_page(blk_list, img_w, img_h):
    """Clamp every block's xyxy and lines to [0, img_w] x [0, img_h]."""
    if not blk_list or img_w <= 0 or img_h <= 0:
        return blk_list
    out = []
    for blk in blk_list:
        x1, y1, x2, y2 = blk.xyxy
        try:
            x1 = max(0, min(int(round(float(x1))), img_w - 1))
            x2 = max(0, min(int(round(float(x2))), img_w))
            y1 = max(0, min(int(round(float(y1))), img_h - 1))
            y2 = max(0, min(int(round(float(y2))), img_h))
        except (TypeError, ValueError):
            out.append(blk)
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        new_blk = copy.copy(blk)
        new_blk.xyxy = [x1, y1, x2, y2]
        if getattr(blk, "lines", None) and len(blk.lines) > 0:
            try:
                pts = np.array(blk.lines[0], dtype=np.float64)
                if pts.ndim == 2 and pts.shape[0] >= 3 and pts.shape[1] >= 2:
                    pts[:, 0] = np.clip(pts[:, 0], 0, img_w - 1)
                    pts[:, 1] = np.clip(pts[:, 1], 0, img_h - 1)
                    new_blk.lines = [pts.astype(np.int32).tolist()]
                else:
                    new_blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
            except (TypeError, ValueError, IndexError):
                new_blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
        else:
            new_blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
        out.append(new_blk)
    return out


def _merge_overlapping_blocks(blk_list, iou_threshold):
    """Merge text blocks overlapping with IoU >= threshold or containment."""
    if not blk_list or iou_threshold <= 0:
        return blk_list
    blks = list(blk_list)
    while True:
        merged_any = False
        for i in range(len(blks)):
            for j in range(i + 1, len(blks)):
                a, b = blks[i], blks[j]
                iou = _iou_xyxy(a.xyxy, b.xyxy)
                if iou >= iou_threshold:
                    x1 = min(a.xyxy[0], b.xyxy[0])
                    y1 = min(a.xyxy[1], b.xyxy[1])
                    x2 = max(a.xyxy[2], b.xyxy[2])
                    y2 = max(a.xyxy[3], b.xyxy[3])
                    pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)
                    font_size = max(
                        getattr(a, "_detected_font_size", 12),
                        getattr(b, "_detected_font_size", 12),
                    )
                    merged = TextBlock(xyxy=[x1, y1, x2, y2], lines=[pts.tolist()])
                    merged._detected_font_size = font_size
                    blks = [bx for k, bx in enumerate(blks) if k != i and k != j] + [merged]
                    merged_any = True
                    break
            if merged_any:
                break
        if not merged_any:
            break
    return blks


def _expand_blocks(blk_list, pad, w, h):
    """Expand each block by `pad` pixels on all sides, clipped to image."""
    if pad <= 0:
        return blk_list
    out = []
    for blk in blk_list:
        x1, y1, x2, y2 = blk.xyxy
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad)
        y2 = min(h, y2 + pad)
        if x2 <= x1 or y2 <= y1:
            out.append(blk)
            continue
        new_blk = copy.copy(blk)
        new_blk.xyxy = [x1, y1, x2, y2]
        new_blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
        out.append(new_blk)
    return out


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------

@register_textdetectors("comic-text-and-bubble-detector")
class ComicTextAndBubbleDetector(TextDetectorBase):
    """
    HuggingFace object-detection based detector.
    Default model: ogkalu/comic-text-and-bubble-detector (RT-DETRv2).
    Labels: bubble, text_bubble, text_free — all kept as text regions.
    """

    params = {
        "model_id": {
            "type": "line_editor",
            "value": "ogkalu/comic-text-and-bubble-detector",
            "description": "HuggingFace model id (e.g. ogkalu/comic-text-and-bubble-detector)",
        },
        "confidence threshold": {
            "type": "line_editor",
            "value": 0.3,
            "description": "Min detection score (0.2–0.5).",
        },
        "box_padding": {
            "type": "line_editor",
            "value": 3,
            "description": "Pixels to expand boxes (reduces clipped punctuation).",
        },
        "font size multiplier": {
            "type": "line_editor",
            "value": 1.0,
        },
        "font size max": {
            "type": "line_editor",
            "value": -1,
        },
        "font size min": {
            "type": "line_editor",
            "value": -1,
        },
        "mask dilate size": {
            "type": "line_editor",
            "value": 2,
        },
        "device": DEVICE_SELECTOR(),
        "description": "HF object-detection (ogkalu). pip install transformers torch",
    }

    _load_model_keys = {"pipe"}

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.pipe = None
        self._model_id = None
        self._device = None

    def _resolve_model_ref(self, model_id: str) -> str:
        """Resolve model_id: if it's a relative path, try repo root."""
        s = (model_id or "").strip()
        if not s:
            return s
        if osp.isfile(s) or osp.isdir(s):
            return s
        root = osp.abspath(osp.join(osp.dirname(osp.abspath(__file__)), "..", ".."))
        candidate = osp.normpath(osp.join(root, s))
        if osp.isfile(candidate) or osp.isdir(candidate):
            return candidate
        return s

    def _load_model(self):
        if not _HF_AVAILABLE:
            self.logger.warning(
                "transformers/pillow not installed. "
                "Install: pip install transformers torch pillow"
            )
            self.pipe = None
            return

        model_id = (self.params.get("model_id") or {}).get(
            "value", "ogkalu/comic-text-and-bubble-detector"
        )
        if not model_id or not isinstance(model_id, str):
            model_id = "ogkalu/comic-text-and-bubble-detector"
        model_id = model_id.strip()

        device = (self.params.get("device") or {}).get("value", "cpu")
        if device == "gpu":
            device = "cuda"
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"

        if self.pipe is not None and self._model_id == model_id and self._device == device:
            return

        model_ref = self._resolve_model_ref(model_id)
        device_id = 0 if device == "cuda" else -1

        try:
            self.pipe = pipeline(
                "object-detection",
                model=model_ref,
                device=device_id,
            )
            self._model_id = model_id
            self._device = device
            self.logger.info("Loaded HF object-detection model: %s on %s", model_ref, device)
        except Exception as e:
            self.logger.warning("Failed to load HF model %s: %s", model_ref, e)
            self.pipe = None

    def _detect(self, img: np.ndarray, proj=None) -> Tuple[np.ndarray, List[TextBlock]]:
        if not _HF_AVAILABLE or self.pipe is None:
            h, w = img.shape[:2]
            return np.zeros((h, w), dtype=np.uint8), []

        # Ensure 3-channel RGB
        if img.ndim == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
        elif img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)

        h, w = img.shape[:2]

        # Parse params
        conf_thr = 0.3
        try:
            conf_thr = max(0.0, min(1.0, float(
                (self.params.get("confidence threshold") or {}).get("value", 0.3)
            )))
        except (TypeError, ValueError):
            pass

        pad_val = 3
        try:
            pad_val = max(0, min(24, int(
                (self.params.get("box_padding") or {}).get("value", 3) or 0
            )))
        except (TypeError, ValueError):
            pass

        # Run inference
        try:
            pil_img = PILImage.fromarray(img)
            results = self.pipe(pil_img)
        except Exception as e:
            self.logger.warning("HF object-detection inference failed: %s", e)
            return np.zeros((h, w), dtype=np.uint8), []

        blk_list = []
        for item in results if results else []:
            if not isinstance(item, dict):
                continue
            score = item.get("score", 0)
            if score < conf_thr:
                continue
            box = item.get("box")
            if not box:
                continue
            x1 = int(box.get("xmin", 0))
            y1 = int(box.get("ymin", 0))
            x2 = int(box.get("xmax", 0))
            y2 = int(box.get("ymax", 0))
            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)
            blk = TextBlock(xyxy=[x1, y1, x2, y2], lines=[pts.tolist()])
            blk._detected_font_size = max(y2 - y1, 12)
            blk_list.append(blk)

        # Merge overlapping blocks
        blk_list = _merge_overlapping_blocks(blk_list, 0.35)

        # Box padding
        if pad_val > 0:
            blk_list = _expand_blocks(blk_list, pad_val, w, h)

        # Sort by reading order
        blk_list = sort_regions(blk_list)

        # Clip to page
        blk_list = _clip_blocks_to_page(blk_list, w, h)

        # Build mask
        mask = np.zeros((h, w), dtype=np.uint8)
        for blk in blk_list:
            drawn = False
            if getattr(blk, "lines", None) and len(blk.lines) > 0:
                for line in blk.lines:
                    try:
                        pts = np.array(line, dtype=np.int32)
                        if pts.ndim == 2 and pts.shape[0] >= 3 and pts.shape[1] == 2:
                            pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
                            pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
                            cv2.fillPoly(mask, [pts], 255)
                            drawn = True
                    except (TypeError, ValueError, IndexError):
                        pass
            if not drawn:
                x1, y1, x2, y2 = blk.xyxy
                pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)
                cv2.fillPoly(mask, [pts], 255)

        # Font size post-processing
        fnt_rsz = 1.0
        try:
            fnt_rsz = float(
                (self.params.get("font size multiplier") or {}).get("value", 1.0)
            )
        except (TypeError, ValueError):
            pass
        fnt_max = -1
        try:
            fnt_max = int(
                (self.params.get("font size max") or {}).get("value", -1)
            )
        except (TypeError, ValueError):
            pass
        fnt_min = -1
        try:
            fnt_min = int(
                (self.params.get("font size min") or {}).get("value", -1)
            )
        except (TypeError, ValueError):
            pass

        for blk in blk_list:
            sz = blk._detected_font_size * fnt_rsz
            if fnt_max > 0:
                sz = min(fnt_max, sz)
            if fnt_min > 0:
                sz = max(fnt_min, sz)
            blk.font_size = sz
            blk._detected_font_size = sz

        # Mask dilate
        ksize = 2
        try:
            ksize = int(
                (self.params.get("mask dilate size") or {}).get("value", 2)
            )
        except (TypeError, ValueError):
            pass
        if ksize > 0:
            element = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (2 * ksize + 1, 2 * ksize + 1), (ksize, ksize)
            )
            mask = cv2.dilate(mask, element)

        return mask, blk_list

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if param_key in ("model_id", "device"):
            self.pipe = None
            self._model_id = None
            self._device = None