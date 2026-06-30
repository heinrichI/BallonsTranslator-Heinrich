# Implementation Plan

[Overview]
Integrate and verify the existing ogkalu/comic-text-and-bubble-detector usage so object detections (text_bubble and text_free) produce TextBlocks and CTD.pixel-level segmentation (refine_mask) is applied to produce per-character masks; bubble detections are skipped.

This change ensures accurate per-character masks for inpainting and OCR downstream while reusing the existing HF pipeline implementation in modules/textdetector/detector_comic-text-and-bubble-detector.py. The approach preserves current registration and UI parameters, validates device/model selection, and adds verification and test steps so the detector behaves consistently with other detectors (CTD + HF pipeline integration).

[Types]
No new Python types required.

Re-used types and constraints:
- TextBlock (utils/textblock.TextBlock): fields used: xyxy: List[int|float] (x1,y1,x2,y2), lines: List[List[List[int]]] (polygons), font_size (float), _detected_font_size (int/float), det_model (str)
  - Validation: xyxy must be clipped to image bounds; lines must contain polygons with integer coordinates; font_size > 0.
- Mask: numpy.ndarray, dtype=uint8, shape=(H,W), values {0,255}
- HF pipeline results: List[Dict] with keys:
  - score: float in [0,1]
  - label: str in {"bubble","text_bubble","text_free"} (case-insensitive)
  - box: dict with xmin,ymin,xmax,ymax (numbers)
- ProjImgTrans (utils.proj_imgtrans.ProjImgTrans) optional context passed into detect()

[Files]
Single sentence: Modify the existing HF detector module and ensure tests and documentation are updated.

Detailed breakdown:
- Existing file to modify:
  - modules/textdetector/detector_comic-text-and-bubble-detector.py
    - Purpose: HF object-detection -> parse detections -> create TextBlocks -> draw rough masks -> call CTD.refine_mask for pixel-level refinement -> return (mask, blk_list)
    - Specific modifications (if any required by verification):
      - Ensure explicit skip for label "bubble" (confirmed)
      - Confirm call refine_mask(img, mask, blk_list) is present and receives correct arguments (img as RGB ndarray, mask as uint8, blk_list list[TextBlock]).
      - Verify parameter names and UI keys: "model_id", "confidence threshold", "box_padding", "font size multiplier", "font size max", "font size min", "mask dilate size", "device"
      - Add defensive checks: handle missing/irregular box dicts, non-dict pipeline outputs, and torch/device fallback logic already present.
      - Add inline docstrings/comments explaining the decision to skip "bubble" detections and call CTD.refine_mask.
- New files to create:
  - None required for core change.
- Files to delete/move:
  - None.
- Configuration updates:
  - README or doc/modules/ note (optional) to document that ogkalu detector calls CTD.refine_mask; add short entry in doc/modules/ or CHANGELOG if desired.

[Functions]
Single sentence: Keep existing functions; add or adjust small helper validation and logging.

Detailed breakdown:
- New helper functions (inside detector_comic-text-and-bubble-detector.py if needed):
  - _validate_detection_item(item) -> bool
    - Purpose: robustly validate HF pipeline item dict shape before reading label/box/score.
    - Implementation: ensure dict, contains numeric score, label str, box dict with xmin/ymin/xmax/ymax.
  - (Optional) _safe_box_from_item(item, w, h) -> Tuple[int,int,int,int] — clamps and returns integers (x1,y1,x2,y2).
- Existing functions (verify and adjust as needed):
  - _iou_xyxy(a, b) — keep as implemented for overlap merging.
  - _merge_overlapping_blocks(blk_list, iou_threshold) — keep.
  - _clip_blocks_to_page(blk_list, img_w, img_h) — keep.
  - _expand_blocks(blk_list, pad, w, h) — keep.
  - ComicTextAndBubbleDetector._load_model(self) — verify pipeline creation and device mapping; keep.
  - ComicTextAndBubbleDetector._detect(self, img, proj) -> Tuple[np.ndarray, List[TextBlock]]
    - Ensure flow:
      1. Normalize input to 3-channel RGB (already present).
      2. Read conf_thr & pad_val from params (already present).
      3. Run HF pipeline and filter results by score >= conf_thr.
      4. Skip detections with label == "bubble".
      5. For text_bubble/text_free create TextBlock with xyxy and polygon lines.
      6. Merge, pad, sort, clip.
      7. Draw rough mask (rect/polygon) into mask uint8.
      8. Call refine_mask(img, mask, blk_list) from modules/textdetector/ctd/textmask.py
      9. Dilate mask per param, return mask, blk_list.
    - Required change: none if file already matches; else align to the above flow.
