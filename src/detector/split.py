"""도메인 단위 층화 분할."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from detector.data import Sample


def make_folds(
    samples: list[Sample], k: int = 5, seed: int = 42, groups: np.ndarray | None = None
) -> np.ndarray:
    """groups 를 주지 않으면 도메인 단위, 주면 그 그룹 단위로 같은 fold 에 묶는다."""
    if any(s.y is None for s in samples):
        raise ValueError("make_folds needs labeled samples: found y is None (embedded_banner?)")
    y = np.array([s.y for s in samples])
    groups = np.array([s.domain for s in samples]) if groups is None else np.asarray(groups)
    folds = np.full(len(samples), -1, dtype=int)
    cv = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=seed)
    for f, (_, test_idx) in enumerate(cv.split(np.zeros(len(y)), y, groups)):
        folds[test_idx] = f
    return folds


def _norm_text(t: str) -> str:
    return " ".join(t.lower().split())


def mirror_groups(
    domains: np.ndarray, X_img: np.ndarray, texts: list[str], cos: float = 0.98, min_chars: int = 20
) -> np.ndarray:
    """미러 묶음 그룹 id. 라벨은 보지 않고, 서로 다른 두 도메인의 화면이 이미지 코사인 > cos 이거나
    정규화한 OCR 텍스트(공백 제외 글자 min_chars 이상)가 같으면 두 도메인을 연결한 연결요소."""
    domains = np.asarray(domains)
    uniq = {d: i for i, d in enumerate(dict.fromkeys(domains.tolist()))}
    parent = list(range(len(uniq)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    di = np.array([uniq[d] for d in domains])
    sim = X_img @ X_img.T
    for i, j in zip(*np.nonzero(np.triu(sim > cos, k=1))):
        if di[i] != di[j]:
            union(di[i], di[j])
    seen: dict[str, int] = {}
    for t, d in zip(texts, di):
        n = _norm_text(t)
        if len("".join(n.split())) < min_chars:
            continue
        if n in seen:
            union(seen[n], d)
        else:
            seen[n] = d
    roots = np.array([find(d) for d in di])
    _, gid = np.unique(roots, return_inverse=True)
    return gid


def first_seen(samples: list[Sample]) -> dict[str, str]:
    """domain_hash 별 가장 이른 captured_at 날짜(YYYY-MM-DD). captured_at 이 빈 화면은 무시."""
    out: dict[str, str] = {}
    for s in samples:
        d = s.captured_at[:10]
        if d and (s.domain_hash not in out or d < out[s.domain_hash]):
            out[s.domain_hash] = d
    return out


def first_seen_from_index(index_path: Path) -> dict[str, str]:
    """색인의 ok 행 전체(라벨·덮어쓰기와 무관)에서 사이트별 첫 수집일. exclude 때문에 사이트가 옮겨 가지 않게 한다."""
    out: dict[str, str] = {}
    with Path(index_path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            d = (row.get("captured_at") or "")[:10]
            if row.get("status") != "ok" or not row.get("full_path") or not d:
                continue
            h = row["domain_hash"]
            if h not in out or d < out[h]:
                out[h] = d
    return out


def time_split(
    samples: list[Sample], cutoff: str, first_seen_map: dict[str, str] | None = None,
    until: str | None = None,
) -> np.ndarray:
    """cutoff <= 사이트 첫 수집일 (<= until) 이면 True(시험). until 보다 늦게 처음 수집한 사이트는 학습.
    맵에 없는 사이트는 samples 에서 계산하고, 날짜를 알 수 없으면 학습(False)."""
    fs = dict(first_seen(samples))
    if first_seen_map:
        fs.update(first_seen_map)
    return np.array(
        [s.domain_hash in fs and fs[s.domain_hash] >= cutoff and (until is None or fs[s.domain_hash] <= until)
         for s in samples], dtype=bool)
