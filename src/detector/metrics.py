"""지표·도메인 단위 부트스트랩·임계값."""
from __future__ import annotations

from typing import Callable

import numpy as np


def confusion(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> dict[str, int]:
    y = np.asarray(y).astype(int)
    pred = np.asarray(p) >= thr
    return {
        "tp": int(((y == 1) & pred).sum()),
        "fp": int(((y == 0) & pred).sum()),
        "tn": int(((y == 0) & ~pred).sum()),
        "fn": int(((y == 1) & ~pred).sum()),
    }


def f1(y: np.ndarray, p: np.ndarray, thr: float = 0.5) -> float:
    c = confusion(y, p, thr)
    denom = 2 * c["tp"] + c["fp"] + c["fn"]
    return float("nan") if denom == 0 else 2 * c["tp"] / denom


def rate(y_pred_positive_mask: np.ndarray) -> float:
    m = np.asarray(y_pred_positive_mask, dtype=bool)
    return float("nan") if m.size == 0 else float(m.mean())


def bootstrap_ci(
    stat_fn: Callable[[np.ndarray], float],
    groups: np.ndarray,
    n: int = 1000,
    seed: int = 42,
) -> tuple[float, float, int]:
    """도메인을 복원추출해 stat_fn(행 인덱스)을 n회 계산. 예외·NaN 회차는 제외."""
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    members = {g: np.flatnonzero(groups == g) for g in uniq}
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(n):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([members[g] for g in pick])
        try:
            v = float(stat_fn(idx))
        except Exception:
            continue
        if np.isnan(v):
            continue
        vals.append(v)
    if not vals:
        return float("nan"), float("nan"), 0
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi), len(vals)


def threshold_for_fpr(y_neg_scores: np.ndarray, target: float = 0.02) -> float:
    """음성 중 (score >= thr) 비율이 target 이하가 되는 가장 낮은 임계값."""
    s = np.sort(np.asarray(y_neg_scores, dtype=float))[::-1]
    k = int(np.floor(target * len(s)))  # 허용 오탐 수
    if k >= len(s):
        return float(s.min())
    return float(np.nextafter(s[k], np.inf))
