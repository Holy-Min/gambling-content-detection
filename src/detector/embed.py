"""이미지 임베딩(첫 화면 타일 평균)과 id 단위 .npy 캐시. 기본은 CLIP, `ENCODERS` 로 다른 특징 추출기를 고른다."""
from __future__ import annotations

import time
from dataclasses import dataclass
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
    return _tiles_2v(first_screen(sample.image_path))


def _tiles_2v(im):
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


# ---- 특징 추출기 등록(비교용). 위의 embed_images 와 캐시(_features/clip)는 그대로 둔다. ----

@dataclass(frozen=True)
class EncoderSpec:
    kind: str  # clip | siglip | dinov2 | open_clip
    model: str
    tiles: str  # 2v | grid6 | grid8
    pretrained: str | None = None


ENCODERS: dict[str, EncoderSpec] = {
    "clip-b32": EncoderSpec("clip", "openai/clip-vit-base-patch32", "2v"),
    "clip-b32-grid6": EncoderSpec("clip", "openai/clip-vit-base-patch32", "grid6"),
    "clip-b32-grid8": EncoderSpec("clip", "openai/clip-vit-base-patch32", "grid8"),
    "siglip2-b16": EncoderSpec("siglip", "google/siglip2-base-patch16-224", "2v"),
    "dinov2-s": EncoderSpec("dinov2", "facebook/dinov2-small", "2v"),
    "dinov2-b": EncoderSpec("dinov2", "facebook/dinov2-base", "2v"),
    "mobileclip2-s2": EncoderSpec("open_clip", "MobileCLIP2-S2", "2v", pretrained="dfndr2b"),
}
# 비교 후보. dinov2·grid 항목은 ENCODERS 에 재현용으로만 남긴다.
DEFAULT_COMPARE_ENCODERS = ("clip-b32", "siglip2-b16", "mobileclip2-s2")
GRID_COLS, GRID_ROWS = 2, 3


