# Technical Context

## Technologies Used
- **Python 3.10–3.12** (primary language)
- **PyQt6/PyQt5** — cross-platform GUI framework
- **PyTorch** — deep learning framework for all ML modules
- **transformers** — HuggingFace library (used by ogkalu_rtdetr detector, translators)
- **ultralytics** — YOLO/RT-DETR model loading (ysg detector)
- **OpenCV** — image processing, mask operations
- **NumPy** — array operations
- **Pillow** — image conversion for HF pipeline
- **ONNX Runtime** — alternative inference backend (ctd detector)

## Development Setup
- **Python interpreter**: `j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe`
- **Запуск проекта**: `"j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py`
- **Виртуальное окружение**: `j:\Comic translate\BallonsTranslator\myenv\`
- **Установка зависимостей**: `"j:\Comic translate\BallonsTranslator\myenv\Scripts\pip.exe" install -r requirements.txt`
- **Важно**: Все команды Python должны выполняться из этого виртуального окружения

## Installed Modules (as of May 2026)

### Text Detectors (4)
| ID | Class | Description |
|----|-------|-------------|
| `ctd` | `ComicTextDetector` | Original comictextdetector.pt (ONNX/Torch) |
| `ysgyolo` | `YSGYoloDetector` | YOLO/RT-DETR via ultralytics |
| `stariver_ocr` | `StariverDetector` | Stariver cloud API |
| `ogkalu_rtdetr` | `OgkaluRTDetrDetector` | HF transformers pipeline (ogkalu model) |

### OCR Modules (19)
manga_ocr, paddle_ocr, mit32px, mit48px, mit48px_ctc, tr_ocr, bing_ocr, google_vision, google_lens_exp, idefics2_ocr, llm_ocr, none_ocr, one_ocr, one_ocr_mitfont, qwen2_ocr, stariver_ocr, windows_ocr, PaddleOCRVLMy, PaddleOCRVLMyColor

### Inpainters (5)
lama_mpe, lama_large_512px, aot, patchmatch, opencv-tela

### Translators (22)
google, DeepL, DeepL Free, DeepLX API, ChatGPT, ChatGPT_exp, Baidu, Caiyun, Yandex, YandexFree, Papago, Youdao, Sakura, Sugoi, ezTrans, m2m100, nllb200, TransGemma, LLM_API_Translator, text-generation-webui, TranslatorsPack, None, Copy Source

## Technical Constraints
- **Windows 10** primary target (with macOS/Linux support)
- **CUDA/MPS/XPU** GPU support via PyTorch
- **ONNX** fallback for CPU inference (ctd detector)
- **3-channel RGB** input required by all detectors
- **8-bit uint8** binary masks (0 or 255)
- Model weights stored in `data/models/`

## Key Dependencies
- `torch` + `torchvision` — core ML framework
- `transformers` — HF model loading (ogkalu_rtdetr, translators)
- `ultralytics==8.3.90` — YOLO/RT-DETR inference
- `opencv-python` — image processing
- `PyQt6` — GUI
- `shapely` — polygon operations
- `pillow` — image format support