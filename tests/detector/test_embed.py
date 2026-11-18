from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from detector import embed
from detector.data import Sample


def _sample(tmp_path: Path, i: int, height: int = 1830) -> Sample:
    rng = np.random.default_rng(i)
    arr = rng.integers(0, 255, (height // 10, 824 // 10, 3), dtype=np.uint8)
    im = Image.fromarray(arr).resize((824, height), Image.NEAREST)
    p = tmp_path / f"s{i}.png"
    im.save(p)
    return Sample(f"id{i}", "normal", 0, f"d{i}.com", f"h{i}", None, p)


class _FakeProc:
    def __call__(self, images, return_tensors):
        px = torch.stack([torch.tensor(np.asarray(im.resize((8, 8))), dtype=torch.float32).permute(2, 0, 1) for im in images])
        return {"pixel_values": px}


class _FakeModel:
    def __init__(self):
        self.calls = 0
        self.proj = torch.nn.Linear(192, 512)

    def get_image_features(self, pixel_values):
        self.calls += 1
        return self.proj(pixel_values.flatten(1))


def test_embed_shape_and_norm(tmp_path):
    samples = [_sample(tmp_path, i) for i in range(3)]
    out = embed.embed_images(samples, tmp_path / "cache", device="cpu")
    assert out.shape == (3, 512) and out.dtype == np.float32
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-4)


def test_embed_cache_resume(tmp_path, monkeypatch):
    fake = _FakeModel()
    monkeypatch.setattr(embed, "_load_model", lambda name, device: (fake, _FakeProc()))
    samples = [_sample(tmp_path, i) for i in range(3)]
    first = embed.embed_images(samples, tmp_path / "cache", device="cpu")
    n = fake.calls
    assert n > 0
    second = embed.embed_images(samples, tmp_path / "cache", device="cpu")
    assert fake.calls == n
    assert np.array_equal(first, second)


def test_short_image_single_tile(tmp_path):
    out = embed.embed_images([_sample(tmp_path, 0, height=900)], tmp_path / "cache", device="cpu")
    assert out.shape == (1, 512)
