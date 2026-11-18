"""CLIP 이미지 임베딩(첫 화면 위·아래 두 타일 평균)과 id 단위 .npy 캐시."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from detector.data import Sample, first_screen

TILE_H = 915


def _load_model(model_name: str, device: str):
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained(model_name).to(device).eval()
    return model, CLIPProcessor.from_pretrained(model_name)


def _default_device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _tiles(sample: Sample):
    im = first_screen(sample.image_path)
    if im.height <= TILE_H:
        return [im]
    return [
        im.crop((0, 0, im.width, TILE_H)),
        im.crop((0, TILE_H, im.width, min(2 * TILE_H, im.height))),
    ]


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-12)


def embed_images(
    samples: list[Sample],
    cache_dir: Path,
    model_name: str = "openai/clip-vit-base-patch32",
    device: str | None = None,
) -> np.ndarray:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    device = device or _default_device()
    todo = [s for s in samples if not (cache_dir / f"{s.id}.npy").exists()]
    if todo:
        model, processor = _load_model(model_name, device)
        for s in todo:
            inputs = processor(images=_tiles(s), return_tensors="pt")
            with torch.no_grad():
                feats = model.get_image_features(pixel_values=inputs["pixel_values"].to(device))
            if not isinstance(feats, torch.Tensor):  # 신버전 transformers 는 출력 객체를 돌려줌
                feats = feats.pooler_output
            feats = feats.float().cpu().numpy()
            vec = _normalize(feats.mean(axis=0)).astype(np.float32)
            tmp = cache_dir / f"{s.id}.tmp.npy"
            np.save(tmp, vec)
            tmp.replace(cache_dir / f"{s.id}.npy")  # 중간 끊김에도 깨진 캐시가 남지 않게
    if not samples:
        return np.zeros((0, 512), dtype=np.float32)
    return np.stack([np.load(cache_dir / f"{s.id}.npy") for s in samples]).astype(np.float32)
