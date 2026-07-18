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
import json
from pathlib import Path
from datetime import datetime

from .base import register_textdetectors, TextDetectorBase, TextBlock, DEVICE_SELECTOR
from utils.textblock import sort_regions
from .ctd.textmask import refine_mask
from .detector_ctd import ComicTextDetector

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


def _merge_overlapping_blocks(blk_list, iou_threshold, max_area=None):
    """Merge text blocks overlapping with IoU >= threshold or containment.

    If max_area is provided (in pixels) any candidate merge producing a merged
    box with area > max_area will be skipped. This prevents creating huge
    merged blocks that later cause refine_mask to expand into background.
    """
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
                    merged_area = max(0, (x2 - x1)) * max(0, (y2 - y1))
                    if max_area is not None and merged_area > int(max_area):
                        # skip this merge to avoid producing an excessively large block
                        continue
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
    """
    Expand each block by `pad` pixels on all sides, clipped to image.

    Cap per-block padding to a fraction of block height to avoid excessive
    growth for very large merged boxes (which causes refine_mask to include
    background art).
    """
    if pad <= 0:
        return blk_list
    out = []
    for blk in blk_list:
        x1, y1, x2, y2 = blk.xyxy
        bh = max(1, int(y2 - y1))
        # allow padding up to 15% of block height (rounded)
        max_pad = int(round(bh * 0.15))
        use_pad = min(pad, max_pad) if max_pad > 0 else 0
        if use_pad <= 0:
            out.append(blk)
            continue
        nx1 = max(0, x1 - use_pad)
        ny1 = max(0, y1 - use_pad)
        nx2 = min(w, x2 + use_pad)
        ny2 = min(h, y2 + use_pad)
        if nx2 <= nx1 or ny2 <= ny1:
            out.append(blk)
            continue
        new_blk = copy.copy(blk)
        new_blk.xyxy = [nx1, ny1, nx2, ny2]
        new_blk.lines = [[[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]]]
        out.append(new_blk)
    return out


def _validate_detection_item(item) -> bool:
    """Quick validation for HF pipeline detection item."""
    if not isinstance(item, dict):
        return False
    # must have a numeric score
    score = item.get("score")
    if score is None:
        return False
    try:
        float(score)
    except Exception:
        return False
    # box or bbox should exist in some form; detailed parsing done in _safe_box_from_item
    if item.get("box") is None and item.get("bbox") is None and item.get("bounding_box") is None:
        # still allow: some pipelines may omit explicit box field (rare)
        return True
    return True


def _safe_box_from_item(item, img_w, img_h):
    """
    Robustly extract pixel xyxy coordinates from various HF pipeline box formats.
    Returns (x1, y1, x2, y2) or None on failure.
    Accepts:
      - box dict with xmin/ymin/xmax/ymax or x1/y1/x2/y2 or left/top/right/bottom
      - box dict with left/top/width/height
      - bbox/list/tuple in [x1,y1,x2,y2] or [x,y,w,h] in pixels or normalized (0..1)
    """
    try:
        box = item.get("box") or item.get("bbox") or item.get("bounding_box")
        x1 = y1 = x2 = y2 = None
        if isinstance(box, dict):
            # common dict keys
            x1 = box.get("xmin", box.get("x1", box.get("left")))
            y1 = box.get("ymin", box.get("y1", box.get("top")))
            x2 = box.get("xmax", box.get("x2", box.get("right")))
            y2 = box.get("ymax", box.get("y2", box.get("bottom")))
            if x2 is None or y2 is None:
                # try width/height variant
                w_box = box.get("width", box.get("w"))
                h_box = box.get("height", box.get("h"))
                if x1 is not None and y1 is not None and w_box is not None and h_box is not None:
                    x2 = float(x1) + float(w_box)
                    y2 = float(y1) + float(h_box)
                else:
                    return None
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
            x2 = int(round(float(x2)))
            y2 = int(round(float(y2)))
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            a, b, c, d = box
            a = float(a); b = float(b); c = float(c); d = float(d)
            # normalized coordinates (0..1)
            if 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 and 0.0 <= c <= 1.0 and 0.0 <= d <= 1.0:
                # decide between [x1,y1,x2,y2] and [x,y,w,h]
                if c > a and d > b:
                    x1 = int(round(a * img_w)); y1 = int(round(b * img_h))
                    x2 = int(round(c * img_w)); y2 = int(round(d * img_h))
                else:
                    x1 = int(round(a * img_w)); y1 = int(round(b * img_h))
                    x2 = int(round((a + c) * img_w)); y2 = int(round((b + d) * img_h))
            else:
                # pixel coordinates or [x,y,w,h] in px
                if c > a and d > b:
                    x1 = int(round(a)); y1 = int(round(b)); x2 = int(round(c)); y2 = int(round(d))
                else:
                    x1 = int(round(a)); y1 = int(round(b)); x2 = int(round(a + c)); y2 = int(round(b + d))
        else:
            return None

        # sanitize order
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        # clip
        x1 = max(0, min(int(x1), img_w - 1))
        y1 = max(0, min(int(y1), img_h - 1))
        x2 = max(0, min(int(x2), img_w))
        y2 = max(0, min(int(y2), img_h))

        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    except Exception:
        return None

