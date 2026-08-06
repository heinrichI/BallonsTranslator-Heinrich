# Implementation Plan

## [Overview]

Make lazy model loading the default behavior for inpaint, OCR, and detector modules, and fix the modules that currently defeat lazy loading by loading models eagerly in `__init__` or re-creating them on every call.

The codebase already has a complete lazy-loading infrastructure: `BaseModule` (`modules/base.py`) provides `_load_model_keys`, `load_model()`, `_load_model()`, `all_model_loaded()`, and `unload_model()`. The entry points `TextDetectorBase.detect()`, `OCRBase.run_ocr()`, and `InpainterBase.inpaint()` already check `all_model_loaded()` and call `load_model()` on first use. The `ModuleThread._set_module()` (`ui/module_manager.py` line 58-59) already gates eager loading behind `pcfg.module.load_model_on_demand`. However, the flag **defaults to `False`** (`utils/config.py` line 31), so all four modules load their models at startup when `mainwindow.py` calls `setTextDetector()/setOCR()/setInpainter()/setTranslator()`.

Two genuine bugs defeat lazy loading even when the flag is enabled:

1. **`modules/ocr/ocr_paddle.py`** (line 178): calls `self._load_model()` inside `__init__`, loading the PaddleOCR model eagerly regardless of the flag. It also does NOT define `_load_model_keys`, so `unload_model()` cannot free it.

2. **`modules/textdetector/detector_comic-text-and-bubble-detector.py`** (lines 482-484): creates a **new `ComicTextDetector()` and loads the CTD model on every single `_detect()` call** — never cached, never unloaded, causing repeated model loads and memory leaks.