- Removed functions: None.

[Classes]
Single sentence: Modify existing ComicTextAndBubbleDetector only where defensive validation or logging is needed.

Detailed breakdown:
- Modified class:
  - ComicTextAndBubbleDetector (modules/textdetector/detector_comic-text-and-bubble-detector.py)
    - Key methods to verify/adjust:
      - __init__: ensure self.pipe, self._model_id, self._device initial state (already present).
      - _load_model: ensure torch/cuda fallback logic present and informative logging used.
      - _detect: confirm call refine_mask(img, mask, blk_list) and that blk._detected_font_size/font_size adjustments are applied after refine_mask as appropriate.
      - updateParam: reset self.pipe on model/device changes (already present).
    - Inheritance: TextDetectorBase
- New classes: None.
- Removed classes: None.

[Dependencies]
Single sentence: No new packages; transformers, torch, and pillow are required and already referenced.

Details:
- Required packages (verify presence in requirements.txt):
  - transformers >= 4.38
  - torch
  - pillow
- Model files:
  - ogkalu/comic-text-and-bubble-detector will be downloaded by transformers; ensure network/caching policies noted in docs.
- Integration requirements:
  - CTD refine_mask uses utils.imgproc_utils helpers; ensure these imports remain available.

[Testing]
Single sentence: Manual UI testing plus a small scripted validation of detection -> refinement flow.

Test plan:
- Manual UI:
  1. Launch app via virtualenv: & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py
  2. Settings → Text Detection → select "comic-text-and-bubble-detector"
  3. Load diverse comic page images (vertical/horizontal, different font sizes).
  4. Run detection and confirm:
     - text_bubble and text_free produce TextBlocks (visible in UI)
     - bubble detections are skipped
     - mask highlights per-character regions (not just rectangles)
     - OCR accuracy improves on refined masks
- Scripted smoke test (python script):
  - Small script to call module API:
    from modules.textdetector.detector_comic-text-and-bubble-detector import ComicTextAndBubbleDetector
    det = ComicTextAndBubbleDetector()
    mask, blks = det.detect(img)  # with sample numpy array
    assert isinstance(mask, np.ndarray) and mask.dtype == np.uint8
    assert all(isinstance(b, TextBlock) for b in blks)
- Edge case tests:
  - HF pipeline returns malformed entries (graceful skip, log warning).
  - Empty results -> return empty blk_list and zero mask.
  - Large boxes clipped correctly.
  - Device not available (cuda requested but unavailable) -> fallback to cpu.

[Implementation Order]
Single sentence: Verify and, if necessary, adjust the existing detector module, document behavior, then create a tracking task to implement and validate.

Numbered steps:
1. Confirm code in modules/textdetector/detector_comic-text-and-bubble-detector.py already follows the required flow (HF inference → skip "bubble" → create TextBlocks → merge/pad/sort/clip → draw coarse mask → call refine_mask(img, mask, blk_list) → dilate → return mask, blk_list). If not, apply minimal adjustments.
2. Add _validate_detection_item and/or _safe_box_from_item helpers if HF outputs need hardening; add small unit tests for these helpers.
3. Ensure refine_mask call uses image in RGB, mask uint8, and blk_list list[TextBlock]; move font-size post-processing to after refine_mask if needed.
4. Run smoke tests and manual UI test to confirm detection and mask quality.
5. Update docs (doc/modules or README) noting that this detector invokes CTD.refine_mask and that "bubble" detections are skipped.
6. If tests reveal parameter tuning needed, adjust default params ("confidence threshold" 0.3, "box_padding" 3, "mask dilate size" 2).
7. Merge changes and close the implementation task.