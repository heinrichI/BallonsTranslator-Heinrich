import re
from transformers import AutoModelForCausalLM, AutoProcessor
import numpy as np
import torch
from typing import List

from .base import OCRBase, register_OCR, DEFAULT_DEVICE, DEVICE_SELECTOR, TextBlock

from modules.ocr.mit48px_ctc import OCR48pxCTC
from utils.textblock import collect_textblock_regions

from modules.ocr.utils import is_garbage_text

# MODEL_PATH = 'j:/Comic translate/PaddleOCR-VL-For-Manga/PaddleOCR-VL'
# MODEL_PATH = 'j:/Comic translate/PaddleOCR-VL-For-Manga/Archie-0.0004'
MODEL_PATH = 'j:/Comic translate/PaddleOCR-VL-For-Manga/Empowered-0.0071'


@register_OCR('PaddleOCRVLMyColor')
class PaddleOCRVLMy(OCRBase):
    params = {
        'device': DEVICE_SELECTOR(),
        "max_new_tokens": {
            "value": 1024,
            "description": "Max generation tokens"
        },
        "model_path": {
            "value": "",
            "description": "Path to PaddleOCR-VL.",
        },
    }
    device = DEFAULT_DEVICE

    _load_model_keys = {'model', 'processor'}

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.device = self.params['device']['value']
        self.model = None
        self.processor = None
        self.mit_model: OCR48pxCTC = None

    def is_garbage(self, text, min_len=18):
        return is_garbage_text(text, min_len=min_len, logger=self.logger)

    def ocr_img(self, img: np.ndarray) -> str:
        # save ballons
        # from datetime import datetime
        # timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # from PIL import Image
        # pil_img = Image.fromarray(img)
        # pil_img.save(f"{timestamp}.png")

        # Prepare the prompt
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": "OCR:"},
                ],
            }
        ]

        # Process inputs
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[text], images=[img], return_tensors="pt")
        inputs = {
            k: (v.to(self.model.device) if isinstance(v, torch.Tensor) else v)
            for k, v in inputs.items()
        }

        # Generate text
        with torch.inference_mode():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=self.get_param_value('max_new_tokens'),
                do_sample=False,
                use_cache=False
            )

        input_length = inputs["input_ids"].shape[1]
        generated_tokens = generated[:, input_length:]
        answer = self.processor.batch_decode(generated_tokens, skip_special_tokens=True)[0]

        #  if pcfg.restore_ocr_empty:
        if self.is_garbage(answer):
            # return ''
            raise Exception(f"Garbage OCR output: {answer}")
        # return answer.split('\n')
        # return answer.replace('\n', ' ')
        return answer

    def _load_model(self):
        if self.model is None:
            if not self.params['model_path']['value'] or not self.params['model_path']['value'].strip():
                  self.logger.warning("Model path is empty, None, or just whitespace.")
                  return
            model = AutoModelForCausalLM.from_pretrained(
                self.params['model_path']['value'],
                trust_remote_code=True,
                dtype=torch.float16 if self.device == "cuda" else torch.float32
                # dtype=torch.bfloat16,
            ).to(self.device).eval()

            processor = AutoProcessor.from_pretrained(
                MODEL_PATH, trust_remote_code=True, use_fast=True
            )

            # Set pad_token_id to avoid warning during generation
            if model.generation_config.pad_token_id is None:
                model.generation_config.pad_token_id = processor.tokenizer.eos_token_id

            self.model = model
            self.processor = processor
        if self.mit_model is None:
            self.mit_model = OCR48pxCTC(r'data/models/mit48pxctc_ocr.ckpt', self.device)

    def _ocr_blk_list(self, img: np.ndarray, blk_list: List[TextBlock], *args, **kwargs):
        # import debugpy
        # debugpy.debug_this_thread()
        # debugpy.breakpoint()

        regions, textblk_lst_indices = collect_textblock_regions(img, blk_list, self.mit_model.text_height, self.mit_model.maxwidth, False, None)
        self.mit_model(blk_list, regions, textblk_lst_indices, chunk_size=16)
    
        im_h, im_w = img.shape[:2]
        for blk in blk_list:
            x1, y1, x2, y2 = blk.absBounding_rect()
            # pad
            x1 = int(max(0, x1 - 10))
            x2 = int(min(im_w, x2 + 10))
            y1 = int(max(0, y1 - 2))
            y2 = int(min(im_h, y2 + 5))
            # try:
            if x1 < x2 and y1 < y2: 
                # Extract region and convert RGBA to RGB if necessary for model input
                region = img[y1:y2, x1:x2]
                answer = self.ocr_img(region)
                blk.text = answer
            else:
                self.logger.warning('invalid textbbox to target img')
                blk.text = ['']
            # except Exception as e:
                # import debugpy
                # debugpy.debug_this_thread()
                # debugpy.breakpoint()
                # if self.logger:
                #     self.logger.error(
                #         f"_ocr_blk_list: {e}", exc_info=self.debug_mode)

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if param_key == 'model_path':
            # Eagerly reload model when model_path changes.
            try:
                if self.model is not None:
                    try:
                        del self.model
                    except Exception:
                        pass
                self.model = None
                self.processor = None
                # reset mit_model so it will be recreated on next load
                try:
                    if getattr(self, 'mit_model', None) is not None:
                        del self.mit_model
                except Exception:
                    pass
                self.mit_model = None
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                try:
                    self._load_model()
                    # Log successful reload
                    try:
                        self.logger.info(f"Reloaded OCR model from {self.params.get('model_path', {}).get('value', '').strip() or MODEL_PATH}")
                    except Exception:
                        pass
                except Exception:
                    raise
            except Exception as e:
                self.logger.error(f"Failed to load model from new model_path: {e}", exc_info=self.debug_mode)
                self.model = None
                self.processor = None
                self.mit_model = None
                self.module_init_report = {
                    'module': 'PaddleOCRVLMyColor',
                    'device': self.device,
                    'model_dir': self.params.get('model_path', {}).get('value', '').strip() or MODEL_PATH,
                    'success': False,
                    'error': str(e),
                }
            return
        device = self.params['device']['value']
        if self.device != device and self.model is not None:
            try:
                self.model.to(device)
            except Exception as e:
                self.logger.error(f"Failed to move model to device {device}: {e}")
        self.device = device


