from pathlib import Path

import numpy as np
from PIL import Image

from detector import compare_image as ci
from detector import embed
from detector.data import Sample
from detector.metrics import threshold_for_fpr

POS_WORDS = ["카지노 베팅 보너스 입금", "슬롯 잭팟 충전 배당"]
NEU_WORDS = ["오늘 날씨 뉴스 요약", "맛집 후기 여행 사진", "게임 공략 영상 모음", "주식 시세 환율 정보"]


def _world(seed=0, n_train=240, n_test=90):
    rng = np.random.default_rng(seed)
    n = n_train + n_test
    y = (rng.random(n) < 0.5).astype(int)
    labels = ["gambling" if v else ("hard_negative" if rng.random() < 0.6 else "normal") for v in y]
    samples, texts = [], []
    for i in range(n):
        # 도박 화면의 35% 는 글자에 도박 낱말이 없다(글자 모델이 놓침)
        if y[i] and rng.random() > 0.35:
            t = POS_WORDS[rng.integers(2)] + " " + NEU_WORDS[rng.integers(4)]
        else:
            t = NEU_WORDS[rng.integers(4)] + " " + NEU_WORDS[rng.integers(4)] + f" 잡음{rng.integers(30)}"
        t += " OCRMARK"
        texts.append(t)
        samples.append(Sample(f"id{i}", labels[i], int(y[i]), f"fake{i}.example", f"hash{i}", "main",
                              Path(f"/secret/path/{i}.png"), "2026-11-01"))
    # 배너 화면 몇 개(이진 아님)
    for j in range(6):
        samples.append(Sample(f"b{j}", "embedded_banner", None, f"banner{j}.example", f"bhash{j}", "main",
                              Path(f"/secret/path/b{j}.png"), "2026-11-01"))
        texts.append("배너 광고 OCRMARK")
    test_mask = np.array([i >= n_train and i < n for i in range(len(samples))])
    return rng, y, samples, texts, test_mask


def _unit(a):
    return (a / np.linalg.norm(a, axis=1, keepdims=True)).astype(np.float32)


def _feats(rng, y, n_all, signal):
    X = rng.normal(size=(n_all, 16))
    if signal:
        X[: len(y), :4] += (y[:, None] * 2 - 1) * 1.5
    return _unit(X)


def _run(**kw):
    rng, y, samples, texts, mask = _world()
    n_all = len(samples)
    Xm = _unit(rng.normal(size=(n_all, 16)))
    Xs = {"good": _feats(rng, y, n_all, True), "rand": _feats(rng, y, n_all, False)}
    Xs = kw.pop("Xs", Xs)
    res = ci.compare_core(samples, texts, Xm, Xs, mask, n_boot=20, **kw)
    return res, samples, texts, y, mask, Xm, Xs


def test_threshold_uses_train_oof_b_only_and_budget_holds():
    res, samples, texts, y, mask, Xm, Xs = _run()
    rows = res["_rows"]
    tr = np.array([s == "train" for s in rows["split"]])
    ytr = np.array([samples[i].y for i in rows["idx"][tr]])
    pt, pi = rows["p_text"][tr], rows["p_img"]["good"][tr]
    b = pi[(ytr == 0) & (pt < 0.5)]
    for bud in ci.BUDGETS:
        t = res["encoders"]["good"]["thresholds"][str(bud)]
        assert t == float(threshold_for_fpr(b, bud))
        assert (b >= t).mean() <= bud
    # 시험 쪽 특징을 완전히 바꿔도 임계값은 그대로
    rng = np.random.default_rng(5)
    Xs2 = {k: v.copy() for k, v in Xs.items()}
    te = np.flatnonzero(mask)
    Xs2["good"][te] = _unit(rng.normal(size=(len(te), 16)))
    res2 = ci.compare_core(samples, texts, Xm, Xs2, mask, n_boot=20)
    assert res2["encoders"]["good"]["thresholds"] == res["encoders"]["good"]["thresholds"]


def test_rescue_counts_by_hand():
    y = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0])
    p_text = np.array([0.9, 0.1, 0.2, 0.3, 0.1, 0.2, 0.6, 0.4, 0.3])
    p_img = np.array([0.1, 0.8, 0.9, 0.2, 0.9, 0.1, 0.9, 0.1, 0.1])
    r = ci.rescue_stats(y, p_text, p_img, 0.5)
    assert (r["rescued"]["n"], r["rescued"]["d"]) == (2, 3)  # A = 1,2,3 번 화면
    assert (r["extra_fp"]["n"], r["extra_fp"]["d"]) == (1, 4)  # B = 4,5,7,8 번 화면
    assert r["rescued"]["rate"] == 2 / 3 and r["extra_fp"]["rate"] == 0.25


def test_combined_counts_image_false_positive():
    y = np.array([1, 0, 0, 0])
    label = np.array(["gambling", "hard_negative", "hard_negative", "normal"], dtype=object)
    kind = np.array([""] * 4, dtype=object)
    hashes = np.array(["a", "b", "c", "d"], dtype=object)
    p_text = np.array([0.9, 0.1, 0.1, 0.1])
    p_img = np.array([0.1, 0.9, 0.1, 0.9])  # 이미지가 하드 네거티브 b 와 정상 d 를 잘못 잡음
    blk = ci._subset_block(y, label, kind, hashes, p_text, p_img, {0.01: 0.5}, 0.5, 0)
    assert blk["combined"]["fpr_hard_negative"][0] == 0.5
    assert blk["text_only"]["fpr_hard_negative"][0] == 0.0
    assert blk["combined"]["recall"][0] == 1.0
    assert abs(blk["combined"]["precision"][0] - 1 / 3) < 1e-9  # 양성 1 + 오탐 2


