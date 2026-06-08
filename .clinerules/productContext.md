# Product Context

## Why This Project Exists
Translating comics and manga manually is extremely labor-intensive — each page requires text detection, OCR, translation, erasing original text, and rendering new text while preserving the original layout and aesthetics. BallonsTranslator automates this entire pipeline using deep learning.

## Problems It Solves
1. **Manual text detection** — Automatically finds text regions and speech bubbles on comic pages
2. **OCR** — Recognizes text in Japanese and English (and other languages)
3. **Translation** — Machine translation with 20+ engines (Google, DeepL, ChatGPT, etc.)
4. **Inpainting** — Erases original text while preserving background art
5. **Text rendering** — Renders translated text with proper formatting (color, outline, angle, orientation, alignment)

## How It Should Work
- User opens a folder of comic images
- Configures source/target languages and selects modules (detector, OCR, translator, inpainter)
- Clicks "Run" to execute the full pipeline automatically
- Can manually edit any detected text blocks, masks, or inpainted regions

## User Experience Goals
- Minimal manual intervention for simple translations
- WYSIWYG editing for fine-tuning results
- Modular: users can mix and match components (e.g., different detectors for different comic styles)
- Preserve original text aesthetics (font size, angle, color, outline, vertical/horizontal alignment)