import cv2
import numpy as np
import torch
from typing import List

from .base import InpainterBase, register_inpainter, DEFAULT_DEVICE, DEVICE_SELECTOR, soft_empty_cache
from ..textdetector import TextBlock


@register_inpainter('flux2_klein')
class Flux2KleinInpainter(InpainterBase):
    inpaint_by_block = False
    check_need_inpaint = False

    params = {
        'device': DEVICE_SELECTOR(),
        'step': 8,
        'max_resolution': {
            'type': 'selector',
            'options': [512, 768, 1024, 1280, 1536, 2048],
            'value': 1024
        },
    }

    download_file_list = [
        {
            'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/model_index.json',
            'files': 'data/models/flux-2-klein-4b/model_index.json',
        },
        {
            'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/scheduler/scheduler_config.json',
            'files': 'data/models/flux-2-klein-4b/scheduler/scheduler_config.json'
        },
        {
            'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/transformer/config.json',
            'files': 'data/models/flux-2-klein-4b/transformer/config.json',
        },
        {
            'url': 'https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF/resolve/main/flux-2-klein-4b-Q4_K_M.gguf',
            'files': 'data/models/flux-2-klein-4b-Q4_K_M.gguf',
            'sha256_pre_calculated': '0b25d143c8469b342bc5af3bce92b783bf6b0636d285f7b2f75e38af63af9a15'
        },
        {
            'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/vae/config.json',
            'files': 'data/models/flux-2-vae/config.json',
        },
        {
            'url': 'https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/resolve/main/vae/diffusion_pytorch_model.safetensors',
            'files': 'data/models/flux-2-vae/diffusion_pytorch_model.safetensors',
            'sha256_pre_calculated': 'ca70d2202afe6415bdbcb8793ba8cd99fd159cfe6192381504d6c4d3036e0f04'
        },
        {
            'url': 'https://huggingface.co/dreMaz/flux2-klein-inpaint/resolve/main/flux2_inpaint_prompt.safetensors',
            'files': 'data/models/flux2_inpaint_prompt.safetensors',
            'sha256_pre_calculated': '7d7b19ec266581cb1faa51ad92f49a302932b0c589feae633f97da2d925cb6a4'
        }
    ]

    _load_model_keys = {'pipe'}

    def __init__(self, **params) -> None:
        super().__init__(**params)
        self.device = self.get_param_value('device')
        self.pipe = None
        self.prompt_embeds = None

    def _load_model(self):
        from safetensors.torch import load_file
        from diffusers import GGUFQuantizationConfig
        from .flux_inpaint_pipeline import Flux2KleinInpaintPipeline, Flux2Transformer2DModel, AutoencoderKLFlux2

        device = self.get_param_value('device')
        dtype = torch.bfloat16

        transformer = Flux2Transformer2DModel.from_single_file(
            "data/models/flux-2-klein-4b-Q4_K_M.gguf",
            quantization_config=GGUFQuantizationConfig(compute_dtype=dtype),
            torch_dtype=dtype,
            config='data/models/flux-2-klein-4b/transformer/config.json',
        )
        self.prompt_embeds = load_file('data/models/flux2_inpaint_prompt.safetensors')['prompt_embeds'].to(dtype=dtype, device=device)

        vae = AutoencoderKLFlux2.from_pretrained('data/models/flux-2-vae').to(device=device, dtype=dtype)
        self.pipe = Flux2KleinInpaintPipeline.from_pretrained(
            pretrained_model_name_or_path='data/models/flux-2-klein-4b',
            text_encoder=None,
            tokenizer=None,
            vae=vae,
            transformer=transformer,
            local_files_only=True
        )
        self.pipe.to(device=device)

    @torch.no_grad()
    def _inpaint(self, img: np.ndarray, mask: np.ndarray, textblock_list: List[TextBlock] = None):
        max_resolution = self.get_param_value('max_resolution')
        div = 16
        h, w = img.shape[:2]
        resize_ratio = max_resolution / max(h, w)
        if resize_ratio < 1:
            h, w = int(round(resize_ratio * h)), int(round(resize_ratio * w))
        h = int(round(h / div)) * div
        w = int(round(w / div)) * div

        img_resized = cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4)
        mask_resized = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

        result = self.pipe(
            image=img_resized,
            mask=mask_resized,
            prompt_embeds=self.prompt_embeds,
            height=h,
            width=w,
            num_inference_steps=int(self.get_param_value('step')),
            guidance_scale=1,
            return_dict=False,
            output_type='numpy'
        )
        result_img = (np.round(result[0] * 255)).astype(np.uint8)
        if result_img.shape[:2] != (img.shape[0], img.shape[1]):
            result_img = cv2.resize(result_img, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LANCZOS4)
        return result_img

    def moveToDevice(self, device: str, precision: str = None):
        if self.pipe is not None:
            self.pipe.to(device)
        self.device = device
        if self.prompt_embeds is not None:
            self.prompt_embeds = self.prompt_embeds.to(device)

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if param_key == 'device':
            self.device = self.get_param_value('device')
            if self.pipe is not None:
                self.pipe.to(self.device)
            if self.prompt_embeds is not None:
                self.prompt_embeds = self.prompt_embeds.to(self.device)