# ---------------------------------------------------------------------------

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
            "value": 1,
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
            "value": 1,
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
            pipe_dtype = torch.bfloat16 if device == "cuda" else torch.float32
            self.pipe = pipeline(
                "object-detection",
                model=model_ref,
                device=device_id,
                torch_dtype=pipe_dtype,
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

        # mask: bubble regions → mask only (inpainting area), no TextBlock.
        # text_bubble / text_free → TextBlock + mask (only the text itself, like CTD).
        mask = np.zeros((h, w), dtype=np.uint8)
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
            label = (item.get("label") or "").strip().lower()
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

            if label == "bubble":
                # Bubble outline → skip entirely (no mask, no TextBlock).
                # Only text_bubble and text_free are used, like CTD.
                continue
            else:
                # text_bubble, text_free → TextBlock + mask
                pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)
                blk = TextBlock(xyxy=[x1, y1, x2, y2], lines=[pts.tolist()])
                blk._detected_font_size = max(y2 - y1, 12)
                blk_list.append(blk)

        # Keep HF detections as-is (do not merge) to preserve block granularity for CTD
        # blk_list = _merge_overlapping_blocks(blk_list, 0.35, max_area)

        # Box padding for text blocks
        if pad_val > 0:
            blk_list = _expand_blocks(blk_list, pad_val, w, h)

        # Sort by reading order
        blk_list = sort_regions(blk_list)

        # Clip text blocks to page
        blk_list = _clip_blocks_to_page(blk_list, w, h)

        # Draw rectangular mask as rough prediction guide for refine_mask
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

        # Use CTD model to obtain a binary mask of text areas (replace refine_mask flow).
        # keep a copy of the coarse HF mask for debugging
        coarse_mask = mask.copy()
        try:
            ctd = ComicTextDetector()
            ctd._load_model()
            ctd_mask, ctd_blk_list = ctd._detect(img, None)
            # if CTD returned a valid mask, use it; otherwise fall back to coarse mask
            if isinstance(ctd_mask, np.ndarray) and ctd_mask.dtype == np.uint8:
                mask = ctd_mask
            else:
                mask = coarse_mask
        except Exception as e:
            self.logger.warning("CTD detection failed: %s", e)
            mask = coarse_mask

        # Optional debug dump: save HF results, pre/post masks and block boxes
        try:
            dbg_path = (self.params.get("debug_dump_path") or {}).get("value")
            if dbg_path:
                dbg_dir = Path(dbg_path)
                dbg_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                # save HF raw results if available
                try:
                    raw_fp = dbg_dir / f"hf_results_{ts}.json"
                    with raw_fp.open("w", encoding="utf-8") as f:
                        json.dump(results if 'results' in locals() else {}, f, default=str, ensure_ascii=False, indent=2)
                except Exception as e:
                    self.logger.debug("Failed to write hf results: %s", e)
                # save HF coarse mask and CTD mask
                try:
                    cv2.imwrite(str(dbg_dir / f"mask_hf_coarse_{ts}.png"), coarse_mask)
                except Exception:
                    pass
                try:
                    cv2.imwrite(str(dbg_dir / f"mask_ctd_{ts}.png"), mask)
                except Exception:
                    pass
        except Exception:
            # never crash detection due to debugging IO
            pass

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