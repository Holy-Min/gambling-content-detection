"""이미지 특징 추출기 비교: 글자 모델이 놓친 도박 화면을 얼마나 건지고, 글자가 통과시킨 정상 화면을 얼마나 덜 건드리는가.

`compare_core` 는 순수 함수(모델 로딩·파일 입출력 없음)이고 `compare_image` 가 입출력을 맡는다.
공개 산출물(md·json)에는 개수·비율만 쓴다(도메인·OCR 원문·경로·domain_hash 없음).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .data import Sample, load_samples
from .evaluate2 import (DEFAULT_CUTOFF, DEFAULT_INDEX, DEFAULT_LABELS, DEFAULT_TEST_UNTIL, HOME, _cell, _pct,
                        _rate_pair, _stat_fn, _triple, _write_csv)
from .metrics import TEXT_THR, f1, rescue_stats, rescue_threshold
from .models import image_model, text_model
from .split import first_seen_from_index, make_folds, mirror_groups, time_split

BUDGETS = (0.005, 0.01, 0.02, 0.05)
RANK_BUDGET = 0.01
FOUR = ("f1", "precision", "recall", "fpr_hard_negative")


def _four(y, label, kind, hashes, pred: np.ndarray, n_boot: int) -> dict:
    p = pred.astype(float)
    return {s: _triple(_stat_fn(s, y, label, kind, p, 0.5), hashes, n_boot) for s in FOUR}


def _clean_t(t: float) -> float | None:
    return None if not np.isfinite(t) else float(t)


def _subset_block(y, label, kind, hashes, p_text, p_img, t_by_budget: dict, t_comb: float, n_boot: int) -> dict:
    """한 부분집합(학습 OOF 또는 시험)에서 이미지 단독·융합·합친 판정 지표. 시험은 t 를 학습 OOF 에서 정한 값 그대로 쓴다."""
    text_pred = p_text >= TEXT_THR
    fusion = (p_text + p_img) / 2 >= 0.5
    comb = text_pred | (p_img >= t_comb)

    def gain(idx):
        return f1(y[idx], fusion[idx].astype(float), 0.5) - f1(y[idx], text_pred[idx].astype(float), 0.5)

    return {
        "n": {"screens": int(len(y)), "sites": int(len(set(hashes.tolist())))},
        "text_only": _four(y, label, kind, hashes, text_pred, n_boot),
        "image_only": _four(y, label, kind, hashes, p_img >= 0.5, n_boot),
        "fusion": {**_four(y, label, kind, hashes, fusion, n_boot), "f1_gain_vs_text": _triple(gain, hashes, n_boot)},
        "rescue": {str(b): rescue_stats(y, p_text, p_img, t) for b, t in t_by_budget.items()},
        "combined": _four(y, label, kind, hashes, comb, n_boot),
    }


def compare_core(
    samples: list[Sample], texts: list[str], X_mirror: np.ndarray, Xs: dict[str, np.ndarray],
    test_mask: np.ndarray, fp_budget: float = 0.01, n_boot: int = 1000, k: int = 5, seed: int = 42,
) -> dict:
    """samples(이진+배너+합법 사행 전체)·texts·X_mirror·Xs[key] 는 같은 순서.
    X_mirror 는 미러 묶음 계산용(기존 CLIP 특징): 모든 인코더가 같은 fold 를 쓰게 한다."""
    y_all = np.array([-1 if s.y is None else s.y for s in samples])
    texts_a = np.array(texts, dtype=object)
    hashes = np.array([s.domain_hash for s in samples], dtype=object)
    label = np.array([s.label for s in samples], dtype=object)
    kind = np.array([s.page_kind or "" for s in samples], dtype=object)
    is_bin = y_all >= 0
    tr_i = np.flatnonzero(is_bin & ~test_mask)
    te_i = np.flatnonzero(is_bin & test_mask)
    ba_i = np.flatnonzero(label == "embedded_banner")
    ytr, yte = y_all[tr_i], y_all[te_i]
    budgets = tuple(sorted(set(BUDGETS) | {fp_budget}))

    # 글자 모델: 인코더와 무관하게 한 번만(같은 fold, 임계값 0.5 고정)
    gid = mirror_groups(hashes[tr_i], X_mirror[tr_i], list(texts_a[tr_i]))
    folds = make_folds([samples[i] for i in tr_i], k=k, seed=seed, groups=gid)
    tr_texts = list(texts_a[tr_i])
    pt_oof = np.zeros(len(tr_i))
    for f in np.unique(folds):
        te_f = folds == f
        m = text_model().fit([t for t, b in zip(tr_texts, ~te_f) if b], ytr[~te_f])
        pt_oof[te_f] = m.predict_proba([t for t, b in zip(tr_texts, te_f) if b])[:, 1]
    tm = text_model().fit(tr_texts, ytr)
    pt_te = tm.predict_proba(list(texts_a[te_i]))[:, 1] if len(te_i) else np.zeros(0)
    pt_ba = tm.predict_proba(list(texts_a[ba_i]))[:, 1] if len(ba_i) else np.zeros(0)

    lab_tr, lab_te = label[tr_i], label[te_i]
    out: dict = {
        "budgets": list(budgets), "fp_budget": fp_budget, "text_thr": TEXT_THR,
        "n": {
            "train": {"screens": int(len(tr_i)), "sites": int(len(set(hashes[tr_i].tolist())))},
            "test": {"screens": int(len(te_i)), "sites": int(len(set(hashes[te_i].tolist())))},
            "banner": {"screens": int(len(ba_i)), "sites": int(len(set(hashes[ba_i].tolist())))},
        },
        "encoders": {},
    }
    rows = {"idx": np.concatenate([tr_i, te_i, ba_i]), "p_text": np.concatenate([pt_oof, pt_te, pt_ba]),
            "split": ["train"] * len(tr_i) + ["test"] * len(te_i) + ["banner"] * len(ba_i), "p_img": {}}

    for key, X in Xs.items():
        pi_oof = np.zeros(len(tr_i))
        Xtr = X[tr_i]
        for f in np.unique(folds):
            te_f = folds == f
            pi_oof[te_f] = image_model().fit(Xtr[~te_f], ytr[~te_f]).predict_proba(Xtr[te_f])[:, 1]
        im = image_model().fit(Xtr, ytr)
        pi_te = im.predict_proba(X[te_i])[:, 1] if len(te_i) else np.zeros(0)
        pi_ba = im.predict_proba(X[ba_i])[:, 1] if len(ba_i) else np.zeros(0)
        rows["p_img"][key] = np.concatenate([pi_oof, pi_te, pi_ba])

        # 임계값은 학습 OOF 의 B(음성 중 글자가 통과시킨 것)로만 정한다
        b_scores = pi_oof[(ytr == 0) & (pt_oof < TEXT_THR)]
        t_by = {b: rescue_threshold(ytr, pt_oof, pi_oof, b) for b in budgets}
        t_comb = t_by[fp_budget]
        blocks = {
            "train_oof": _subset_block(ytr, lab_tr, kind[tr_i], hashes[tr_i], pt_oof, pi_oof, t_by, t_comb, 0),
            "test": _subset_block(yte, lab_te, kind[te_i], hashes[te_i], pt_te, pi_te, t_by, t_comb, n_boot),
        }
        comb_ba = (pt_ba >= TEXT_THR) | (pi_ba >= t_comb)
        out["encoders"][key] = {
            "thresholds": {str(b): _clean_t(t) for b, t in t_by.items()},
            "train_b_screens": int(len(b_scores)),
            **blocks,
            "banner_combined": _rate_pair(comb_ba, hashes[ba_i], n_boot) if len(ba_i) else None,
        }

    def key_rank(k_: str):
        e = out["encoders"][k_]
        r = e["train_oof"]["rescue"][str(RANK_BUDGET)]["rescued"]["rate"]
        f = e["train_oof"]["image_only"]["f1"][0]
        return (-(-1.0 if r is None else r), -(-1.0 if f is None else f))
    out["ranking"] = sorted(out["encoders"], key=key_rank)
    out["text_only"] = {
        "train_oof": _four(ytr, lab_tr, kind[tr_i], hashes[tr_i], pt_oof >= TEXT_THR, 0),
        "test": _four(yte, lab_te, kind[te_i], hashes[te_i], pt_te >= TEXT_THR, n_boot),
    }
    out["_rows"] = {"idx": rows["idx"], "p_text": rows["p_text"], "split": rows["split"], "p_img": rows["p_img"]}
    return out


# ---- 보고서 ----

def _t(v) -> str:
    return "-" if v is None else f"{v:.4f}"


def _cnt(r: dict) -> str:
    return f"{_pct(r['rate'])} ({r['n']}/{r['d']})"


def render_md(res: dict) -> str:
    enc, ranking, n = res["encoders"], res["ranking"], res["n"]
    rk = str(RANK_BUDGET)
    md = ["# 이미지 특징 추출기 비교 (image_compare)", ""]
    md += [f"- 색인: {res['index']}, 라벨: {res['labels']}, 시험 기준일: {res['cutoff']} 이상 첫 수집"
           f", 상한: {res['test_until'] or '없음'} 이하 첫 수집",
           f"- 학습 화면 {n['train']['screens']}(사이트 {n['train']['sites']}), 시험 화면 {n['test']['screens']}"
           f"(사이트 {n['test']['sites']}), 배너 화면 {n['banner']['screens']}(사이트 {n['banner']['sites']})",
           f"- 글자 모델은 모든 비교에서 같다(임계값 {res['text_thr']} 고정, 같은 fold). 이미지 임계값은 학습 OOF 에서 정한다.",
           f"- 오탐 예산: {', '.join(f'{b:.1%}' for b in res['budgets'])} (합친 판정의 기본 예산 {res['fp_budget']:.1%})",
           f"- 장치: {res.get('device', '-')}",
           "- 신뢰구간: 사이트(domain_hash) 단위 부트스트랩 1,000회, 95%", "",
           "## 읽는 법", "",
           "- 건지기 분석: 글자가 놓친 도박 화면(A) 중 이미지가 잡는 비율과, 글자가 통과시킨 정상·하드 네거티브 화면(B) 중 이미지가 추가로 잘못 잡는 비율을 본다.",
           "- 순위는 학습 OOF 의 예산 1% 건진 비율이 높은 순이고, 동률이면 OOF 이미지 단독 F1 로 가른다.",
           "- 고르는 기준은 학습 데이터 안 교차검증 수치이고, 시험 세트 수치는 확인용이다.",
           "- 인코더마다 그 모델의 공식 전처리를 그대로 썼다. 전처리 방식이 모델마다 달라(가운데 자르기 또는 정사각형으로 눌러 맞추기) 타일 가장자리 일부가 모델에 들어가지 않거나 비율이 바뀔 수 있다. CLIP 은 타일 2장(2v)·8장(grid8) 모두 타일 면적의 약 10%가 잘린다.",
           "- ms/화면은 타일 수에 비례한다(grid8 은 타일 8장, 나머지는 2장).", "",
           "## 요약", "",
           f"| 순위 | 인코더 | OOF 건진 비율@{float(rk):.0%} | 시험 건진 비율@같은 임계값 | 시험 추가 오탐@같은 임계값 "
           f"| 합친 판정 시험 F1 | 합친 판정 시험 하드 네거티브 오탐률 | 이미지 단독 시험 F1 | 이미지 단독 시험 하드 네거티브 오탐률 "
           f"| ms/화면 | 이미지 파라미터 수 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    t0 = res["text_only"]["test"]
    md.append(f"| - | 글자 단독 | - | - | - | {_cell(t0['f1'])} | {_cell(t0['fpr_hard_negative'])} | - | - | - | - |")
    for i, k in enumerate(ranking, 1):
        e = enc[k]
        sp = e.get("speed") or {}
        ms = "-" if sp.get("ms_per_screen") is None else f"{sp['ms_per_screen']:.0f}"
        npar = "-" if sp.get("n_params_image") is None else f"{sp['n_params_image'] / 1e6:.1f}M"
        r_oof = e["train_oof"]["rescue"][rk]["rescued"]
        r_te = e["test"]["rescue"][rk]
        md.append(
            f"| {i} | {k} | {_cnt(r_oof)} | {_cnt(r_te['rescued'])} | {_cnt(r_te['extra_fp'])} "
            f"| {_cell(e['test']['combined']['f1'])} | {_cell(e['test']['combined']['fpr_hard_negative'])} "
            f"| {_cell(e['test']['image_only']['f1'])} | {_cell(e['test']['image_only']['fpr_hard_negative'])} "
            f"| {ms} | {npar} |")
    md += ["", f"요약 표의 건진 비율·추가 오탐은 예산 {float(rk):.1%} 의 임계값 기준이다. "
               f"합친 판정은 `글자>={res['text_thr']} OR 이미지>=t`, t 는 예산 {res['fp_budget']:.1%} 의 임계값이다.", ""]

    md += ["## 예산별 건지기 분석", "",
           "| 인코더 | 예산 | 임계값 t | OOF 건진 비율 | OOF 추가 오탐 | 시험 건진 비율 | 시험 추가 오탐 |", "|---|---|---|---|---|---|---|"]
    for k in ranking:
        e = enc[k]
        for b in res["budgets"]:
            ro, rt = e["train_oof"]["rescue"][str(b)], e["test"]["rescue"][str(b)]
            md.append(f"| {k} | {b:.1%} | {_t(e['thresholds'][str(b)])} | {_cnt(ro['rescued'])} | {_cnt(ro['extra_fp'])} "
                      f"| {_cnt(rt['rescued'])} | {_cnt(rt['extra_fp'])} |")
    md += ["", "건진 비율의 분모는 글자가 놓친 도박 화면, 추가 오탐의 분모는 글자가 통과시킨 음성 화면이다.", ""]

    md += [f"## 합친 판정 (예산 {res['fp_budget']:.1%})", "",
           "| 인코더 | 구분 | F1 | 정밀도 | 재현율 | 하드 네거티브 오탐률 |", "|---|---|---|---|---|---|"]
    to = res["text_only"]
    for nm, key in (("학습 OOF", "train_oof"), ("시험", "test")):
        md.append(f"| 글자 단독 | {nm} | " + " | ".join(_cell(to[key][s]) for s in FOUR) + " |")
    for k in ranking:
        for nm, key in (("학습 OOF", "train_oof"), ("시험", "test")):
            md.append(f"| {k} | {nm} | " + " | ".join(_cell(enc[k][key]["combined"][s]) for s in FOUR) + " |")
    md += ["", "## 평균 융합 (임계값 0.5)", "",
           "| 인코더 | 구분 | 융합 F1 | 융합 하드 네거티브 오탐률 | 글자 단독 대비 F1 차 |", "|---|---|---|---|---|"]
    for k in ranking:
        for nm, key in (("학습 OOF", "train_oof"), ("시험", "test")):
            f = enc[k][key]["fusion"]
            md.append(f"| {k} | {nm} | {_cell(f['f1'])} | {_cell(f['fpr_hard_negative'])} | {_cell(f['f1_gain_vs_text'])} |")
    md += ["", "## 이미지 단독 (임계값 0.5)", "",
           "| 인코더 | 구분 | F1 | 정밀도 | 재현율 | 하드 네거티브 오탐률 |", "|---|---|---|---|---|---|"]
    for k in ranking:
        for nm, key in (("학습 OOF", "train_oof"), ("시험", "test")):
            md.append(f"| {k} | {nm} | " + " | ".join(_cell(enc[k][key]["image_only"][s]) for s in FOUR) + " |")
    md += ["", f"## 참고: 배너 화면에서 합친 판정이 켜진 비율 (예산 {res['fp_budget']:.1%}, 전체 학습 모델)", "",
           "| 인코더 | 켜진 화면 비율 | 한 화면이라도 켜진 사이트 비율 |", "|---|---|---|"]
    for k in ranking:
        b = enc[k]["banner_combined"]
        md.append(f"| {k} | " + (" | ".join(_cell(b[x]) for x in ("screen_rate", "site_rate")) if b else "- | -") + " |")
    md.append("")
    return "\n".join(md)


def write_reports(res: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pub = {k: v for k, v in res.items() if not k.startswith("_")}
    (out_dir / "image_compare.json").write_text(
        json.dumps(pub, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (out_dir / "image_compare.md").write_text(render_md(res), encoding="utf-8")


def compare_image(
    index_path: Path = DEFAULT_INDEX, dataset_root: Path = HOME, labels_path: Path = DEFAULT_LABELS,
    cutoff: str = DEFAULT_CUTOFF, out_dir: Path | None = None, test_until: str | None = DEFAULT_TEST_UNTIL,
    encoders: list[str] | None = None, fp_budget: float = 0.01,
) -> dict:
    from .embed import DEFAULT_COMPARE_ENCODERS, _default_device, embed_with, encoder_info, time_encoder
    from .ocr import run_ocr

    encoders = list(encoders or DEFAULT_COMPARE_ENCODERS)
    repo = Path(__file__).resolve().parents[2]
    out_dir = Path(out_dir or repo / "docs" / "week12")
    feats = Path(dataset_root) / "_features"
    samples = load_samples(index_path, dataset_root, include_embedded=True, labels_path=labels_path)
    ocr = run_ocr(samples, feats / "ocr")
    texts = [ocr[s.id]["text"] for s in samples]
    Xs = {k: embed_with(samples, feats, k) for k in encoders}
    X_mirror = Xs["clip-b32"] if "clip-b32" in Xs else embed_with(samples, feats, "clip-b32")
    test_mask = time_split(samples, cutoff, first_seen_from_index(index_path), until=test_until)
    res = compare_core(samples, texts, X_mirror, Xs, test_mask, fp_budget=fp_budget)

    device = _default_device()
    labeled = [s for s in samples if s.y is not None]
    for k in encoders:
        info = encoder_info(k, device)
        res["encoders"][k]["speed"] = {"ms_per_screen": time_encoder(labeled, k, device), **info}
    res |= {"cutoff": cutoff, "index": Path(index_path).name, "labels": Path(labels_path).name,
            "test_until": test_until, "device": device}
    write_reports(res, out_dir)

    rows = res["_rows"]
    ids = [samples[i].id for i in rows["idx"]]
    hs = [samples[i].domain_hash for i in rows["idx"]]
    lab = [samples[i].label for i in rows["idx"]]
    pk = [samples[i].page_kind or "" for i in rows["idx"]]
    cols = ["id", "domain_hash", "label", "split", "page_kind", "p_text"] + [f"p_img__{k}" for k in encoders]
    data = [ids, hs, lab, rows["split"], pk, rows["p_text"].tolist()] + [rows["p_img"][k].tolist() for k in encoders]
    _write_csv(feats / "predictions_image.csv", cols, zip(*data))
    return res
