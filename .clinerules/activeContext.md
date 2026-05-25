# Active Context

## Current Work Focus
Integrating and hardening the ogkalu/comic-text-and-bubble-detector HF object-detection detector and improving CTD-based pixel-level text segmentation pipeline.

## Recent Changes
- Implemented `modules/textdetector/detector_comic-text-and-bubble-detector.py` improvements:
  - Defensive parsing helpers: `_validate_detection_item(item)` and `_safe_box_from_item(item, img_w, img_h)`.
  - Safe box expansion: `_expand_blocks` now caps per-block padding to 15% of block height.
  - Merge protection: `_merge_overlapping_blocks` accepts `max_area` and skips merges that would exceed 20% of page area.
  - Default parameter adjustments: `"box_padding"` default reduced to 1, `"mask dilate size"` default reduced to 1.
  - Debug dump support added (hf_results_{ts}.json, mask_pre_refine_{ts}.png, mask_post_refine_{ts}.png).
- Added helper/debug scripts:
  - `scripts/debug_run_detector_params.py` — run detector with pad/dilate/no_merge options and save dumps.
  - `scripts/count_debug_masks.py` — compute nonzero pixels for mask_*.png files.
  - `scripts/debug_run_detector.py` — single-image debug runner.
- CTD-related files commented in Russian for clarity:
  - `modules/textdetector/detector_ctd.py` — russian comments added.
  - `modules/textdetector/ctd/basemodel.py` — russian comments added.
  - `modules/textdetector/ctd/inference.py` — russian comments added.
- Small unit helper added: `tests/smoke_detector_hf_helpers.py` (sanity for box parsing).

## Next Steps
- Finalize splitting large merged blocks into text-lines before calling `refine_mask` (to get per-character masks instead of block masks).
- Run manual UI verification across multiple comic pages.
- Consider lowering defaults to pad=0 / dilate=0 in release or expose clearly in UI.
- Update docs (doc/modules or CHANGELOG) describing new detector behavior and required HF model.

## Active Decisions and Considerations
- Use HF `pipeline("object-detection")` for ogkalu model; skip detections labeled `bubble`.
- Treat `text_bubble` and `text_free` as text regions.
- Apply CTD.pixel-level `refine_mask(img, mask, blk_list)` after drawing coarse polygon masks.
- Avoid producing huge merged boxes — cap merge by page-area threshold (0.2).
- Limit per-block padding to a fraction of block height (0.15) to avoid background inclusion.

## How to run (examples)
- Launch app (recommended venv):
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py
- Debug detector on single image:
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" scripts/debug_run_detector_params.py "path\to\img.jpg" debug_dump 0 0
- Count debug masks:
  & "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" scripts/count_debug_masks.py