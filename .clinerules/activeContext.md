# Active Context

## Current Work Focus
Implementing the `comic-text-and-bubble-detector` detector module for the ogkalu/comic-text-and-bubble-detector HuggingFace model.

## Recent Changes
- Created `modules/textdetector/detector_comic-text-and-bubble-detector.py` — new HF object-detection detector module
- Registered as `comic-text-and-bubble-detector` via `@register_textdetectors`
- Uses `transformers.pipeline("object-detection")` for inference
- Detects labels: `bubble`, `text_bubble`, `text_free` (all kept as text regions)
- Verified auto-registration succeeds (registry shows: comic-text-and-bubble-detector, ctd, stariver_ocr, ysgyolo)
- Fixed `_detect` returning None (was missing `return mask, blk_list`)
- Removed old `detector_ogkalu.py` file; renamed to `detector_comic-text-and-bubble-detector.py`

## Next Steps
1. Test the new detector with actual comic pages (launch the app, select "comic-text-and-bubble-detector", run detection)
2. Fine-tune default confidence threshold and other params based on test results
3. If issues arise: adjust post-processing (merge IoU threshold, box padding, etc.)

## Active Decisions and Considerations
- Using `pipeline("object-detection")` rather than direct model+processor loading for simplicity
- All three model labels (bubble, text_bubble, text_free) are treated as text regions
- IoU overlap merging at 0.35 helps deduplicate overlapping bubble+text_bubble detections
- Box padding of 3px reduces clipped punctuation without excessive expansion
- The model auto-downloads from HuggingFace on first use (~170MB)

## Important Patterns and Preferences
- Use virtual environment: `j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe`
- Launch command: `& "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py`
- All Python commands must use myenv, not global Python
- In PowerShell use `& "путь\python.exe" args` (символ `&` и кавычки обязательны)

## Learnings and Project Insights
- Detector auto-registration works via naming convention: file named `detector_<name>.py` in `modules/textdetector/`
- The `ogkalu/comic-text-and-bubble-detector` uses RT-DETRv2 architecture with 42.9M params
- The model is also available in ONNX format, but transformers pipeline is preferred
- Registration key must match the name in config, otherwise KeyError occurs at module switch
