# Technical Context — CTD & ogkalu HF detector notes

## CTD (ComicTextDetector) — implementation notes
- CTDModel provides pixel-level text segmentation and detected text blocks.
- Model formats:
  - ONNX (recommended for CPU): `data/models/comictextdetector.pt.onnx`
  - Torch (recommended for GPU): `data/models/comictextdetector.pt`
- Pipeline stages:
  1. Optional rearrange for extreme aspect ratios: `det_rearrange_forward` produces tiled square batches so model sees near-square crops.
  2. Backbone (YOLOv5 variant) extracts features.
  3. UNet-like head (`UnetHead`) produces coarse text mask.
  4. Optional DBHead produces shrink/threshold maps → lines/blocks.
  5. Postprocessing:
     - `postprocess_mask` converts logits to uint8 mask.
     - `SegDetectorRepresenter` (db utils) converts line maps → line polygons.
     - `group_output` → assemble TextBlock list.
  6. Pixel refinement: `refine_mask(img, coarse_mask, blk_list, refine_mode)` (modules/textdetector/ctd/textmask.py) — produces per-character masks using CTD logic.

## ogkalu/comic-text-and-bubble-detector notes
- Uses HF `transformers.pipeline("object-detection")`. Pipeline returns list of items with keys: `score`, `label`, `box` (box formats vary).
- Important behaviors implemented:
  - Defensive parsing: `_safe_box_from_item` supports multiple HF box formats (dict with xmin/xmax, left/width, list normalized / px).
  - Filter labels: skip `bubble` labels; treat `text_bubble` and `text_free` as text regions.
  - Merge overlapping detections with IoU threshold 0.35; but skip merges producing area > 20% of page area.
  - Per-block padding clamped to 15% of block height to avoid mask blowup.
  - Call `refine_mask` after drawing coarse polygon masks, then apply optional dilation.

## API / key functions
- modules/textdetector/detector_comic-text-and-bubble-detector.py:
  - _load_model(): loads HF pipeline, handles device fallback cuda→cpu.
  - _detect(img): returns (mask: np.uint8, blk_list: List[TextBlock])
  - Helpers: `_validate_detection_item`, `_safe_box_from_item`, `_merge_overlapping_blocks`, `_expand_blocks`, `_clip_blocks_to_page`

- modules/textdetector/ctd/inference.py:
  - `TextDetector.__call__`: orchestrates detect_size preprocess, optional rearrange, forward, postprocess, `group_output`, `refine_mask` and optional keep_undetected mask.

## Runtime recommendations
- Use virtualenv `j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe` for running.
- For HF detector: GPU (cuda) recommended to speed up model load/inference; if not available, pipeline falls back to cpu.
- Prefer detect_size ~ 1024–1280; CTD rearrange logic handles extreme aspect ratios.

## Scripts for debugging
- `scripts/debug_run_detector_params.py` — run HF detector with pad/dilate/no_merge switches and save HF raw results + masks.
- `scripts/count_debug_masks.py` — analyze mask pixel counts to detect mask blowup.
- `scripts/debug_run_detector.py` — convenience script for single-image debug.

## Notes on refine_mask expectations
- `refine_mask(img, coarse_mask, blk_list)` expects:
  - `img`: 3-channel RGB ndarray (uint8)
  - `coarse_mask`: uint8 mask with 0/255
  - `blk_list`: list of TextBlock objects with `xyxy` and `lines` for region guidance
- If `blk_list` contains very large merged rectangles, refine_mask will segment broadly (may include background). Recommended to split large blocks into lines before refine_mask.