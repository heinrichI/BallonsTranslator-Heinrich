# Implementation Plan

Add support for the **ogkalu/comic-text-and-bubble-detector** (RT-DETRv2) HuggingFace model as a new text detector module in BallonsTranslator, following the existing `detector_<name>.py` registration pattern.

The model detects three object classes: `bubble`, `text_bubble`, and `text_free` (SFX/captions). All three are treated as text regions — each detection produces a `TextBlock` and paints its area onto the binary mask. The implementation uses `transformers.pipeline("object-detection")` which auto-downloads and caches model weights from HuggingFace, and exposes user-adjustable parameters (confidence threshold, device selection, font size controls, mask dilate size, box padding) through the same UI pattern as all other detectors. Post-processing includes box padding, IoU-based overlap merging, clipping to page bounds, and reading-order sorting.

## [Types]

No new Python types or data structures are needed. The detector reuses existing types:
- `TextBlock` from `utils.textblock`
- `ProjImgTrans` from `utils.proj_imgtrans`
- `np.ndarray` for images and masks

The `pipeline()` returns results as `List[Dict]` with keys: `score`, `label` (string), `box` (dict with `xmin`, `ymin`, `xmax`, `ymax`).

Labels from the ogkalu model:
- `bubble` — speech bubble region → treated as text
- `text_bubble` — individual text inside bubble → treated as text  
- `text_free` — sound effects/captions outside bubbles → treated as text

All three labels are kept. Each detection produces one `TextBlock`.

## [Files]

One new file must be created:

| File | Action |
|------|--------|
| `modules/textdetector/detector_ogkalu.py` | **CREATE** — new detector module (~220 lines) |

No existing files need modification (auto-registration via file naming convention).

### New file: `modules/textdetector/detector_ogkalu.py`

**Imports**: `numpy`, `cv2`, `copy`, `os.path`, `typing`, existing project helpers (`TextDetectorBase`, `TextBlock`, `DEVICE_SELECTOR`, `register_textdetectors`, `sort_regions`), plus conditional import of `transformers.pipeline`, `torch`, `PIL.Image`.

**Class**: `OgkaluRTDetrDetector(TextDetectorBase)`
- Registration: `@register_textdetectors('ogkalu_rtdetr')`
- `params` dict (UI-configurable):
  - `'model_id'`: `{'type': 'line_editor', 'value': 'ogkalu/comic-text-and-bubble-detector'}` — allows user to switch to another HF model
  - `'confidence threshold'`: `{'type': 'line_editor', 'value': 0.3}` — min detection score
  - `'box_padding'`: `{'type': 'line_editor', 'value': 3}` — pixels to expand each box (reduce clipped punctuation)
  - `'font size multiplier'`: `{'type': 'line_editor', 'value': 1.0}`
  - `'font size max'`: `{'type': 'line_editor', 'value': -1}`
  - `'font size min'`: `{'type': 'line_editor', 'value': -1}`
  - `'mask dilate size'`: `{'type': 'line_editor', 'value': 2}`
  - `'device'`: `DEVICE_SELECTOR()`
  - `'description'`: info string
- `_load_model_keys = {'pipe'}`
- `_load_model()`:
  1. Read `model_id` and `device` from params
  2. Resolve local path vs HF hub id
  3. Create `pipeline("object-detection", model=model_ref, device=0 if device=='cuda' else -1)`
  4. Store as `self.pipe`
- `_detect(img, proj) -> (mask, blk_list)`:
  1. Convert 4-channel to 3-channel if needed
  2. Record original h, w
  3. Run `self.pipe(PILImage.fromarray(img))` → list of detection dicts
  4. Filter by confidence threshold
  5. For each detection:
     - Extract `xmin, ymin, xmax, ymax` from `box` dict
     - Clip to image bounds
     - Apply box padding (pixels)
     - Create `TextBlock` with `xyxy` and `lines` as 4-corner polygon
     - Set `_detected_font_size = max(y2 - y1, 12)`
  6. Merge overlapping blocks via IoU threshold (0.35 default)
  7. Apply font size multiplier/max/min
  8. Build mask by `cv2.fillPoly` for each block
  9. Apply mask dilate
  10. Sort by reading order via `sort_regions()`
  11. Clip blocks to page bounds
  12. Return `mask, blk_list`
- `updateParam(param_key, param_content)`: reset `self.pipe = None` on model_id or device change

**Helper functions** (module-level):
- `_iou_xyxy(a, b)`: IoU for two [x1,y1,x2,y2] boxes
- `_merge_overlapping_blocks(blk_list, iou_threshold)`: merge blocks with IoU ≥ threshold or containment
- `_clip_blocks_to_page(blk_list, img_w, img_h)`: clamp all coordinates to image bounds
- `_expand_blocks(blk_list, pad, w, h)`: pad each block outward

## [Functions]

### New functions in `detector_ogkalu.py`

| Function | Signature | Purpose |
|----------|-----------|---------|
| `_iou_xyxy(a, b)` | `(List[float], List[float]) -> float` | IoU for two xyxy boxes |
| `_merge_overlapping_blocks(blk_list, iou_threshold)` | `(List[TextBlock], float) -> List[TextBlock]` | Merge blocks with high overlap |
| `_clip_blocks_to_page(blk_list, img_w, img_h)` | `(List[TextBlock], int, int) -> List[TextBlock]` | Clamp blocks to image bounds |
| `_expand_blocks(blk_list, pad, w, h)` | `(List[TextBlock], int, int, int) -> List[TextBlock]` | Pad each block outward |
| `OgkaluRTDetrDetector._load_model(self)` | `-> None` | Load HF pipeline |
| `OgkaluRTDetrDetector._detect(self, img, proj)` | `(np.ndarray, ProjImgTrans) -> Tuple[np.ndarray, List[TextBlock]]` | Run inference, parse outputs |
| `OgkaluRTDetrDetector.updateParam(self, param_key, param_content)` | `(str, any) -> None` | Reset pipe on param change |

### Modified functions

None.

### Removed functions

None.

## [Classes]

### New class: `OgkaluRTDetrDetector(TextDetectorBase)`

- **File**: `modules/textdetector/detector_ogkalu.py`
- **Registration key**: `'ogkalu_rtdetr'`
- **Key attributes**:
  - `params`: dict with all UI-visible parameters
  - `pipe`: `transformers.pipeline` instance (object-detection)
  - `_load_model_keys = {'pipe'}`
- **Key methods**:
  - `_load_model()` — creates HF pipeline
  - `_detect(img, proj)` — main inference pipeline
  - `updateParam()` — handles model_id/device changes

## [Dependencies]

No new dependencies. `transformers` (≥4.38), `torch`, `Pillow` are already in `requirements.txt`.

The model `ogkalu/comic-text-and-bubble-detector` (~43M params, ~170MB) is downloaded automatically by `transformers` on first use and cached.

## [Testing]

Manual testing via the BallonsTranslator UI:
1. Launch app, go to Settings → Text Detection
2. Select "ogkalu_rtdetr" from the detector dropdown
3. Load a comic page image
4. Run text detection pipeline
5. Verify that `bubble`, `text_bubble`, and `text_free` regions are detected as TextBlocks
6. Verify the mask covers all detected areas
7. Verify font size estimation, sorting, and ordering is reasonable

## [Implementation Order]

1. Create `modules/textdetector/detector_ogkalu.py` with the complete detector class
2. Verify auto-registration by launching the app and checking the detector dropdown
3. Test on sample comic pages to validate detection quality and mask generation