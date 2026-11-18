import numpy as np

from detector.models import fit_full, oof_predict, text_model, top_ngrams


def _data(n_dom=10, per=6, seed=0):
    rng = np.random.default_rng(seed)
    words = ["apple", "river", "stone", "cloud", "green", "table", "music", "paper"]
    texts, y, folds = [], [], []
    for d in range(n_dom):
        for _ in range(per):
            noise = " ".join(rng.choice(words, 4))
            texts.append(f"dom{d}tok dom{d}uniq dom{d}zzz {noise}")
            y.append(d % 2)
            folds.append(d % 5)
    n = len(texts)
    return texts, rng.normal(size=(n, 8)), np.array(y), np.array(folds)


def test_oof_never_sees_test_domain():
    texts, X, y, folds = _data()
    oof = oof_predict(texts, X, y, folds)["text"]
    tm, _ = fit_full(texts, X, y)
    insample = tm.predict_proba(texts)[:, 1]
    pos = y == 1
    assert insample[pos].mean() > 0.7
    assert oof[pos].mean() < insample[pos].mean() - 0.15
    assert abs(oof.mean() - 0.5) < 0.15  # 도메인 토큰만으로는 기회 수준


def test_fusion_is_mean():
    texts, X, y, folds = _data()
    r = oof_predict(texts, X, y, folds)
    assert np.allclose(r["fusion"], (r["text"] + r["image"]) / 2)


def test_empty_text_gets_probability():
    texts, X, y, folds = _data()
    texts[0] = ""
    texts[5] = ""
    r = oof_predict(texts, X, y, folds)
    for k in ("text", "image", "fusion"):
        assert np.all((r[k] >= 0) & (r[k] <= 1))
    tm, _ = fit_full(texts, X, y)
    assert 0 <= tm.predict_proba([""])[0, 1] <= 1


def test_top_ngrams_positive_only():
    texts = ["bet bonus win", "bet bonus now", "hello world", "hello there world"] * 2
    y = np.array([1, 1, 0, 0] * 2)
    pipe = text_model().fit(texts, y)
    got = top_ngrams(pipe, "bet bonus", k=3)
    assert 0 < len(got) <= 3
