import numpy as np

from detector.metrics import bootstrap_ci, confusion, f1, rate, threshold_for_fpr


def test_f1_and_confusion():
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.4, 0.6, 0.1])
    assert confusion(y, p) == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert f1(y, p) == 0.5
    assert rate(np.array([True, False, False, False])) == 0.25


def _synthetic(n_dom=20, per=5, seed=0):
    rng = np.random.default_rng(seed)
    groups = np.repeat(np.arange(n_dom), per)
    y = (groups % 2).astype(int)
    p = np.clip(y * 0.6 + rng.normal(0.2, 0.25, len(y)), 0, 1)
    return groups, y, p


def test_bootstrap_ci_contains_point():
    groups, y, p = _synthetic()
    stat = lambda idx: f1(y[idx], p[idx])
    lo, hi, valid = bootstrap_ci(stat, groups, n=1000, seed=42)
    point = f1(y, p)
    assert lo <= point <= hi
    assert valid == 1000


def test_bootstrap_skips_degenerate():
    groups = np.repeat(np.arange(10), 4)
    y = (groups == 0).astype(int)  # 양성 도메인 1개뿐
    p = np.where(y == 1, 0.9, 0.1)

    def stat(idx):
        if y[idx].sum() == 0:
            raise ValueError("no positives")
        return f1(y[idx], p[idx])

    lo, hi, valid = bootstrap_ci(stat, groups, n=1000, seed=42)
    assert 0 < valid < 1000
    assert not (np.isnan(lo) or np.isnan(hi))


def test_threshold_for_fpr():
    neg = np.arange(100) / 100.0
    thr = threshold_for_fpr(neg, 0.02)
    assert (neg >= thr).mean() <= 0.02
