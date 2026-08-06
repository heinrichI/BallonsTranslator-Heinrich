import pytest
import numpy as np

def test_config_default():
    import utils.config as cfg
    assert cfg.pcfg.module.load_model_on_demand is True

def test_paddleocr_lazy_or_skip():
    try:
        from modules.ocr.ocr_paddle import PaddleOCRModule, PADDLE_OCR_AVAILABLE
    except Exception:
        pytest.skip("ocr_paddle import failed")
    if not PADDLE_OCR_AVAILABLE:
        pytest.skip("PaddleOCR not installed in test env")
    inst = PaddleOCRModule()
    # model should not be loaded at construction when lazy mode enabled
    assert getattr(inst, "model", None) is None
    assert getattr(PaddleOCRModule, "_load_model_keys", None) == {"model"}

def test_ctd_detector_cached(monkeypatch):
    mod = __import__("modules.textdetector.detector_comic-text-and-bubble-detector",
                     fromlist=["ComicTextAndBubbleDetector", "ComicTextDetector", "_HF_AVAILABLE"])
    ComicTextAndBubbleDetector = mod.ComicTextAndBubbleDetector

    # Dummy CTD to count instantiations
    class DummyCTD:
        created = 0
        def __init__(self):
            DummyCTD.created += 1
        def _load_model(self):
            return
        def _detect(self, img, proj):
            h, w = img.shape[:2]
            return np.zeros((h, w), dtype=np.uint8), []

    monkeypatch.setattr(mod, "ComicTextDetector", DummyCTD)
    monkeypatch.setattr(mod, "_HF_AVAILABLE", True)

    det = ComicTextAndBubbleDetector()
    assert det._ctd_detector is None
    # Make a harmless callable pipeline that returns empty results
    det.pipe = lambda img: []
    img = np.zeros((16, 16, 3), dtype=np.uint8)

    # First call should construct DummyCTD once
    mask1, blks1 = det._detect(img, None)
    assert DummyCTD.created == 1
    # Second call should reuse same instance (no new creation)
    mask2, blks2 = det._detect(img, None)
    assert DummyCTD.created == 1