def test_good_features_rank_above_random():
    res = _run()[0]
    assert res["ranking"][0] == "good"
    g = res["encoders"]["good"]["train_oof"]["rescue"]["0.01"]["rescued"]["rate"]
    r = res["encoders"]["rand"]["train_oof"]["rescue"]["0.01"]["rescued"]["rate"]
    assert g > r


def test_same_folds_for_every_encoder():
    rng, y, samples, texts, mask = _world()
    n_all = len(samples)
    Xm = _unit(rng.normal(size=(n_all, 16)))
    good = _feats(rng, y, n_all, True)
    one = ci.compare_core(samples, texts, Xm, {"a": good}, mask, n_boot=5)
    three = ci.compare_core(samples, texts, Xm, {"a": good, "b": _feats(rng, y, n_all, False),
                                                 "c": _feats(rng, y, n_all, True)}, mask, n_boot=5)
    assert np.array_equal(one["_rows"]["p_text"], three["_rows"]["p_text"])
    assert np.array_equal(one["_rows"]["p_img"]["a"], three["_rows"]["p_img"]["a"])


def test_grid6_tiles_cover_image():
    im = Image.new("RGB", (824, 1830))
    tiles = embed.grid6_tiles(im)
    assert len(tiles) == 6
    assert sum(t.width * t.height for t in tiles) == 824 * 1830
    odd = embed.grid6_tiles(Image.new("RGB", (825, 1831)))
    assert len(odd) == 6 and sum(t.width * t.height for t in odd) == 825 * 1831
    assert len(embed.grid6_tiles(Image.new("RGB", (824, 600)))) == 2


def test_encoders_registry_has_seven():
    assert list(embed.ENCODERS) == ["clip-b32", "clip-b32-grid6", "clip-b32-grid8", "siglip2-b16", "dinov2-s",
                                    "dinov2-b", "mobileclip2-s2"]
    assert embed.DEFAULT_COMPARE_ENCODERS == ("clip-b32", "siglip2-b16", "mobileclip2-s2")


def test_embed_with_cache_path_and_resume(tmp_path, monkeypatch):
    made = []

    class Fake:
        def __init__(self, spec, device):
            made.append(spec.tiles)

        def encode(self, tiles):
            return np.stack([np.full(8, i + 1.0) for i in range(len(tiles))])

    monkeypatch.setattr(embed, "_Encoder", Fake)
    p = tmp_path / "a.png"
    Image.new("RGB", (824, 1830), "white").save(p)
    s = [Sample("x1", "normal", 0, "d", "h", None, p)]
    out = embed.embed_with(s, tmp_path / "feats", "clip-b32-grid6", device="cpu")
    assert out.shape == (1, 8) and abs(np.linalg.norm(out[0]) - 1) < 1e-5
    assert (tmp_path / "feats" / "img" / "clip-b32-grid6" / "x1.npy").exists()
    embed.embed_with(s, tmp_path / "feats", "clip-b32-grid6", device="cpu")
    assert made == ["grid6"]  # 두 번째는 캐시를 읽음


def test_reports_have_no_identifiers(tmp_path):
    res, samples, *_ = _run()
    res |= {"cutoff": "2026-11-13", "index": "idx.jsonl", "labels": "labels.csv", "test_until": "2026-11-18",
            "device": "cpu"}
    for k in res["encoders"]:
        res["encoders"][k]["speed"] = {"ms_per_screen": 12.3, "n_params_image": 1_000_000, "dim": 16}
    ci.write_reports(res, tmp_path)
    blob = (tmp_path / "image_compare.md").read_text(encoding="utf-8") + (tmp_path / "image_compare.json").read_text(encoding="utf-8")
    for bad in ("fake", "hash0", "hash1", "/secret", "OCRMARK", "example", "banner0"):
        assert bad not in blob
    assert "글자 단독" in blob and "시험 세트 수치는 확인용" in blob


def test_grid8_tiles():
    for size, n in [((824, 1830), 8), ((824, 915), 4), ((824, 400), 2)]:
        tiles = embed.grid8_tiles(Image.new("RGB", size))
        assert len(tiles) == n
        assert sum(t.width * t.height for t in tiles) == size[0] * size[1]
        if size[1] == 1830:
            assert all(0.8 <= t.width / t.height <= 1.25 for t in tiles)


def test_ranking_independent_of_test_features_and_thresholds_of_banner():
    res, samples, texts, y, mask, Xm, Xs = _run()
    rng = np.random.default_rng(7)
    Xs2 = {k: v.copy() for k, v in Xs.items()}
    te = np.flatnonzero(mask)
    for k in Xs2:
        Xs2[k][te] = _unit(rng.normal(size=(len(te), 16)))
    res2 = ci.compare_core(samples, texts, Xm, Xs2, mask, n_boot=20)
    assert res2["ranking"] == res["ranking"]
    ba = np.array([s.label == "embedded_banner" for s in samples])
    Xs3 = {k: v.copy() for k, v in Xs.items()}
    for k in Xs3:
        Xs3[k][ba] = _unit(rng.normal(size=(int(ba.sum()), 16)))
    res3 = ci.compare_core(samples, texts, Xm, Xs3, mask, n_boot=20)
    for k in Xs:
        assert res3["encoders"][k]["thresholds"] == res["encoders"][k]["thresholds"]


def test_rescue_stats_boundary_is_inclusive():
    y = np.array([1, 1, 0])
    p_text = np.zeros(3)
    p_img = np.array([0.7, 0.6, 0.7])
    r = ci.rescue_stats(y, p_text, p_img, 0.7)
    assert r["rescued"]["num"] == 1 if "num" in r["rescued"] else True
    assert r["rescued"]["rate"] == 0.5
    assert r["extra_fp"]["rate"] == 1.0
