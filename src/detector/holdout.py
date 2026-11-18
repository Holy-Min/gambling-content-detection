"""사전 등록 홀드아웃 점검: 오탐 줄이기 규칙(mean/text/and)을 새로 모인 화면에서 확인."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .metrics import bootstrap_ci

RULES = ("mean", "text", "and")
LABELS = ("gambling", "hard_negative", "normal")
THR = 0.5  # 사전 등록: 임계값 고정
NEAR_DUP_COS = 0.98
CUTOFF = "2026-11-09T14:00"
RULE_DESC = {
    "mean": "두 확률의 평균 >= 0.5 (현재)",
    "text": "텍스트 확률 >= 0.5",
    "and": "텍스트 >= 0.5 그리고 이미지 >= 0.5",
}


def apply_rule(p_text: np.ndarray, p_image: np.ndarray, rule: str) -> np.ndarray:
    pt, pi = np.asarray(p_text, dtype=float), np.asarray(p_image, dtype=float)
    if rule == "mean":
        return (pt + pi) / 2 >= THR
    if rule == "text":
        return pt >= THR
    if rule == "and":
        return (pt >= THR) & (pi >= THR)
    raise ValueError(f"unknown rule: {rule}")


def select_holdout(rows: list[dict], snapshot_ids: set[str], cutoff: str = CUTOFF) -> list[dict]:
    """status ok·화면 파일 있음·라벨 3종·captured_at >= cutoff, 스냅숏 id 는 제외."""
    return [
        r for r in rows
        if r.get("status") == "ok" and r.get("full_path")
        and r.get("label") in LABELS
        and str(r.get("captured_at", "")) >= cutoff
        and r["id"] not in snapshot_ids
    ]


def near_dup_mask(X_hold: np.ndarray, X_train: np.ndarray, cos: float = NEAR_DUP_COS) -> np.ndarray:
    """학습 화면 중 코사인 > cos 인 것이 하나라도 있으면 True. (벡터는 정규화되어 있다고 가정)"""
    if len(X_train) == 0:
        return np.zeros(len(X_hold), dtype=bool)
    return (np.asarray(X_hold) @ np.asarray(X_train).T).max(axis=1) > cos


def _div(a: float, b: float) -> float:
    return float("nan") if b == 0 else a / b


def rule_metrics(label: np.ndarray, kind: np.ndarray, domain: np.ndarray, pred: np.ndarray) -> dict:
    label, kind, domain, pred = map(np.asarray, (label, kind, domain, pred))
    pred = pred.astype(bool)
    g, hn, nm = (label == k for k in LABELS)
    dep = g & (kind == "deposit")
    tp, fp = int((g & pred).sum()), int((~g & pred).sum())
    fn = int((g & ~pred).sum())
    return {
        "n": {k: int((label == k).sum()) for k in LABELS},
        "domains": {k: int(len(set(domain[label == k]))) for k in LABELS},
        "n_deposit": int(dep.sum()),
        "recall": _div(tp, tp + fn),
        "deposit_recall": _div(int((dep & pred).sum()), int(dep.sum())),
        "hn_fpr": _div(int((hn & pred).sum()), int(hn.sum())),
        "normal_fpr": _div(int((nm & pred).sum()), int(nm.sum())),
        "precision": _div(tp, tp + fp),
        "f1": _div(2 * tp, 2 * tp + fp + fn),
    }


def _ci(label, domain, pred, which: str) -> list:
    g, hn = label == "gambling", label == "hard_negative"

    def stat(idx):
        base = g[idx] if which == "recall" else hn[idx]
        return _div(int((base & pred[idx]).sum()), int(base.sum()))

    lo, hi, valid = bootstrap_ci(stat, domain, n=1000, seed=42)
    return [lo, hi, valid]


def _oof_context(pred_csv: Path) -> dict:
    with Path(pred_csv).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    label = np.array([r["label"] for r in rows])
    kind = np.array([r["page_kind"] for r in rows], dtype=object)
    domain = np.array([r["domain"] for r in rows])
    out = {}
    for scen, suf in (("A", ""), ("B", "_mirror")):
        pt = np.array([float(r[f"p_text{suf}"]) for r in rows])
        pi = np.array([float(r[f"p_image{suf}"]) for r in rows])
        out[scen] = {r: rule_metrics(label, kind, domain, apply_rule(pt, pi, r)) for r in RULES}
    return out


def run_holdout(live_index: Path, snapshot: Path, root: Path, pred_csv: Path, cutoff: str = CUTOFF) -> dict:
    from .data import load_samples
    from .embed import embed_images
    from .models import fit_full
    from .ocr import run_ocr

    feats = Path(root) / "_features"
    train = [s for s in load_samples(snapshot, root) if s.y is not None]
    snap_ids = {s.id for s in train}
    live_rows = [json.loads(l) for l in Path(live_index).open(encoding="utf-8") if l.strip()]
    assert not [r for r in live_rows if r["id"] in snap_ids and str(r.get("captured_at", "")) >= cutoff], \
        "snapshot id found after cutoff"
    keep = {r["id"] for r in select_holdout(live_rows, snap_ids, cutoff)}
    hold = [s for s in load_samples(live_index, root) if s.id in keep]

    ocr = run_ocr(train + hold, feats / "ocr")
    X_tr = embed_images(train, feats / "clip")
    X_ho = embed_images(hold, feats / "clip")
    ttr = [ocr[s.id]["text"] for s in train]
    tho = [ocr[s.id]["text"] for s in hold]
    tm, im = fit_full(ttr, X_tr, np.array([s.y for s in train]))
    pt, pi = tm.predict_proba(tho)[:, 1], im.predict_proba(X_ho)[:, 1]

    label = np.array([s.label for s in hold])
    kind = np.array([s.page_kind or "" for s in hold], dtype=object)
    domain = np.array([s.domain for s in hold])
    new_dom = ~np.isin(domain, [s.domain for s in train])
    no_dup = ~near_dup_mask(X_ho, X_tr)
    subsets = {"all": np.ones(len(hold), bool), "new_domain": new_dom, "no_near_dup": no_dup}

    res = {"cutoff": cutoff, "train_screens": len(train), "holdout_screens": len(hold),
           "rules": RULE_DESC, "subsets": {}}
    for name, m in subsets.items():
        res["subsets"][name] = {}
        for r in RULES:
            pred = apply_rule(pt, pi, r)
            d = rule_metrics(label[m], kind[m], domain[m], pred[m])
            if name == "all":
                d["recall_ci"] = _ci(label, domain, pred, "recall")
                d["hn_fpr_ci"] = _ci(label, domain, pred, "hn_fpr")
            res["subsets"][name][r] = d
    res["oof_context"] = _oof_context(pred_csv)
    return res


def _pct(v: float) -> str:
    return "-" if v != v else f"{v * 100:.1f}%"


def _cell(d: dict, key: str) -> str:
    s = _pct(d[key])
    ci = d.get(key + "_ci")
    return f"{s} [{ci[0] * 100:.1f}~{ci[1] * 100:.1f}]" if ci else s


def _table(sub: dict, ci: bool) -> list[str]:
    head = ["| 규칙 | 도박 재현율 | 충전 재현율 | 하드 네거티브 오탐률 | 일반(normal) 오탐률 | 정밀도 | F1 |",
            "|---|---|---|---|---|---|---|"]
    for r in RULES:
        d = sub[r]
        f1 = "-" if d["f1"] != d["f1"] else f"{d['f1']:.3f}"
        head.append(f"| {r} | {_cell(d, 'recall')} | {_pct(d['deposit_recall'])} | {_cell(d, 'hn_fpr')} "
                    f"| {_pct(d['normal_fpr'])} | {_pct(d['precision'])} | {f1} |")
    return head


def _count_line(d: dict) -> str:
    n, dm = d["n"], d["domains"]
    return (f"도박 {n['gambling']}쪽/{dm['gambling']}개(충전 {d['n_deposit']}쪽), 하드 네거티브 "
            f"{n['hard_negative']}쪽/{dm['hard_negative']}개, normal {n['normal']}쪽/{dm['normal']}개")


def write_reports(res: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "holdout.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    S = res["subsets"]
    L = ["# 오탐 줄이기 규칙 홀드아웃 점검", "",
         f"학습: 스냅숏 {res['train_screens']}쪽 전체로 텍스트·이미지 모델을 한 번 학습했어요. "
         f"홀드아웃: 스냅숏 이후({res['cutoff']} 이후)에 새로 모은 {res['holdout_screens']}쪽이에요. "
         "수치는 모두 화면(쪽) 단위, 임계값 0.5예요.", "",
         "## 사전 등록", "",
         "규칙과 임계값은 홀드아웃 결과를 보기 전에 고정했어요. 규칙 `and` 는 out-of-fold 오류를 본 뒤 정한 것이라 "
         "그 데이터로는 확인할 수 없어서 새 데이터로 점검해요.", ""]
    L += [f"- `{r}`: {d}" for r, d in res["rules"].items()]
    L += ["", "지표 뜻: 도박 재현율은 도박 화면 중 잡은 비율, 충전 재현율은 그중 충전 화면, 오탐률은 해당 정상 화면을 "
          "도박으로 잘못 잡은 비율, 정밀도는 도박이라 한 것 중 실제 도박 비율, F1은 재현율과 정밀도를 합친 점수예요. "
          "대괄호는 도메인 단위 부트스트랩(1,000회, seed 42) 95% 구간이에요.", ""]
    titles = {"all": "전체 홀드아웃", "new_domain": "학습에 없던 도메인만 (참고용, 표본 매우 적음)",
              "no_near_dup": "학습 화면과 거의 같은 것 제외 (CLIP 코사인 0.98 이하)"}
    for k, t in titles.items():
        L += [f"## {t}", "", _count_line(S[k]["mean"]), ""] + _table(S[k], k == "all") + [""]
    L += ["## 참고: 평가 데이터(사후 선택) out-of-fold", "",
          "스냅숏 475쪽의 out-of-fold 예측에 같은 규칙을 적용한 값이에요. 규칙을 이 오류를 보고 골랐기 때문에 "
          "낙관적이고, 홀드아웃과 비교용으로만 봐 주세요.", ""]
    for scen, t in (("A", "A. 새 주소(도메인 단위)"), ("B", "B. 처음 보는 사이트(미러 묶음 단위)")):
        L += [f"**{t}** — " + _count_line(res["oof_context"][scen]["mean"]), ""]
        L += _table(res["oof_context"][scen], False) + [""]
    L += ["## 한계", "",
          "- 홀드아웃은 대부분 학습에 있던 사이트를 다시 찍은 화면이라 새 사이트에 대한 성능이 아니에요.",
          "- 학습에 없던 도메인 부분집합은 매우 작아 구간이 넓고 참고용이에요.",
          "- 라벨은 수집 때 정한 검색어·도메인 단위 라벨이에요(화면 단위로 다시 검토하지 않았어요).",
          "- 규칙을 하나 골라 확인하는 점검이라, 결과가 좋아도 제품 목표(하드 네거티브 오탐률 2% 이하) 달성을 뜻하지 않아요.", ""]
    (out_dir / "holdout.md").write_text("\n".join(L), encoding="utf-8")
