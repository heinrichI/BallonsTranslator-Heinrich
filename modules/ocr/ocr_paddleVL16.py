import re
import warnings
import numpy as np
import torch
from typing import List
from PIL import Image

from transformers import AutoProcessor, AutoModelForImageTextToText
from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS

from .base import OCRBase, register_OCR, DEFAULT_DEVICE, DEVICE_SELECTOR, TextBlock
from collections import Counter

LOCAL_MODEL_DIR = r"data/models/paddle_ocr_vl_16"


@register_OCR('PaddleOCRVL16')
class PaddleOCRVL16(OCRBase):
    """
    PaddleOCR-VL-1.6 integration via transformers AutoModelForImageTextToText.

    Supports base model download and user-specified finetuned model paths.
    Uses processor.apply_chat_template() for correct multi-modal input preparation.
    Supports CPU / CUDA device switching and uses bfloat16 on CUDA, float32 on CPU.
    Requires transformers>=5.0.0.
    """
    params = {
        "device": DEVICE_SELECTOR(),
        "model_path": {
            "value": "",
            "description": "Path to PaddleOCR-VL-1.6 model dir. Leave empty to use default downloaded model.",
        },
        "task": {
            "type": "selector",
            "options": ["ocr", "table", "chart", "formula", "spotting", "seal"],
            "value": "ocr",
            "description": "OCR task mode: 'ocr' for text recognition, 'spotting' for detection + recognition, others for specialized parsing"
        },
        "max_new_tokens": {
            "value": 512,
            "description": "Max generation tokens"
        },
        "attn_implementation": {
            "type": "selector",
            "options": ["auto", "flash_attention_2"],
            "value": "auto",
            "description": "Attention implementation: 'auto' (default) or 'flash_attention_2' for speed/memory boost"
        },
        "description": "PaddleOCR-VL-1.6 OCR module. Supports base and finetuned models.",
    }
    device = DEFAULT_DEVICE

    PROMPTS = {
        "ocr": "OCR:",
        "table": "Table Recognition:",
        "formula": "Formula Recognition:",
        "chart": "Chart Recognition:",
        "spotting": "Spotting:",
        "seal": "Seal Recognition:",
    }

    SPOTTING_UPSCALE_THRESHOLD = 1500

    MAX_PIXELS = {
        "ocr": 1280 * 28 * 28,
        "spotting": 2048 * 28 * 28,
        "table": 1280 * 28 * 28,
        "formula": 1280 * 28 * 28,
        "chart": 1280 * 28 * 28,
        "seal": 1280 * 28 * 28,
    }

    download_file_list = [{
        'url': 'https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/resolve/main/',
        'files': [
            'config.json',
            'configuration_paddleocr_vl.py',
            'generation_config.json',
            'model.safetensors',
            'modeling_paddleocr_vl.py',
            'tokenizer_config.json',
            'tokenizer.json',
            'tokenizer.model',
            'preprocessor_config.json',
            'processing_paddleocr_vl.py',
            'processor_config.json',
            'special_tokens_map.json',
            'inference.yml',
            'image_processing_paddleocr_vl.py',
            'README.md'
        ],
        'sha256_pre_calculated': [None]*15,
        'save_dir': LOCAL_MODEL_DIR,
        'concatenate_url_filename': 1,
    }]

    _load_model_keys = {'model', 'processor'}

    # PaddleOCR-VL-1.6 Jinja2 chat template (passed directly to apply_chat_template)
    # Based on the finetuned model's chat_template.jinja which uses
    # <|IMAGE_START|><|IMAGE_PLACEHOLDER|><|IMAGE_END|> tokens.
    _CHAT_TEMPLATE = (
        "{%- if not cls_token is defined -%}"
        "    {%- set cls_token = \"<|begin_of_sentence|>\" -%}"
        "{%- endif -%}"
        "{{- cls_token -}}"
        "{%- for message in messages -%}"
        "    {%- if message[\"role\"] == \"user\" -%}"
        "        {{- \"User: \" -}}"
        "        {%- for content in message[\"content\"] -%}"
        "            {%- if content[\"type\"] == \"image\" -%}"
        "                {{ \"<|IMAGE_START|><|IMAGE_PLACEHOLDER|><|IMAGE_END|>\" }}"
        "            {%- endif -%}"
        "        {%- endfor -%}"
        "        {%- for content in message[\"content\"] -%}"
        "            {%- if content[\"type\"] == \"text\" -%}"
        "                {{ content[\"text\"] }}"
        "            {%- endif -%}"
        "        {%- endfor -%}"
        "        {{ \"\\n\" -}}"
        "    {%- elif message[\"role\"] == \"assistant\" -%}"
        "        {{- \"Assistant:\\n\" -}}"
        "        {%- for content in message[\"content\"] -%}"
        "            {%- if content[\"type\"] == \"text\" -%}"
        "                {{ content[\"text\"] }}"
        "            {%- endif -%}"
        "        {%- endfor -%}"
        "        {{ eos_token -}}"
        "    {%- endif -%}"
        "{%- endfor -%}"
        "{%- if add_generation_prompt -%}"
        "    {{- \"Assistant:\\n\" -}}"
        "{%- endif -%}"
    )

    @staticmethod
    def _ensure_default_rope():
        """Register 'default' ROPE_INIT_FUNCTIONS entry if missing (transformers >=5.x compat)."""
        if 'default' not in ROPE_INIT_FUNCTIONS:
            def _compute_default_rope_parameters(config, device=None, seq_len=None, **kw):
                head_dim = getattr(config, 'head_dim', None) or config.hidden_size // config.num_attention_heads
                dim = int(head_dim)
                base = config.rope_theta
                inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.int64).to(device=device, dtype=torch.float) / dim))
                return inv_freq, 1.0
            ROPE_INIT_FUNCTIONS['default'] = _compute_default_rope_parameters

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.device = self.params['device']['value']
        self.model = None
        self.processor = None

    def _get_model_dir(self):
        model_path = self.params.get('model_path', {}).get('value', '').strip()
        return model_path if model_path else LOCAL_MODEL_DIR

    def is_garbage(self, text, min_len=18):
        if not text:
            return False
        clean_text = "".join(text.split())
        if len(clean_text) < min_len:
            return False
        counts = Counter(clean_text)
        most_common = counts.most_common(1)
        char, count = most_common[0]
        unique_count = len(counts)
        if count / len(clean_text) > 0.6:
            self.logger.warning("Flagged: Single character dominance")
            return True
        if len(clean_text) > 30 and unique_count <= 4:
            self.logger.warning(f"Flagged: Low character diversity ({unique_count} unique chars)")
            return True
        if len(clean_text) > 30:
            top3_count = sum(c for _, c in counts.most_common(3))
            top3_ratio = top3_count / len(clean_text)
            if top3_ratio > 0.75:
                self.logger.warning(f"Flagged: Top-3 chars cover {top3_ratio:.0%} of text ({counts.most_common(3)})")
                return True
        if re.search(r'(.{1,6})\s*(\1[\s]*){19,}', text):
            self.logger.warning("Flagged: Repeated short pattern")
            return True
        return False

    def ocr_img(self, img: np.ndarray) -> str:
        self._load_model()

        task = self.get_param_value('task')
        prompt_text = self.PROMPTS.get(task, "OCR:")

        pil_img = Image.fromarray(img).convert("RGB")
        orig_w, orig_h = pil_img.size

        if task == "spotting" and orig_w < self.SPOTTING_UPSCALE_THRESHOLD and orig_h < self.SPOTTING_UPSCALE_THRESHOLD:
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                resample_filter = Image.LANCZOS
            pil_img = pil_img.resize((orig_w * 2, orig_h * 2), resample_filter)

        max_pixels = self.MAX_PIXELS.get(task, 1280 * 28 * 28)
        min_pixels = self.processor.image_processor.size.get(
            "shortest_edge",
            self.processor.image_processor.size.get("min_pixels", 112896)
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_img},
                    {"type": "text", "text": prompt_text},
                ],
            }
        ]

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            inputs = self.processor.apply_chat_template(
                messages,
                chat_template=self._CHAT_TEMPLATE,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                images_kwargs={
                    "size": {
                        "shortest_edge": min_pixels,
                        "longest_edge": max_pixels,
                    },
                },
            )
        inputs = {k: v.to(self.model.device) if isinstance(v, torch.Tensor) else v
                  for k, v in inputs.items()}

        with torch.inference_mode():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=self.get_param_value("max_new_tokens"),
                do_sample=False,
            )

        new_tokens = generated[:, inputs["input_ids"].shape[-1]:]
        answer = self.processor.batch_decode(new_tokens, skip_special_tokens=True)[0]
        answer = answer.strip()

        if self.is_garbage(answer):
            raise Exception(f"Garbage OCR output: {answer}")

        return answer

    def _load_model(self):
        if self.model is not None and self.processor is not None:
            return

        self._ensure_default_rope()

        model_dir = self._get_model_dir()
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32

        attn_impl = self.get_param_value('attn_implementation')
        load_kwargs = {}
        if attn_impl == "flash_attention_2":
            load_kwargs["attn_implementation"] = "flash_attention_2"

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Unrecognized keys in .rope_parameters.")
            warnings.filterwarnings("ignore", message="`torch_dtype` is deprecated")
            warnings.filterwarnings("ignore", message="`PaddleOCRVLProcessor` defines")
            model = AutoModelForImageTextToText.from_pretrained(
                model_dir,
                dtype=dtype,
                **load_kwargs
            ).to(self.device).eval()

        processor = AutoProcessor.from_pretrained(model_dir)

        try:
            if getattr(model, "generation_config", None) is not None:
                if model.generation_config.pad_token_id is None:
                    model.generation_config.pad_token_id = processor.tokenizer.eos_token_id
        except Exception:
            pass

        self.model = model
        self.processor = processor

        self.module_init_report = {
            'module': 'PaddleOCRVL16',
            'device': self.device,
            'model_dir': model_dir,
            'success': True,
        }

    def _ocr_blk_list(self, img: np.ndarray, blk_list: List[TextBlock], *args, **kwargs):
        im_h, im_w = img.shape[:2]
        for blk in blk_list:
            x1, y1, x2, y2 = blk.absBounding_rect()
            x1 = int(max(0, x1 - 10))
            x2 = int(min(im_w, x2 + 10))
            y1 = int(max(0, y1 - 2))
            y2 = int(min(im_h, y2 + 5))
            if y2 < im_h and x2 < im_w and x1 > 0 and y1 > 0 and x1 < x2 and y1 < y2:
                region = img[y1:y2, x1:x2]
                try:
                    answer = self.ocr_img(region)
                    blk.text = answer
                except Exception as e:
                    self.logger.error(f"_ocr_blk_list: {e}", exc_info=self.debug_mode)
                    blk.text = ['']
            else:
                self.logger.warning('invalid textbbox to target img')
                blk.text = ['']

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if param_key == 'model_path':
            self.model = None
            self.processor = None
            return
        device = self.params['device']['value']
        if self.device != device and self.model is not None:
            try:
                self.model.to(device)
            except Exception as e:
                self.logger.error(f"Failed to move model to device {device}: {e}")
        self.device = device


if __name__ == "__main__":
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

    import numpy as _np
    import torch as _torch
    from PIL import Image as _Image

    TEST_IMAGE = r"j:\Comic translate\OCR_bench\test_data\en\Archie & Friends - Summer Vacation 001-003_0.png"
    EXPECTED = "HEY, KIDS! I FIGURED, IF I CAN'T BRING THE BEACH CROWD TO ME, I'LL COME TO YOU"

    _device = "cuda" if _torch.cuda.is_available() else "cpu"
    print(f"Using device: {_device}")

    _img = _np.array(_Image.open(TEST_IMAGE).convert("RGB"))
    _ocr = PaddleOCRVL16(device=_device)
    _result = _ocr.ocr_img(_img)
    print("OUTPUT:", repr(_result))
    print("CONTAINS EXPECTED:", EXPECTED.upper() in _result.upper())