def grid6_tiles(im) -> list:
    """첫 화면을 2열×3행으로 자른다. 나머지 픽셀은 마지막 열·행에 넣는다.
    행 수는 높이를 610px(=1830/3)로 나눈 몫(1~3). 915px 이하로 짧으면 1행."""
    rows = 1 if im.height <= TILE_H else min(GRID_ROWS, max(1, im.height // (1830 // GRID_ROWS)))
    cw, rh = im.width // GRID_COLS, im.height // rows
    tiles = []
    for r in range(rows):
        y0, y1 = r * rh, (im.height if r == rows - 1 else (r + 1) * rh)
        for c in range(GRID_COLS):
            x0, x1 = c * cw, (im.width if c == GRID_COLS - 1 else (c + 1) * cw)
            tiles.append(im.crop((x0, y0, x1, y1)))
    return tiles


def grid8_tiles(im) -> list:
    """첫 화면을 2열×N행으로 자른다(N = round(높이/(너비/2)), 최소 1). 타일이 정사각형에 가깝다.
    균등 분할이고 나머지 픽셀은 마지막 열·행에 넣는다."""
    cw0 = im.width // GRID_COLS
    rows = max(1, round(im.height / (im.width / GRID_COLS)))
    rh = im.height // rows
    tiles = []
    for r in range(rows):
        y0, y1 = r * rh, (im.height if r == rows - 1 else (r + 1) * rh)
        for c in range(GRID_COLS):
            x0, x1 = c * cw0, (im.width if c == GRID_COLS - 1 else (c + 1) * cw0)
            tiles.append(im.crop((x0, y0, x1, y1)))
    return tiles


def _as_tensor(out) -> torch.Tensor:
    if isinstance(out, torch.Tensor):
        return out
    return out.pooler_output  # 신버전 transformers 는 출력 객체를 돌려줌


class _Encoder:
    """타일 목록 → (타일 수, 차원) 특징. 모델·전처리기는 각 라이브러리 공식 것을 쓴다."""

    def __init__(self, spec: EncoderSpec, device: str):
        self.spec, self.device = spec, device
        if spec.kind == "clip":
            self.model, self.proc = _load_model(spec.model, device)
        elif spec.kind == "siglip":
            from transformers import AutoModel, AutoProcessor

            self.model = AutoModel.from_pretrained(spec.model).to(device).eval()
            self.proc = AutoProcessor.from_pretrained(spec.model)
        elif spec.kind == "dinov2":
            from transformers import AutoImageProcessor, AutoModel

            self.model = AutoModel.from_pretrained(spec.model).to(device).eval()
            self.proc = AutoImageProcessor.from_pretrained(spec.model)
        elif spec.kind == "open_clip":
            import open_clip

            model, _, self.proc = open_clip.create_model_and_transforms(spec.model, pretrained=spec.pretrained)
            self.model = model.to(device).eval()
        else:
            raise ValueError(f"unknown encoder kind: {spec.kind}")

    def encode(self, tiles: list) -> np.ndarray:
        kind = self.spec.kind
        with torch.no_grad():
            if kind == "open_clip":
                px = torch.stack([self.proc(t) for t in tiles]).to(self.device)
                feats = self.model.encode_image(px)
            else:
                px = self.proc(images=tiles, return_tensors="pt")["pixel_values"].to(self.device)
                if kind == "dinov2":
                    feats = self.model(pixel_values=px).last_hidden_state[:, 0]
                else:
                    feats = _as_tensor(self.model.get_image_features(pixel_values=px))
        return feats.float().cpu().numpy()

    def _vision_module(self):
        kind = self.spec.kind
        if kind == "open_clip":
            return [self.model.visual]
        if kind == "clip":
            return [self.model.vision_model, self.model.visual_projection]
        if kind == "siglip":
            return [self.model.vision_model]
        return [self.model]

    def n_params(self) -> int:
        return int(sum(p.numel() for m in self._vision_module() for p in m.parameters()))


def _tile_fn(spec: EncoderSpec):
    return {"grid6": grid6_tiles, "grid8": grid8_tiles}.get(spec.tiles, _tiles_2v)


def _spec(key: str) -> EncoderSpec:
    if key not in ENCODERS:
        raise ValueError(f"unknown encoder {key!r}; choose from {', '.join(ENCODERS)}")
    return ENCODERS[key]


def embed_with(samples: list[Sample], feats_root: Path, key: str, device: str | None = None) -> np.ndarray:
    """key 의 특징 추출기로 samples 를 임베딩. clip-b32 는 기존 `_features/clip`, 나머지는 `_features/img/<key>`."""
    spec = _spec(key)
    if key == "clip-b32":
        return embed_images(samples, Path(feats_root) / "clip", spec.model, device)
    cache_dir = Path(feats_root) / "img" / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    todo = [s for s in samples if not (cache_dir / f"{s.id}.npy").exists()]
    if todo:
        enc = _Encoder(spec, device or _default_device())
        tile = _tile_fn(spec)
        for s in todo:
            feats = enc.encode(tile(first_screen(s.image_path)))
            vec = _normalize(feats.mean(axis=0)).astype(np.float32)
            tmp = cache_dir / f"{s.id}.tmp.npy"
            np.save(tmp, vec)
            tmp.replace(cache_dir / f"{s.id}.npy")
    if not samples:
        return np.zeros((0, 0), dtype=np.float32)
    return np.stack([np.load(cache_dir / f"{s.id}.npy") for s in samples]).astype(np.float32)


def encoder_info(key: str, device: str | None = None) -> dict:
    """이미지 쪽 파라미터 수(vision tower 만)와 특징 차원."""
    spec = _spec(key)
    enc = _Encoder(spec, device or _default_device())
    from PIL import Image

    dim = int(enc.encode([Image.new("RGB", (224, 224))]).shape[1])
    return {"n_params_image": enc.n_params(), "dim": dim}


def time_encoder(samples: list[Sample], key: str, device: str | None = None, k: int = 20) -> float:
    """예열 1회 뒤 화면 k개의 중앙값 ms/화면(타일 나누기+전처리+추론). 캐시는 쓰지 않는다."""
    spec = _spec(key)
    enc = _Encoder(spec, device or _default_device())
    tile = _tile_fn(spec)
    ims = [first_screen(s.image_path) for s in samples[:k]]  # PNG 읽기는 시간에서 뺀다
    if not ims:
        return float("nan")
    enc.encode(tile(ims[0]))
    ts = []
    for im in ims:
        t0 = time.perf_counter()
        enc.encode(tile(im))
        ts.append((time.perf_counter() - t0) * 1000)
    return float(np.median(ts))