All other audited modules are properly lazy (set model attrs to `None` in `__init__`, define `_load_model_keys`, don't call `_load_model()` in `__init__`): `detector_ctd.py`, `ocr_paddleVL15/16/16Color/my/myColor.py`, `ocr_mit.py`, `ocr_manga.py`, `ocr_oneocr.py`, `ocr_stariver.py`, `ocr_llm_api.py`, `ocr_none.py`, AOT/Lama inpainters.

## [Types]

No new types are introduced. The change modifies existing class attributes and method behavior.

- `ModuleConfig.load_model_on_demand: bool` — default changes from `False` to `True` in `utils/config.py`.
- `PaddleOCRModule._load_model_keys: set` — new class attribute `{'model'}` added in `modules/ocr/ocr_paddle.py`.
- `ComicTextAndBubbleDetector._ctd_detector: Optional[ComicTextDetector]` — new instance attribute caching the CTD sub-detector in `modules/textdetector/detector_comic-text-and-bubble-detector.py`.
- `ComicTextAndBubbleDetector._load_model_keys: set` — extended from `{'pipe'}` to `{'pipe', '_ctd_detector'}` so `unload_model()` frees both.

## [Files]

### Modified files

1. **`utils/config.py`** (line 31)
   - Change `load_model_on_demand: bool = False` to `load_model_on_demand: bool = True`.

2. **`modules/ocr/ocr_paddle.py`**
   - Add `_load_model_keys = {'model'}` class attribute (near line 162, after `device = DEFAULT_DEVICE`).
   - Remove the `self._load_model()` call from `__init__` (line 178).
   - In `updateParam` (lines 370-390): when a model-affecting param changes, set `self.model = None` before calling `self._load_model()` so the next `run_ocr()` re-loads lazily and `all_model_loaded()` reports `False` until then.

3. **`modules/textdetector/detector_comic-text-and-bubble-detector.py`**
   - Change `_load_model_keys = {"pipe"}` to `_load_model_keys = {"pipe", "_ctd_detector"}` (line 304).
   - In `__init__` (lines 306-310): add `self._ctd_detector = None`.
   - In `_detect()` (lines 481-492): replace the per-call `ComicTextDetector()` creation with a cached instance.
   - In `updateParam` (lines 569-574): when `model_id` or `device` changes, also reset `self._ctd_detector = None` so the CTD sub-detector is re-created on next use.

## [Functions]

### Modified functions

1. **`PaddleOCRModule.__init__`** (`modules/ocr/ocr_paddle.py`, lines 164-178)
   - Remove `self._load_model()` (line 178). Model loads lazily on first `run_ocr()` via `OCRBase.run_ocr()` → `all_model_loaded()` → `load_model()`.

2. **`PaddleOCRModule.updateParam`** (`modules/ocr/ocr_paddle.py`, lines 370-390)
   - When a model-affecting param changes (`language`, `device`, `use_angle_cls`, `ocr_version`, `enable_mkldnn`, `det_limit_side_len`, `rec_batch_num`, `drop_score`): set `self.model = None` before calling `self._load_model()`. This ensures the model is re-created lazily on next use and `all_model_loaded()` correctly reports `False` until then.

3. **`ComicTextAndBubbleDetector._detect`** (`modules/textdetector/detector_comic-text-and-bubble-detector.py`, lines 481-492)
   - Replace the per-call `ComicTextDetector()` instantiation with a cached `self._ctd_detector` instance. Only create and load once; reuse on subsequent calls:
     ```python
     if self._ctd_detector is None:
         self._ctd_detector = ComicTextDetector()
         self._ctd_detector._load_model()
     ctd_mask, ctd_blk_list = self._ctd_detector._detect(img, None)
     ```

4. **`ComicTextAndBubbleDetector.updateParam`** (`modules/textdetector/detector_comic-text-and-bubble-detector.py`, lines 569-574)
   - When `model_id` or `device` changes, also set `self._ctd_detector = None` so the CTD sub-detector is re-created on next use.

## [Classes]

### Modified classes

1. **`PaddleOCRModule`** (`modules/ocr/ocr_paddle.py`)
   - Add `_load_model_keys = {'model'}` class attribute.
   - Remove the eager `_load_model()` call from `__init__`.
   - Update `updateParam` to reset `self.model = None` before reload.

2. **`ComicTextAndBubbleDetector`** (`modules/textdetector/detector_comic-text-and-bubble-detector.py`)
   - Extend `_load_model_keys` to include `_ctd_detector`.
   - Add `self._ctd_detector = None` in `__init__`.
   - Cache CTD sub-detector in `_detect()`.
   - Reset `_ctd_detector` in `updateParam` on model/device change.

## [Dependencies]

No new dependencies. No version changes. The existing `pyphen`, `transformers`, `torch`, `paddleocr` (optional), and `ctd` modules are unchanged.

## [Testing]

### New tests

1. **`tests/test_lazy_loading.py`** — new test file verifying:
   - `ModuleConfig.load_model_on_demand` defaults to `True`.
   - `PaddleOCRModule.__init__` does NOT call `_load_model()` (model attr is `None` after construction).
   - `PaddleOCRModule` defines `_load_model_keys = {'model'}`.
   - `ComicTextAndBubbleDetector.__init__` sets `_ctd_detector = None`.
   - `ComicTextAndBubbleDetector._load_model_keys` includes both `pipe` and `_ctd_detector`.
   - `ComicTextAndBubbleDetector._detect` reuses the cached `_ctd_detector` (mock `ComicTextDetector` and assert it is constructed only once across two `_detect` calls).

### Existing tests

- Run `myenv\Scripts\python -m pytest tests/ui/ -v` to ensure no regressions in UI tests.
- Run `myenv\Scripts\python -m pytest tests/ -v` for the full suite.

### Manual validation

- Launch the app with `& "j:\Comic translate\BallonsTranslator\myenv\Scripts\python.exe" launch.py`.
- Verify no model loading happens at startup (check log for absence of "Loaded HF object-detection model" / "Loading PaddleOCR model" messages).
- Run a detection pass and verify the HF model + CTD sub-detector load on first `detect()` call.
- Toggle the "Load models on demand" checkbox off and verify models load at startup again.

## [Implementation Order]

1. Change `load_model_on_demand` default to `True` in `utils/config.py`.
2. Fix `modules/ocr/ocr_paddle.py`: add `_load_model_keys`, remove eager `_load_model()` from `__init__`, update `updateParam`.
3. Fix `modules/textdetector/detector_comic-text-and-bubble-detector.py`: cache CTD sub-detector, extend `_load_model_keys`, update `updateParam`.
4. Add `tests/test_lazy_loading.py` with the new tests.
5. Run the full test suite and manual validation.
