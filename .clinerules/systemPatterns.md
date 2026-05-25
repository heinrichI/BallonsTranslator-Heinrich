# System Patterns

## System Architecture
BallonsTranslator uses a modular **pipeline architecture** with 4 main stages:
1. **Text Detection** → finds text regions on page images
2. **OCR** → recognizes text in detected regions
3. **Translation** → translates recognized text
4. **Inpainting** → erases original text from image

Each stage is implemented as a **pluggable module** registered via a `Registry` pattern. Users can mix and match modules from different providers.

## Key Technical Decisions
- **Qt6/PyQt6** for cross-platform GUI
- **PyTorch** as the primary deep learning framework
- **Registry pattern** for module registration (see `utils/registry.py`)
- **Auto-discovery** of modules via naming convention: files named `detector_<name>.py`, `ocr_<name>.py`, `translator_<name>.py`, `inpaint_<name>.py` are auto-imported
- **3-channel RGB** input standard for all detectors (RGBA→RGB conversion in base class)
- **8-bit uint8** format for mask images
- **`data/models/`** directory for model weight storage (with download-on-demand)

## Design Patterns in Use
| Pattern | Location | Purpose |
|---------|----------|---------|
| Registry | `utils/registry.py`, `modules/base.py` | Module registration and lookup |
| Base Class | `modules/base.py` (`BaseModule`) | Common interface for all modules |
| Template Method | `modules/textdetector/base.py` | `detect()` → `_detect()` hook |
| Thread Worker | `ui/module_manager.py` | Non-blocking pipeline execution |
| Signal/Slot | Qt signals in `ui/module_manager.py` | Cross-thread communication |
| Factory | `init_module_registries()` | Auto-discover and register modules |

## Component Relationships
```
App (mainwindow.py)
  └── ModuleManager (module_manager.py)
        ├── TextDetectThread → TextDetectorBase → {ctd, ysg, ogkalu, stariver}
        ├── OCRThread → OCRBase → {manga_ocr, paddle_ocr, ...}
        ├── TranslateThread → BaseTranslator → {google, deepl, chatgpt, ...}
        └── InpaintThread → InpainterBase → {lama, patchmatch, ...}
```

## Critical Implementation Paths
1. **Pipeline execution** (`ImgtransThread._imgtrans_pipeline`): iterates pages, runs detect→OCR→translate→inpaint sequentially or in parallel
2. **TextBlock object** (`utils/textblock.py`): core data structure carrying xyxy, lines, text, translation, font format, mask
3. **Detector interface** (`TextDetectorBase`): `_detect(img, proj) -> (mask, blk_list)` — returns binary mask + list of TextBlocks
4. **Mask generation**: each detector fills a binary mask (`np.uint8`, 0 or 255) marking areas to inpaint