# Progress

## What Works
- Full translation pipeline: detect → OCR → translate → inpaint → render
- 4 text detectors (ctd, ysgyolo, stariver_ocr, ogkalu_rtdetr)
- 19 OCR modules
- 22 translation engines
- 5 inpainters
- WYSIWYG text editing with formatting
- Image editing with inpainting brush
- Word document import/export
- Full-text search/replace
- Font style presets
- Vertical (webtoon) comic support

## What's Left to Build
- Ongoing: improving translation quality and text rendering accuracy
- Ongoing: adding more detector/OCR/translator/inpainter options
- The new `ogkalu_rtdetr` detector needs real-world testing

## Current Status (May 2026)
- **ogkalu_rtdetr detector**: implemented and registered, pending manual testing
- **Memory Bank**: core files initialized with project overview

## Known Issues
- Different detectors produce varying quality depending on comic style
- Model weight downloading can fail behind restrictive networks (manual download fallback available)
- Windows 7 not supported for pre-built packages