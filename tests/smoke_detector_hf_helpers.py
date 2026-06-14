import importlib.util
import os
import sys

HERE = os.path.dirname(__file__)
MODULE_PATH = os.path.abspath(os.path.join(HERE, "..", "modules", "textdetector", "detector_comic-text-and-bubble-detector.py"))

def load_module(path):
    # Ensure project root is on sys.path so package-relative imports work
    project_root = os.path.abspath(os.path.join(HERE, ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    spec = importlib.util.spec_from_file_location("hf_detector_hf_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    # set package to allow relative imports (module lives in modules/textdetector)
    mod.__package__ = "modules.textdetector"
    spec.loader.exec_module(mod)
    return mod

def assert_eq(a, b):
    if a != b:
        raise SystemExit(f"ASSERT FAILED: {a!r} != {b!r}")

def run():
    mod = load_module(MODULE_PATH)
    safe = getattr(mod, "_safe_box_from_item", None)
    if safe is None:
        raise SystemExit("Helper _safe_box_from_item not found")

    img_w, img_h = 640, 480

    cases = [
        ({"box": {"xmin": 10, "ymin": 15, "xmax": 110, "ymax": 115}}, (10,15,110,115)),
        ({"box": {"left": 5, "top": 6, "width": 20, "height": 30}}, (5,6,25,36)),
        ({"bbox": [0.1, 0.1, 0.2, 0.2]}, (int(round(0.1*img_w)), int(round(0.1*img_h)), int(round(0.2*img_w)), int(round(0.2*img_h)))),
        ({"bbox": [50, 60, 150, 160]}, (50,60,150,160)),
        ({"bbox": [50, 60, 100, 40]}, (50,60,150,100)),  # [x,y,w,h]
        ({"box": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}}, (1,2,3,4)),
    ]

    for item, expected in cases:
        out = safe(item, img_w, img_h)
        if out is None:
            raise SystemExit(f"Case {item!r} returned None")
        assert_eq(tuple(out), tuple(expected))

    # invalid cases
    invalids = [
        {},
        {"box": {"foo": 1}},
        {"bbox": [1,2,3]},  # wrong length
        {"box": None},
    ]
    for item in invalids:
        out = safe(item, img_w, img_h)
        if out is not None:
            raise SystemExit(f"Invalid case {item!r} unexpectedly returned {out!r}")

    print("All helper smoke tests passed.")

if __name__ == "__main__":
    run()