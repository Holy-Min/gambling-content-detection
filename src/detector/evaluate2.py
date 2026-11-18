"""2차 기준선: 새 데이터·새 라벨로 같은 모델을 다시 학습하고, 첫 수집일 기준 시험 세트로 평가한다.

평가 핵심(`run_core`)은 순수 함수(OCR·CLIP 호출 없음)이고, `evaluate2` 가 파일 입출력을 맡는다.
공개 산출물에는 domain_hash·개수·비율만 쓴다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .data import Sample, load_samples
from .metrics import bootstrap_ci, confusion, f1, threshold_for_fpr
from .models import fit_full, oof_predict
from .rules import LEGAL_BRAND_TERMS, legal_brand_hits, legal_rule
from .split import first_seen_from_index, make_folds, mirror_groups, time_split

HOME = Path.home() / "datasets" / "gambling"
DEFAULT_INDEX = HOME / "_features" / "index_snapshot_20261118T1911.jsonl"
DEFAULT_LABELS = Path(__file__).resolve().parents[2] / "docs" / "labeling" / "labels_v1.csv"
DEFAULT_CUTOFF = "2026-11-13"
DEFAULT_TEST_UNTIL = "2026-11-18"
MODELS = ("text", "image", "fusion")
MODEL_KO = {"text": "텍스트", "image": "이미지", "fusion": "융합"}
THR_KEYS = ("0.5", "fpr2")
STATS = ("f1", "precision", "recall", "fpr_hard_negative", "fpr_normal", "recall_deposit")
RULE_STATS = ("f1", "precision", "recall", "fpr_hard_negative")


def _clean(v: float) -> float | None:
    return None if v is None or np.isnan(v) else float(v)


def _triple(stat, groups: np.ndarray, n_boot: int) -> list:
    """[점추정, 하한, 상한]. 계산 불가(NaN)는 None."""
    if len(groups) == 0:
        return [None, None, None]
    pt = _clean(stat(np.arange(len(groups))))
    lo, hi, _ = bootstrap_ci(stat, groups, n=n_boot)
    return [pt, _clean(lo), _clean(hi)]


def _mean_or_nan(mask: np.ndarray) -> float:
    return float("nan") if mask.size == 0 else float(mask.mean())


def _stat_fn(name: str, y, label, kind, p, thr):
    def fn(idx: np.ndarray) -> float:
        yy, pp = y[idx], p[idx]
        c = confusion(yy, pp, thr)
        if name == "f1":
            return f1(yy, pp, thr)
        if name == "precision":
            return float("nan") if c["tp"] + c["fp"] == 0 else c["tp"] / (c["tp"] + c["fp"])
        if name == "recall":
            return float("nan") if c["tp"] + c["fn"] == 0 else c["tp"] / (c["tp"] + c["fn"])
        if name == "recall_deposit":
            m = (yy == 1) & (kind[idx] == "deposit")
            return _mean_or_nan(pp[m] >= thr)
        lab = "hard_negative" if name == "fpr_hard_negative" else "normal"
        return _mean_or_nan(pp[label[idx] == lab] >= thr)
    return fn


def _counts(label, hashes, kind) -> dict:
    out = {"sites": int(len(set(hashes.tolist()))), "screens": int(len(label)), "by_label": {}}
    for lab in sorted(set(label.tolist())):
        m = label == lab
        out["by_label"][lab] = {"sites": int(len(set(hashes[m].tolist()))), "screens": int(m.sum())}
    dep = (label == "gambling") & (kind == "deposit")
    out["by_label"]["gambling_deposit"] = {"sites": int(len(set(hashes[dep].tolist()))), "screens": int(dep.sum())}
    return out


def subset_report(y, label, kind, hashes, P: dict, thr: dict, n_boot: int) -> dict:
    """한 부분집합의 모델×임계값별 지표(사이트 단위 부트스트랩 신뢰구간)."""
    res = {"n": _counts(label, hashes, kind), "models": {}, "fusion_gain_f1": {}}
    for m in MODELS:
        res["models"][m] = {}
        for tk in THR_KEYS:
            t = 0.5 if tk == "0.5" else thr[m]
            res["models"][m][tk] = {
                s: _triple(_stat_fn(s, y, label, kind, P[m], t), hashes, n_boot) for s in STATS
            }
    for tk in THR_KEYS:
        t = {m: (0.5 if tk == "0.5" else thr[m]) for m in MODELS}

        def gain(idx, t=t):
            fu = f1(y[idx], P["fusion"][idx], t["fusion"])
            ft, fi = (f1(y[idx], P[m][idx], t[m]) for m in ("text", "image"))
            if np.isnan(ft) or np.isnan(fi):  # max 가 순서에 좌우되지 않게, 둘 다 유효할 때만
                return float("nan")
            return fu - max(ft, fi)
        res["fusion_gain_f1"][tk] = _triple(gain, hashes, n_boot)
    return res


def _rate_pair(flag: np.ndarray, hashes: np.ndarray, n_boot: int) -> dict:
    """화면 단위 비율과 '한 화면이라도 켜진 사이트' 비율(사이트 단위 부트스트랩)."""
    sites = np.array(sorted(set(hashes.tolist())), dtype=object)
    site_flag = np.array([flag[hashes == h].any() for h in sites]) if len(sites) else np.zeros(0)
    return {
        "screen_rate": _triple(lambda idx, f=flag: float(f[idx].mean()), hashes, n_boot),
        "site_rate": _triple(lambda idx, f=site_flag: float(f[idx].mean()), np.arange(len(sites)), n_boot),
    }


def banner_report(P: dict, hashes: np.ndarray, thr: dict, n_boot: int) -> dict:
    out = {"n": {"sites": int(len(set(hashes.tolist()))), "screens": int(len(hashes))}, "models": {}}
    for m in MODELS:
        out["models"][m] = {}
        for tk in THR_KEYS:
            t = 0.5 if tk == "0.5" else thr[m]
            out["models"][m][tk] = _rate_pair(P[m] >= t, hashes, n_boot)
    return out


def text_plus_rule_report(y, label, kind, hashes, p_text, rule, thr: dict, n_boot: int) -> dict:
    """글자 단독 vs (글자 p>=임계값 OR 규칙). thr 는 {"text": fpr2 임계값}."""
    p_or = np.where(rule, np.inf, p_text)
    out: dict = {}
    for tk in THR_KEYS:
        t = 0.5 if tk == "0.5" else thr["text"]
        out[tk] = {
            name: {s: _triple(_stat_fn(s, y, label, kind, p, t), hashes, n_boot) for s in RULE_STATS}
            for name, p in (("text_only", p_text), ("text_or_rule", p_or))
        }
    return out


def rule_false_hits_report(groups: dict[str, np.ndarray], rule: np.ndarray, texts: np.ndarray,
                           neg_idx: np.ndarray) -> dict:
    """합법 사행이 아닌 화면에서 규칙이 켜진 비율(묶음별)과, 음성 화면에서 낱말별 켜진 화면 수."""
    out: dict = {}
    for name, ix in groups.items():
        hits = int(rule[ix].sum())
        out[name] = {"screens": int(len(ix)), "hits": hits, "rate": hits / len(ix) if len(ix) else None}
    counts = {t: 0 for t in LEGAL_BRAND_TERMS}
    for i in neg_idx:
        for t in legal_brand_hits(texts[i]):
            counts[t] += 1
    ranked = sorted(((t, c) for t, c in counts.items() if c), key=lambda tc: -tc[1])  # 동률은 목록 순서
    out["by_term_negative"] = [{"term": t, "screens": c} for t, c in ranked]
    return out


def run_core(
    samples: list[Sample], texts: list[str], X: np.ndarray, test_mask: np.ndarray,
    n_boot: int = 1000, k: int = 5, seed: int = 42, test_until: str | None = None,
) -> dict:
    """samples(이진+배너+합법 사행 전체)·texts·X 는 같은 순서. test_mask: time_split 결과(y 없는 행은 무시).
    test_until 은 기록용(마스크는 호출자가 time_split 으로 만든다)."""
    y_all = np.array([-1 if s.y is None else s.y for s in samples])
    texts_a = np.array(texts, dtype=object)
    hashes_all = np.array([s.domain_hash for s in samples], dtype=object)
    label_all = np.array([s.label for s in samples], dtype=object)
    kind_all = np.array([s.page_kind or "" for s in samples], dtype=object)
    is_bin = y_all >= 0
    tr_i = np.flatnonzero(is_bin & ~test_mask)
    te_i = np.flatnonzero(is_bin & test_mask)
    ba_i = np.flatnonzero(label_all == "embedded_banner")
    lg_i = np.flatnonzero(label_all == "legal_gambling")
    rule_all = np.array([legal_rule(t) for t in texts_a], dtype=bool)

    # 학습 세트 OOF (미러 묶음 단위 fold) → 지표 + 임계값 사전 고정
    tr_samples = [samples[i] for i in tr_i]
    tr_gid = mirror_groups(hashes_all[tr_i], X[tr_i], list(texts_a[tr_i]))
    folds = make_folds(tr_samples, k=k, seed=seed, groups=tr_gid)
    oof = oof_predict(list(texts_a[tr_i]), X[tr_i], y_all[tr_i], folds)
    neg = y_all[tr_i] == 0
    thr = {m: float(threshold_for_fpr(oof[m][neg], 0.02)) for m in MODELS}

    # 전체 학습 세트로 재학습 → 시험·배너 예측
    tm, im = fit_full(list(texts_a[tr_i]), X[tr_i], y_all[tr_i])

    def predict(ix: np.ndarray) -> dict:
        if len(ix) == 0:
            return {m: np.zeros(0) for m in MODELS}
        pt = tm.predict_proba(list(texts_a[ix]))[:, 1]
        pi = im.predict_proba(X[ix])[:, 1]
        return {"text": pt, "image": pi, "fusion": (pt + pi) / 2}

    P_te, P_ba, P_lg = predict(te_i), predict(ba_i), predict(lg_i)

    # 미러 여부: 학습+시험 이진 표본 전체의 묶음에서, 학습 사이트와 같은 묶음인 시험 사이트
    bin_i = np.concatenate([tr_i, te_i])
    gid_all = mirror_groups(hashes_all[bin_i], X[bin_i], list(texts_a[bin_i]))
    train_groups = set(gid_all[: len(tr_i)].tolist())
    mirror_te = np.array([g in train_groups for g in gid_all[len(tr_i):]], dtype=bool)

    metrics: dict = {
        "thr_fpr2": thr,
        "n": {
            "train": _counts(label_all[tr_i], hashes_all[tr_i], kind_all[tr_i]),
            "test": _counts(label_all[te_i], hashes_all[te_i], kind_all[te_i]),
            "banner": {"sites": int(len(set(hashes_all[ba_i].tolist()))), "screens": int(len(ba_i))},
            "legal": {"sites": int(len(set(hashes_all[lg_i].tolist()))), "screens": int(len(lg_i))},
        },
        "test_until": test_until,
        "train_oof": subset_report(y_all[tr_i], label_all[tr_i], kind_all[tr_i], hashes_all[tr_i], oof, thr, n_boot),
    }
    for key, mask in (("test", np.ones(len(te_i), bool)), ("test_mirror", mirror_te), ("test_unseen", ~mirror_te)):
        sel = te_i[mask]
        metrics[key] = subset_report(
            y_all[sel], label_all[sel], kind_all[sel], hashes_all[sel],
            {m: P_te[m][mask] for m in MODELS}, thr, n_boot)
        if key in ("test", "test_unseen"):
            metrics.setdefault("text_plus_rule", {})[key] = text_plus_rule_report(
                y_all[sel], label_all[sel], kind_all[sel], hashes_all[sel], P_te["text"][mask],
                rule_all[sel], thr, n_boot)
    metrics["banner"] = banner_report(P_ba, hashes_all[ba_i], thr, n_boot)
    metrics["legal"] = banner_report(P_lg, hashes_all[lg_i], thr, n_boot)
    metrics["legal"]["rule"] = _rate_pair(rule_all[lg_i], hashes_all[lg_i], n_boot)

    def pick(ix: np.ndarray, lab: str) -> np.ndarray:
        return ix[label_all[ix] == lab]
    metrics["rule_false_hits"] = rule_false_hits_report(
        {"test_hard_negative": pick(te_i, "hard_negative"), "train_hard_negative": pick(tr_i, "hard_negative"),
         "train_normal": pick(tr_i, "normal"), "banner": ba_i,
         "test_gambling": pick(te_i, "gambling"), "train_gambling": pick(tr_i, "gambling")},
        rule_all, texts_a,
        np.concatenate([pick(tr_i, "hard_negative"), pick(tr_i, "normal"),
                        pick(te_i, "hard_negative"), pick(te_i, "normal")]))

    # 행 단위 결과(비공개 CSV 용). 원래 샘플 순서 유지.
    n = len(samples)
    rows = {"p_text": [None] * n, "p_image": [None] * n, "p_fusion": [None] * n,
            "split": [None] * n, "mirror_of_train": [""] * n, "rule_hit": rule_all.astype(int).tolist()}
    for ix, P, name in ((tr_i, oof, "train"), (te_i, P_te, "test"), (ba_i, P_ba, "banner"), (lg_i, P_lg, "legal")):
        for j, i in enumerate(ix):
            rows["split"][i] = name
            rows["p_text"][i], rows["p_image"][i], rows["p_fusion"][i] = (float(P[m][j]) for m in MODELS)
    for j, i in enumerate(te_i):
        rows["mirror_of_train"][i] = int(mirror_te[j])
    rows["id"] = [s.id for s in samples]
    rows["domain_hash"] = hashes_all.tolist()
    rows["label"] = label_all.tolist()
    rows["page_kind"] = kind_all.tolist()
    rows["full_path"] = [str(s.image_path) for s in samples]

    disagree = [
        int(i) for j, i in enumerate(tr_i)
        if (y_all[i] == 1 and oof["fusion"][j] < 0.2) or (y_all[i] == 0 and oof["fusion"][j] > 0.8)
    ]
    return {"metrics": metrics, "rows": rows, "disagree_idx": disagree}


def _pct(v) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def _cell(t: list) -> str:
    return "-" if t[0] is None else (f"{_pct(t[0])} [{_pct(t[1])}, {_pct(t[2])}]" if t[1] is not None else _pct(t[0]))


def _prev_table(repo: Path, m: dict) -> list[str]:
    p = repo / "docs" / "week11" / "metrics.json"
    if not p.exists():
        return []
    old = json.loads(p.read_text(encoding="utf-8"))["scenarios"]
    sc = {"domain": "A(처음 보는 사이트 아님, 도메인 단위 OOF)", "mirror_cluster": "B(미러 묶음 단위 OOF)"}
    lines = ["## 1차 → 이번 비교 (융합, 임계값 0.5)", "",
             "| 구분 | F1 | 하드 네거티브 오탐률 |", "|---|---|---|"]
    for k, name in sc.items():
        f = old[k]["models"]["fusion"]
        lines.append(f"| 1차 시나리오 {name} | {_pct(f['f1'][0])} | {_pct(f['fpr_hard_negative'][0])} |")
    for key, name in (("train_oof", "이번 학습 세트 OOF"), ("test", "이번 시험 세트(전체)"),
                      ("test_mirror", "이번 시험 세트(주소만 바꾼 사이트)"), ("test_unseen", "이번 시험 세트(처음 보는 사이트)")):
        f = m[key]["models"]["fusion"]["0.5"]
        lines.append(f"| {name} | {_cell(f['f1'])} | {_cell(f['fpr_hard_negative'])} |")
    return lines + [""]


def _subset_md(title: str, r: dict) -> list[str]:
    n = r["n"]
    bl = ", ".join(f"{k} {v['sites']}사이트/{v['screens']}화면" for k, v in n["by_label"].items())
    lines = [f"## {title}", "", f"사이트 {n['sites']}, 화면 {n['screens']} ({bl})", ""]
    for tk, tname in (("0.5", "임계값 0.5"), ("fpr2", "임계값 = 학습 OOF 오탐 2%")):
        lines += [f"### {tname}", "", "| 지표 | 텍스트 | 이미지 | 융합 |", "|---|---|---|---|"]
        for s in STATS:
            lines.append(f"| {s} | " + " | ".join(_cell(r["models"][m][tk][s]) for m in MODELS) + " |")
        lines += [f"| fusion_gain_f1 | | | {_cell(r['fusion_gain_f1'][tk])} |", ""]
    return lines


def write_reports(metrics: dict, out_dir: Path, repo: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics_v2.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    md = ["# 2차 기준선 지표 (metrics_v2)", ""]
    md += [f"- 색인: {metrics['index']}, 라벨: {metrics['labels']}, 시험 기준일: {metrics['cutoff']} 이상 첫 수집"
           f", 상한: {metrics['test_until'] or '없음'} 이하 첫 수집",
           f"- 임계값(학습 OOF 오탐 2%): " + ", ".join(f"{MODEL_KO[m]} {v:.4f}" for m, v in metrics["thr_fpr2"].items()),
           "- 신뢰구간: 사이트(domain_hash) 단위 부트스트랩 1,000회, 95%", ""]
    md += _prev_table(repo, metrics)
    md += _subset_md("시험 세트 (전체)", metrics["test"])
    md += _subset_md("시험 세트: 주소만 바꾼 사이트(학습 사이트와 같은 미러 묶음)", metrics["test_mirror"])
    md += _subset_md("시험 세트: 처음 보는 사이트", metrics["test_unseen"])
    md += _subset_md("학습 세트 OOF (미러 묶음 단위 fold)", metrics["train_oof"])
    b = metrics["banner"]
    md += ["## 배너 사이트 (embedded_banner, 학습에 쓰지 않음)", "",
           f"사이트 {b['n']['sites']}, 화면 {b['n']['screens']}", "",
           "| 모델 | 임계값 | 도박으로 잡힌 화면 비율 | 한 화면이라도 잡힌 사이트 비율 |", "|---|---|---|---|"]
    for m in MODELS:
        for tk in THR_KEYS:
            c = b["models"][m][tk]
            md.append(f"| {MODEL_KO[m]} | {'0.5' if tk == '0.5' else 'OOF 2%'} | {_cell(c['screen_rate'])} | {_cell(c['site_rate'])} |")
    lg = metrics["legal"]
    md += ["", "## 합법 사행 묶음 (legal_gambling, 학습·시험에 쓰지 않음)", "",
           f"사이트 {lg['n']['sites']}, 화면 {lg['n']['screens']}", "",
           "| 판정 | 임계값 | 잡힌 화면 비율 | 한 화면이라도 잡힌 사이트 비율 |", "|---|---|---|---|",
           f"| 상표 낱말 규칙 | - | {_cell(lg['rule']['screen_rate'])} | {_cell(lg['rule']['site_rate'])} |"]
    for m in MODELS:
        for tk in THR_KEYS:
            c = lg["models"][m][tk]
            md.append(f"| {MODEL_KO[m]} (참고) | {'0.5' if tk == '0.5' else 'OOF 2%'} | "
                      f"{_cell(c['screen_rate'])} | {_cell(c['site_rate'])} |")
    f = metrics["rule_false_hits"]
    md += ["", "## 규칙이 합법 사행이 아닌 화면에서 켜진 비율", "",
           "| 묶음 | 화면 수 | 켜진 화면 | 비율 |", "|---|---|---|---|"]
    for k, name in (("test_hard_negative", "시험 하드 네거티브"), ("train_hard_negative", "학습 하드 네거티브"),
                    ("train_normal", "학습 정상"), ("banner", "배너"),
                    ("test_gambling", "시험 도박 (참고)"), ("train_gambling", "학습 도박 (참고)")):
        md.append(f"| {name} | {f[k]['screens']} | {f[k]['hits']} | {_pct(f[k]['rate'])} |")
    md += ["", "음성 화면(하드 네거티브+정상, 학습+시험)에서 낱말별로 켜진 화면 수 (많은 순)", ""]
    if f["by_term_negative"]:
        md += ["| 낱말 | 켜진 화면 |", "|---|---|"] + [f"| {t['term']} | {t['screens']} |" for t in f["by_term_negative"]]
    else:
        md.append("없음")
    md += [""]
    for key, title in (("test", "시험 세트 (전체)"), ("test_unseen", "시험 세트: 처음 보는 사이트")):
        r = metrics["text_plus_rule"][key]
        md += [f"## 글자 모델 + 규칙: {title}", "", "| 임계값 | 예측 | F1 | 정밀도 | 재현율 | 하드 네거티브 오탐률 |",
               "|---|---|---|---|---|---|"]
        for tk in THR_KEYS:
            for name, nm in (("text_only", "글자 단독"), ("text_or_rule", "글자 OR 규칙")):
                md.append(f"| {'0.5' if tk == '0.5' else 'OOF 2%'} | {nm} | "
                          + " | ".join(_cell(r[tk][name][s]) for s in RULE_STATS) + " |")
        md.append("")
    md += [f"어긋남 목록(학습 세트, OOF 융합): {metrics['n_disagreements']}화면 (비공개 CSV)", ""]
    (out_dir / "metrics_v2.md").write_text("\n".join(md), encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def evaluate2(
    index_path: Path = DEFAULT_INDEX, dataset_root: Path = HOME, labels_path: Path = DEFAULT_LABELS,
    cutoff: str = DEFAULT_CUTOFF, out_dir: Path | None = None, test_until: str | None = DEFAULT_TEST_UNTIL,
) -> dict:
    from .embed import embed_images
    from .ocr import run_ocr

    repo = Path(__file__).resolve().parents[2]
    out_dir = Path(out_dir or repo / "docs" / "week12")
    feats = Path(dataset_root) / "_features"
    samples = load_samples(index_path, dataset_root, include_embedded=True, labels_path=labels_path)
    ocr = run_ocr(samples, feats / "ocr")
    X = embed_images(samples, feats / "clip")
    texts = [ocr[s.id]["text"] for s in samples]
    test_mask = time_split(samples, cutoff, first_seen_from_index(index_path), until=test_until)
    out = run_core(samples, texts, X, test_mask, test_until=test_until)
    m, rows = out["metrics"], out["rows"]
    m |= {"cutoff": cutoff, "index": Path(index_path).name, "labels": Path(labels_path).name,
          "n_disagreements": len(out["disagree_idx"])}
    write_reports(m, out_dir, repo)
    cols = ["id", "domain_hash", "label", "split", "mirror_of_train", "page_kind", "rule_hit", "p_text", "p_image", "p_fusion"]
    _write_csv(feats / "predictions_v2.csv", cols, zip(*(rows[c] for c in cols)))
    dcols = ["id", "domain_hash", "label", "page_kind", "p_text", "p_image", "p_fusion", "full_path"]
    _write_csv(feats / "disagreements_v2.csv", dcols,
               ([rows[c][i] for c in dcols] for i in out["disagree_idx"]))
    return m
