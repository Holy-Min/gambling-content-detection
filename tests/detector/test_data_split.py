import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from detector.data import Sample, first_screen, load_samples
from detector.split import make_folds

REAL_INDEX = Path.home() / "datasets/gambling/index.jsonl"


def _row(i, label, status="ok", domain="a.com", page_kind="home"):
    return {
        "id": f"id{i}", "label": label, "status": status, "domain": domain,
        "domain_hash": f"h{domain}", "page_kind": page_kind,
        "full_path": f"img/{i}.png" if status == "ok" else None,
    }


def test_load_samples_filters_ok_and_labels(tmp_path):
    rows = [
        _row(0, "gambling"),
        _row(1, "hard_negative", domain="b.com", page_kind=None),
        _row(2, "normal", domain="c.com"),
        _row(3, "embedded_banner", domain="d.com"),
        _row(4, "gambling", status="challenge"),
        _row(5, "normal", status="error", domain="e.com"),
    ]
    idx = tmp_path / "index.jsonl"
    idx.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    got = load_samples(idx, tmp_path)
    assert [s.id for s in got] == ["id0", "id1", "id2"]
    assert [s.y for s in got] == [1, 0, 0]
    assert got[0].image_path == tmp_path / "img/0.png"
    assert got[1].page_kind is None

    with_emb = load_samples(idx, tmp_path, include_embedded=True)
    emb = [s for s in with_emb if s.label == "embedded_banner"]
    assert len(with_emb) == 4 and len(emb) == 1 and emb[0].y is None


def test_first_screen_short_and_rgba(tmp_path):
    Image.new("RGB", (824, 3000), "white").save(tmp_path / "tall.png")
    Image.new("RGBA", (824, 900), (255, 0, 0, 128)).save(tmp_path / "rgba.png")
    Image.new("P", (824, 500)).save(tmp_path / "pal.png")

    assert first_screen(tmp_path / "tall.png").size == (824, 1830)
    rgba = first_screen(tmp_path / "rgba.png")
    assert rgba.size == (824, 900) and rgba.mode == "RGB"
    pal = first_screen(tmp_path / "pal.png")
    assert pal.mode == "RGB" and pal.size == (824, 500)


def _sample(i, domain, y):
    return Sample(f"s{i}", "gambling" if y else "normal", y, domain, domain, None, Path("x.png"))


def test_folds_never_share_domain():
    samples = []
    n = 0
    for d in range(12):
        y = 1 if d < 6 else 0
        for _ in range(1 + d % 3):
            samples.append(_sample(n, f"d{d}.com", y))
            n += 1
    folds = make_folds(samples)
    assert len(folds) == len(samples)
    by_domain = defaultdict(set)
    for s, f in zip(samples, folds):
        by_domain[s.domain].add(int(f))
    assert all(len(v) == 1 for v in by_domain.values())


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="real dataset not present")
def test_every_fold_has_both_classes():
    samples = load_samples(REAL_INDEX, REAL_INDEX.parent)
    folds = make_folds(samples, k=5, seed=42)
    y = np.array([s.y for s in samples])
    assert set(folds.tolist()) == set(range(5))
    for f in range(5):
        assert (y[folds == f] == 1).sum() >= 1
        assert (y[folds == f] == 0).sum() >= 1


def test_make_folds_rejects_unlabeled():
    samples = [_sample(0, "a.com", 1), _sample(1, "b.com", None)]
    with pytest.raises(ValueError, match="y is None"):
        make_folds(samples)


def test_make_folds_custom_groups_keep_groups_together():
    samples = []
    n = 0
    for d in range(12):
        y = 1 if d < 6 else 0
        for _ in range(3):
            samples.append(_sample(n, f"d{d}.com", y))
            n += 1
    # 도메인 2개씩 한 그룹(미러 묶음)
    groups = np.array([int(s.domain[1:-4]) // 2 for s in samples])
    folds = make_folds(samples, groups=groups)
    by_group = defaultdict(set)
    for g, f in zip(groups, folds):
        by_group[g].add(int(f))
    assert all(len(v) == 1 for v in by_group.values())
