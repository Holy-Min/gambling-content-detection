from pathlib import Path

import numpy as np
from PIL import Image

from detector.data import Sample
from detector.report import data_notes, score_scenario, seed_variability
from detector.split import make_folds


def _synthetic(n_dom=40, per=2):
    rng = np.random.default_rng(1)
    samples, texts, y, label, kind = [], [], [], [], []
    for d in range(n_dom):
        lab = ["gambling", "hard_negative", "normal", "hard_negative"][d % 4]
        for j in range(per):
            yy = int(lab == "gambling")
            samples.append(Sample(f"{d}-{j}", lab, yy, f"d{d}.com", f"h{d}", "deposit" if (yy and j == 0) else "", Path("x.png")))
            texts.append(("slot casino bet " if yy else "shop game pay ") + " ".join(rng.choice(list("abcdefgh"), 3)))
            y.append(yy), label.append(lab), kind.append("deposit" if (yy and j == 0) else "")
    X = rng.normal(size=(len(y), 6)) + np.array(y)[:, None] * 0.8
    return samples, texts, X, np.array(y), np.array(label, dtype=object), np.array(kind, dtype=object)


def test_seed_variability_ordering_and_headline_row():
    samples, texts, X, y, label, kind = _synthetic()
    groups = np.array([s.domain for s in samples])
    out = seed_variability(samples, texts, X, y, label, kind, {"domain": groups}, seeds=[42, 0, 1])
    entry = out["domain"]
    assert entry["seeds"] == [42, 0, 1]
    for name in ("text", "image", "fusion"):
        for stat in entry["models"][name].values():
            assert stat["min"] <= stat["median"] <= stat["max"]
    # seed 42 행은 헤드라인(score_scenario) 점추정과 같아야 한다
    from detector.models import oof_predict
    P = oof_predict(texts, X, y, make_folds(samples, groups=groups, seed=42))
    head = score_scenario(y, label, kind, P, groups, n_boot=5)
    for name in ("text", "image", "fusion"):
        m = entry["models"][name]
        assert m["f1"]["seed42"] == head["models"][name]["f1"][0]
        assert m["fpr_hard_negative"]["seed42"] == head["models"][name]["fpr_hard_negative"][0]
        assert m["recall_at_fpr2"]["seed42"] == head["models"][name]["recall_at_fpr2"]


def test_data_notes_counts_blank_and_wide(tmp_path):
    def mk(name, size, color):
        p = tmp_path / name
        Image.new("RGB", size, color).save(p)
        return p
    ph = mk("a.png", (400, 800), (255, 255, 255))      # 흰 화면
    wide = mk("b.png", (1300, 800), (10, 20, 30))
    ok = Image.effect_noise((400, 800), 60).convert("RGB")
    okp = tmp_path / "c.png"
    ok.save(okp)
    S = [Sample("1", "gambling", 1, "a", "ha", None, ph), Sample("2", "hard_negative", 0, "b", "hb", None, wide),
         Sample("3", "hard_negative", 0, "c", "hc", None, okp)]
    ocr = {"1": {"text": "abc"}, "2": {"text": "abc"}, "3": {"text": ""}}
    P = {"domain": {"fusion": np.array([0.9, 0.9, 0.1])}, "mirror_cluster": {"fusion": np.array([0.9, 0.1, 0.1])}}
    n = data_notes(S, ocr, P)
    assert n["blank_screens"] == {"gambling": 1, "hard_negative": 2}
    w = n["hard_negative_wide"]
    assert w["screens"] == 1 and w["fpr_fusion"]["domain"]["wide"] == 1.0
    assert w["fpr_fusion"]["domain"]["phone"] == 0.0


def _spread_stub(lo, mid, hi):
    return {"min": lo, "median": mid, "max": hi, "seed42": mid}


def _metrics_stub():
    st = {s: _spread_stub(0.1, 0.2, 0.3) for s in ("f1", "fpr_hard_negative", "fpr_normal", "recall_deposit", "recall_at_fpr2")}
    sc = {"seeds": [42, 0], "models": {k: st for k in ("text", "image", "fusion")}, "fusion_gain_f1": _spread_stub(-0.03, -0.02, -0.01)}
    return {
        "seed_variability": {"domain": sc, "mirror_cluster": sc},
        "data_notes": {
            "blank_screens": {"gambling": 3, "hard_negative": 1},
            "hard_negative_wide": {"screens": 31, "of": 138, "domains": 7, "min_width_px": 1000,
                                   "fpr_fusion": {"domain": {"wide": 0.032, "phone": 0.187},
                                                  "mirror_cluster": {"wide": 0.129, "phone": 0.168}}},
        },
    }


def test_variability_and_notes_markdown():
    from detector.report import _notes_md, _variability_md
    md = "\n".join(_variability_md(_metrics_stub()))
    assert "seed 42 는 미리 정한 값" in md and "0.100~0.300 (0.200)" in md and "-0.030~-0.010" in md
    notes = "\n".join(_notes_md(_metrics_stub()))
    assert "31쪽(7개 도메인)" in notes and "A 3.2%" in notes and "B 16.8%" in notes
    assert "빈" in notes and "4쪽(도박 3, 하드 네거티브 1)" in notes
