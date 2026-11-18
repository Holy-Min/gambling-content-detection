"""3모델 out-of-fold 평가 → 공개 산출물(개수·비율·해시만)과 비공개 산출물(OCR 원문 포함)."""
from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import embed as embed_mod
from .data import Sample, load_samples
from .embed import embed_images
from .metrics import bootstrap_ci, confusion, f1, rate, threshold_for_fpr
from .models import fit_full, ngram_contributions, oof_predict, top_ngrams
from .ocr import run_ocr
from .split import make_folds, mirror_groups

HOME = Path.home() / "datasets" / "gambling"
DEFAULT_INDEX = HOME / "_features" / "index_snapshot_20261109T1400.jsonl"
EXPECTED = {  # 스냅숏 기준 화면/도메인 (컨트롤러가 확정한 값)
    "gambling": (263, 78), "hard_negative": (138, 25), "normal": (74, 8), "embedded_banner": (117, 19),
}
EXPECTED_DEPOSIT = (40, 17)
TARGETS = {
    "f1": 0.90, "fpr_hard_negative": 0.02, "recall_deposit": 0.90, "fusion_gain_f1": 0.03,
}
SUSPECT_HASHES = ("009f5ba41893", "eaacd8017fc9", "acf4d36c3f04", "2fd53dff660c")  # 라벨 불일치 의심(사후 지정)
SEEDS = [42, 0, 1, 2, 3, 4, 5, 6]  # 42 는 사전 지정한 헤드라인 fold 배정, 나머지는 변동 폭 확인용
WIDE_PX = 1000  # 이 폭 이상은 데스크톱 레이아웃 캡처(폰 캡처는 824~912px)
VAR_STATS = ("f1", "fpr_hard_negative", "fpr_normal", "recall_deposit", "recall_at_fpr2")
MODEL_KO = {"text": "텍스트", "image": "이미지", "fusion": "융합"}
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def count_samples(samples: list[Sample]) -> dict:
    screens: dict[str, int] = defaultdict(int)
    doms: dict[str, set] = defaultdict(set)
    for s in samples:
        screens[s.label] += 1
        doms[s.label].add(s.domain)
    dep = [s for s in samples if s.label == "gambling" and s.page_kind == "deposit"]
    return {
        "screens": dict(screens) | {"gambling_deposit": len(dep)},
        "domains": {k: len(v) for k, v in doms.items()} | {"gambling_deposit": len({s.domain for s in dep})},
    }


def _print_counts(n: dict) -> None:
    print("평가 데이터 (화면쪽/도메인):")
    for label, (es, ed) in EXPECTED.items():
        s, d = n["screens"].get(label, 0), n["domains"].get(label, 0)
        flag = "" if (s, d) == (es, ed) else f"  <-- 기대값 {es}/{ed} 와 다름"
        print(f"  {label}: {s}/{d}{flag}")
    s, d = n["screens"]["gambling_deposit"], n["domains"]["gambling_deposit"]
    flag = "" if (s, d) == EXPECTED_DEPOSIT else f"  <-- 기대값 {EXPECTED_DEPOSIT[0]}/{EXPECTED_DEPOSIT[1]} 와 다름"
    print(f"  gambling_deposit: {s}/{d}{flag}")


def _nan_div(a: float, b: float) -> float:
    return float("nan") if b == 0 else a / b


def _stat_fns(y, label, kind, p, thr=0.5):
    hn = label == "hard_negative"
    nm = label == "normal"
    dep = (y == 1) & (kind == "deposit")

    def cm(idx):
        return confusion(y[idx], p[idx], thr)

    def sub(mask):
        def fn(idx):
            m = mask[idx]
            return rate(p[idx][m] >= thr) if m.any() else float("nan")
        return fn

    return {
        "f1": lambda idx: f1(y[idx], p[idx], thr),
        "precision": lambda idx: _nan_div(cm(idx)["tp"], cm(idx)["tp"] + cm(idx)["fp"]),
        "recall": lambda idx: _nan_div(cm(idx)["tp"], cm(idx)["tp"] + cm(idx)["fn"]),
        "fpr_hard_negative": sub(hn),
        "fpr_normal": sub(nm),
        "recall_deposit": sub(dep),
    }


def score_scenario(y, label, kind, P, groups, keep=None, n_boot: int = 1000) -> dict:
    """OOF 확률 P(모델별)로 지표·그룹 단위 부트스트랩 구간. keep 이 있으면 그 화면만(재학습 없이) 센다."""
    if keep is not None:
        y, label, kind, groups = y[keep], label[keep], kind[keep], groups[keep]
        P = {k: v[keep] for k, v in P.items()}
    idx_all = np.arange(len(y))
    models_out, point = {}, {}
    for name in ("text", "image", "fusion"):
        entry = {}
        for m, fn in _stat_fns(y, label, kind, P[name]).items():
            v = fn(idx_all)
            lo, hi, valid = bootstrap_ci(fn, groups, n=n_boot, seed=42)
            entry[m] = [v, lo, hi]
            entry[m + "_valid_resamples"] = valid
        thr = threshold_for_fpr(P[name][label == "hard_negative"], 0.02)
        entry["thr_at_fpr2"] = thr
        entry["recall_at_fpr2"] = float((P[name][y == 1] >= thr).mean())
        models_out[name] = entry
        point[name] = entry["f1"][0]
    gain_fn = lambda idx: (
        f1(y[idx], P["fusion"][idx])
        - max(f1(y[idx], P["text"][idx]), f1(y[idx], P["image"][idx]))
    )
    glo, ghi, gvalid = bootstrap_ci(gain_fn, groups, n=n_boot, seed=42)
    return {
        "n_screens": int(len(y)),
        "n_groups": int(len(np.unique(groups))),
        "models": models_out,
        "fusion_gain_f1": point["fusion"] - max(point["text"], point["image"]),
        "fusion_gain_f1_ci": [glo, ghi, gvalid],
    }


def _ocr_chars(text: str) -> int:
    return len("".join(text.split()))


def _run_stats(y, label, kind, P) -> dict:
    """한 번의 OOF 예측에서 모델별 점추정(변동 분석용). score_scenario 의 점추정과 같은 정의."""
    out = {}
    idx = np.arange(len(y))
    for name in ("text", "image", "fusion"):
        fns = _stat_fns(y, label, kind, P[name])
        e = {m: fns[m](idx) for m in ("f1", "fpr_hard_negative", "fpr_normal", "recall_deposit")}
        thr = threshold_for_fpr(P[name][label == "hard_negative"], 0.02)
        e["recall_at_fpr2"] = float((P[name][y == 1] >= thr).mean())
        out[name] = e
    out["gain_f1"] = out["fusion"]["f1"] - max(out["text"]["f1"], out["image"]["f1"])
    return out


def _spread(vals: list[float], head: float) -> dict:
    v = np.array(vals, dtype=float)
    return {"min": float(np.nanmin(v)), "median": float(np.nanmedian(v)), "max": float(np.nanmax(v)), "seed42": float(head)}


def seed_variability(samples, texts, X, y, label, kind, scen_groups: dict, seeds=SEEDS) -> dict:
    """fold 배정 seed 만 바꿔 다시 학습·예측했을 때 지표가 얼마나 움직이는지(시나리오별 최소·중앙·최대).
    seeds[0] 은 헤드라인 seed(42)여야 한다."""
    out = {}
    for key, groups in scen_groups.items():
        runs = []
        for sd in seeds:
            folds = make_folds(samples, groups=groups, seed=sd)
            runs.append(_run_stats(y, label, kind, oof_predict(texts, X, y, folds)))
        models = {name: {st: _spread([r[name][st] for r in runs], runs[0][name][st]) for st in VAR_STATS}
                  for name in ("text", "image", "fusion")}
        out[key] = {"seeds": list(seeds), "models": models,
                    "fusion_gain_f1": _spread([r["gain_f1"] for r in runs], runs[0]["gain_f1"])}
    return out


def data_notes(samples, ocr, P_by_scen: dict) -> dict:
    """평가 데이터의 한계 수치: 빈 캡처 수, 하드 네거티브 중 데스크톱 폭 화면과 그 오탐률(융합, 0.5)."""
    from PIL import Image

    label = np.array([s.label for s in samples])
    wide = np.zeros(len(samples), dtype=bool)
    blank = np.zeros(len(samples), dtype=bool)
    for i, s in enumerate(samples):
        with Image.open(s.image_path) as im:
            wide[i] = im.width >= WIDE_PX
            flat = float(np.asarray(im.convert("L"), dtype=float).std()) < 2
        blank[i] = flat or _ocr_chars(ocr[s.id]["text"]) == 0
    hn = label == "hard_negative"
    fpr = {}
    for key, P in P_by_scen.items():
        pred = np.asarray(P["fusion"]) >= 0.5
        fpr[key] = {"wide": float(pred[hn & wide].mean()), "phone": float(pred[hn & ~wide].mean())}
    return {
        "blank_screens": {k: int((blank & (label == k)).sum()) for k in ("gambling", "hard_negative", "normal")
                          if (blank & (label == k)).any()},
        "hard_negative_wide": {
            "screens": int((hn & wide).sum()), "of": int(hn.sum()),
            "domains": len({s.domain for s, w, h in zip(samples, wide, hn) if w and h}),
            "min_width_px": WIDE_PX, "fpr_fusion": fpr,
        },
    }


def _timing(samples, X, ocr, text_pipe, img_pipe, texts, k=20, seed=42) -> dict:
    import torch

    rng = np.random.default_rng(seed)
    pick = rng.choice(len(samples), size=min(k, len(samples)), replace=False)
    device = embed_mod._default_device()
    model, processor = embed_mod._load_model("openai/clip-vit-base-patch32", device)
    for i in pick[:2]:  # 워밍업(캐시 쓰지 않음)
        inp = processor(images=embed_mod._tiles(samples[i]), return_tensors="pt")
        with torch.no_grad():
            model.get_image_features(pixel_values=inp["pixel_values"].to(device))
    t_embed, t_cls = [], []
    for i in pick:
        t0 = time.perf_counter()
        inp = processor(images=embed_mod._tiles(samples[i]), return_tensors="pt")
        with torch.no_grad():
            feats = model.get_image_features(pixel_values=inp["pixel_values"].to(device))
        if not isinstance(feats, torch.Tensor):
            feats = feats.pooler_output
        embed_mod._normalize(feats.float().cpu().numpy().mean(axis=0))
        t_embed.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        a = text_pipe.predict_proba([texts[i]])[:, 1]
        b = img_pipe.predict_proba(X[i : i + 1])[:, 1]
        _ = (a + b) / 2
        t_cls.append((time.perf_counter() - t0) * 1000)
    return {
        "ocr": float(np.median([ocr[s.id]["ms"] for s in samples])),
        "embed": float(np.median(t_embed)),
        "classify": float(np.median(t_cls)),
    }


def _signal(p_text, p_image):
    """도박 쪽 확률을 누가 끌어올렸는지."""
    if p_image >= 0.8 and p_text < 0.5:
        return "이미지 주도"
    if p_text >= 0.8 and p_image < 0.5:
        return "글자 주도"
    return "둘 다/혼합"


def _cause(label, kind, chars, is_fp, signal="둘 다/혼합"):
    if chars < 20:
        return "글자 거의 없는 화면"
    if kind == "login":
        return "로그인 화면"
    if is_fp and label == "hard_negative":
        if signal == "이미지 주도":
            return "화면 모양이 도박 화면과 비슷(이미지 주도, 확인 필요)"
        return "정상 결제·게임 문구 유사"
    return "기타(확인 필요)"


def evaluate(index_path: Path = DEFAULT_INDEX, dataset_root: Path = HOME, out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or Path(__file__).resolve().parents[2] / "docs" / "week11")
    feats = Path(dataset_root) / "_features"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"인덱스: {index_path}")
    allsamp = load_samples(index_path, dataset_root, include_embedded=True)
    samples = [s for s in allsamp if s.y is not None]
    emb_samples = [s for s in allsamp if s.y is None]
    n = count_samples(allsamp)
    _print_counts(n)

    ocr = run_ocr(allsamp, feats / "ocr")
    X_all = embed_images(allsamp, feats / "clip")
    pos = {s.id: i for i, s in enumerate(allsamp)}
    X = X_all[[pos[s.id] for s in samples]]
    X_emb = X_all[[pos[s.id] for s in emb_samples]]
    texts = [ocr[s.id]["text"] for s in samples]
    y = np.array([s.y for s in samples])
    label = np.array([s.label for s in samples])
    kind = np.array([s.page_kind or "" for s in samples], dtype=object)
    domain = np.array([s.domain for s in samples])
    gid = mirror_groups(domain, X, texts)  # 시나리오 B: 처음 보는 사이트(미러 묶음 단위)
    scen_defs = {"domain": domain, "mirror_cluster": gid}
    suspect = np.isin(np.array([s.domain_hash for s in samples]), SUSPECT_HASHES)
    scen, preds = {}, {}
    text_models: dict = {}
    for key, groups in scen_defs.items():
        folds = make_folds(samples, groups=groups)
        for f in np.unique(folds):  # 누수 방지 확인: 한 그룹은 한 fold 에만
            assert not (set(groups[folds == f]) & set(groups[folds != f])), "group leaked across folds"
        P = oof_predict(texts, X, y, folds, text_models_out=text_models if key == "domain" else None)
        res = score_scenario(y, label, kind, P, groups)
        res["sensitivity_excluding_suspect_labels"] = score_scenario(y, label, kind, P, groups, keep=~suspect)
        res["sensitivity_excluding_suspect_labels"]["excluded_screens"] = int(suspect.sum())
        scen[key] = res
        preds[key] = (P, folds, groups)
    P, folds, _ = preds["domain"]
    models_out = scen["domain"]["models"]
    gain = scen["domain"]["fusion_gain_f1"]
    glo, ghi, gvalid = scen["domain"]["fusion_gain_f1_ci"]

    # 최종 모델(전체 475화면 학습) → embedded_banner 판정 비율
    tfull, ifull = fit_full(texts, X, y)
    e_texts = [ocr[s.id]["text"] for s in emb_samples]
    p_emb = (tfull.predict_proba(e_texts)[:, 1] + ifull.predict_proba(X_emb)[:, 1]) / 2
    emb_rate = float((p_emb >= 0.5).mean())

    var = seed_variability(samples, texts, X, y, label, kind, scen_defs)
    notes = data_notes(samples, ocr, {k: v[0] for k, v in preds.items()})
    timing = _timing(samples, X, ocr, tfull, ifull, texts)

    metrics = {
        "snapshot": Path(index_path).name,
        "n": n,
        "models": models_out,
        "fusion_gain_f1": gain,
        "fusion_gain_f1_ci": [glo, ghi, gvalid],
        "scenarios": scen,
        "targets": TARGETS,
        "embedded_banner_flag_rate": [emb_rate, len(emb_samples), n["domains"].get("embedded_banner", 0)],
        "timing_ms_median": timing,
        "seed_variability": var,
        "data_notes": notes,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_private(samples, texts, ocr, P, folds, text_models, feats, preds["mirror_cluster"])
    _write_md(metrics, out_dir / "metrics.md")
    _write_error_analysis(samples, y, P, ocr, out_dir / "error_analysis.md")
    _write_figures(metrics, P, y, out_dir)
    _print_summary(metrics)
    return metrics

def _write_private(samples, texts, ocr, P, folds, text_models, feats, scen_b) -> None:
    PB, folds_b, groups_b = scen_b
    with (feats / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "domain", "label", "page_kind", "p_text", "p_image", "p_fusion", "fold",
                    "p_text_mirror", "p_image_mirror", "p_fusion_mirror", "fold_mirror", "mirror_group"])
        for i, s in enumerate(samples):
            w.writerow([s.id, s.domain, s.label, s.page_kind or "", f"{P['text'][i]:.6f}",
                        f"{P['image'][i]:.6f}", f"{P['fusion'][i]:.6f}", int(folds[i]),
                        f"{PB['text'][i]:.6f}", f"{PB['image'][i]:.6f}", f"{PB['fusion'][i]:.6f}",
                        int(folds_b[i]), int(groups_b[i])])
    screens = []
    agg: dict[str, dict] = defaultdict(lambda: {"sum": 0.0, "screens": 0, "domains": set()})
    for i, s in enumerate(samples):
        if P["fusion"][i] < 0.5:
            continue
        tm = text_models[int(folds[i])]
        contrib = ngram_contributions(tm, texts[i])
        grams = top_ngrams(tm, texts[i], k=3)
        lines = []
        for g in grams:
            gs = g.strip()
            for l in ocr[s.id]["lines"]:
                if gs and gs in l["text"].lower() and l["text"] not in lines:
                    lines.append(l["text"])
        screens.append({"id": s.id, "domain": s.domain, "domain_hash": s.domain_hash, "label": s.label,
                        "page_kind": s.page_kind, "p_fusion": float(P["fusion"][i]),
                        "ngrams": grams, "lines": lines[:5]})
        if s.y == 1:  # 양성 판정된 도박 화면(진양성)
            for g, c in contrib.items():
                a = agg[g]
                a["sum"] += c
                a["screens"] += 1
                a["domains"].add(s.domain)
    top = sorted(agg.items(), key=lambda kv: -kv[1]["sum"])[:30]
    top_out = [{"ngram": g, "sum_contribution": v["sum"], "screens": v["screens"], "domains": len(v["domains"])}
               for g, v in top]
    (feats / "evidence.json").write_text(
        json.dumps({"top_evidence_ngrams": top_out, "screens": screens}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def _fmt(v: list, pct=True) -> str:
    if pct:
        return f"{v[0]*100:.1f}% [{v[1]*100:.1f}~{v[2]*100:.1f}]"
    return f"{v[0]:.3f} [{v[1]:.3f}~{v[2]:.3f}]"


ROWS = [
    ("F1", "f1", ">= 0.90", lambda v: v >= 0.90),
    ("정밀도", "precision", "-", None),
    ("재현율(도박 화면을 잡은 비율)", "recall", "-", None),
    ("하드 네거티브 오탐률", "fpr_hard_negative", "<= 2%", lambda v: v <= 0.02),
    ("일반 화면(normal) 오탐률", "fpr_normal", "-", None),
    ("충전 화면 재현율", "recall_deposit", ">= 90%", lambda v: v >= 0.90),
]


def _table(sc: dict) -> list[str]:
    M = sc["models"]
    L = ["| 지표 | 텍스트 | 이미지 | 융합 | 목표 | 융합 달성 |", "|---|---|---|---|---|---|"]
    for ko, key, tgt, ok in ROWS:
        cells = [_fmt(M[k][key], pct=(key != "f1")) for k in ("text", "image", "fusion")]
        ach = "-" if ok is None else ("달성" if ok(M["fusion"][key][0]) else "미달")
        L.append(f"| {ko} | " + " | ".join(cells) + f" | {tgt} | {ach} |")
    g, gl = sc["fusion_gain_f1"], sc["fusion_gain_f1_ci"]
    L.append(f"| 융합 이득(F1 − 단독 최고) | - | - | {g:+.3f} [{gl[0]:+.3f}~{gl[1]:+.3f}] | >= +0.03 | "
             f"{'달성' if g >= 0.03 else '미달'} |")
    L += ["", "| 모델 | 하드 네거티브 오탐률 2% 임계값 | 그때의 재현율 |", "|---|---|---|"]
    for k in ("text", "image", "fusion"):
        L.append(f"| {MODEL_KO[k]} | {M[k]['thr_at_fpr2']:.3f} | {M[k]['recall_at_fpr2']*100:.1f}% |")
    return L


def _sens_table(sc: dict, sc_name: str) -> list[str]:
    s = sc["sensitivity_excluding_suspect_labels"]
    L = [f"**{sc_name}** (제외 {s['excluded_screens']}쪽, 남은 {s['n_screens']}쪽/{s['n_groups']}개 묶음)", "",
         "| 모델 | F1 | 하드 네거티브 오탐률 | 충전 재현율 |", "|---|---|---|---|"]
    for k in ("text", "image", "fusion"):
        e = s["models"][k]
        L.append(f"| {MODEL_KO[k]} | {_fmt(e['f1'], pct=False)} | {_fmt(e['fpr_hard_negative'])} | {_fmt(e['recall_deposit'])} |")
    g = s["fusion_gain_f1"]
    L += ["", f"융합 이득 {g:+.3f}, 하드 네거티브 오탐률 2% 임계값 재현율(융합) {s['models']['fusion']['recall_at_fpr2']*100:.1f}%", ""]
    return L


def _variability_md(m: dict) -> list[str]:
    var = m["seed_variability"]
    sd = var["domain"]["seeds"]
    L = ["## fold 배정만 바꿨을 때의 변동", "",
         f"fold 배정 seed 를 {len(sd)}가지({', '.join(map(str, sd))})로 바꿔 두 상황 모두 처음부터 다시 학습·예측한 뒤 "
         "최소~최대(중앙값)를 적었어요. **seed 42 는 결과를 보기 전에 정한 값이고 위 A·B 표의 수치가 이 값이에요.**", "",
         "| 상황 | 모델 | F1 | 하드 네거티브 오탐률 | 일반 오탐률 | 충전 재현율 | 오탐률 2% 때 재현율 |", "|---|---|---|---|---|---|---|"]

    def cell(s: dict, pct: bool) -> str:
        k = 100 if pct else 1
        f = "{:.1f}" if pct else "{:.3f}"
        return f"{f.format(s['min']*k)}~{f.format(s['max']*k)} ({f.format(s['median']*k)})" + ("%" if pct else "")

    for key, ko in (("domain", "A 새 주소"), ("mirror_cluster", "B 미러 묶음")):
        for name in ("text", "image", "fusion"):
            e = var[key]["models"][name]
            L.append(f"| {ko} | {MODEL_KO[name]} | {cell(e['f1'], False)} | {cell(e['fpr_hard_negative'], True)} | "
                     f"{cell(e['fpr_normal'], True)} | {cell(e['recall_deposit'], True)} | {cell(e['recall_at_fpr2'], True)} |")
    ga, gb = var["domain"]["fusion_gain_f1"], var["mirror_cluster"]["fusion_gain_f1"]
    L += ["", f"융합 이득(F1): A {ga['min']:+.3f}~{ga['max']:+.3f}, B {gb['min']:+.3f}~{gb['max']:+.3f}.", "",
          "fold 배정만 바꿔도 F1 이 ±0.01~0.02, 오탐률이 ±3~4%p 움직여요. 이 변동은 위 신뢰구간(부트스트랩)에 들어 있지 않아요. "
          "seed 42 는 미리 정한 값이에요.", ""]
    return L


def _notes_md(m: dict) -> list[str]:
    n = m["data_notes"]
    w = n["hard_negative_wide"]
    fa, fb = w["fpr_fusion"]["domain"], w["fpr_fusion"]["mirror_cluster"]
    b = n["blank_screens"]
    names = {"gambling": "도박", "hard_negative": "하드 네거티브", "normal": "일반"}
    blank_txt = ", ".join(f"{names[k]} {v}" for k, v in b.items())
    return [
        f"- 하드 네거티브 {w['of']}쪽 중 {w['screens']}쪽({w['domains']}개 도메인)은 데스크톱 레이아웃(폭 {w['min_width_px']}px 이상) 캡처예요. "
        f"융합 오탐률은 이 화면에서 A {fa['wide']*100:.1f}%·B {fb['wide']*100:.1f}%, 폰 폭 화면에서 A {fa['phone']*100:.1f}%·B {fb['phone']*100:.1f}%라서, "
        "하드 네거티브 오탐률이 낮게 보이는 데 데스크톱 화면이 일부 기여해요. 폰 화면 기준으로는 더 높게 읽어야 해요.",
        f"- 완전히 빈(한 가지 색이거나 OCR 글자가 없는) 캡처 {sum(b.values())}쪽({blank_txt})이 평가에 들어 있어요. "
        "수치를 비교할 수 있게 빼지 않았어요.",
    ]


def _write_md(m: dict, path: Path) -> None:
    n = m["n"]
    A, B = m["scenarios"]["domain"], m["scenarios"]["mirror_cluster"]
    L = ["# 1차 모델 평가 (out-of-fold, 임계값 0.5)", "",
         f"데이터: 스냅숏 `{m['snapshot']}`. 모든 수치는 화면(쪽) 단위이고, 같은 묶음의 화면은 한 번도 학습에 쓰이지 않은 fold 에서만 판정했어요.", "",
         "## 두 가지 평가 상황", "",
         "- **A. 새 주소 (도메인 단위 분할)**: 같은 사이트가 주소만 바꿔 다시 나타난 경우예요. 주소가 바뀌어도 화면이 거의 같은 "
         "미러 사이트는 서로 다른 도메인으로 세어 학습과 평가에 나뉘어 들어갈 수 있어요. 앱이 \"주소가 바뀌어도\" 같은 운영자의 화면을 알아보는지를 가늠해요.",
         "- **B. 처음 보는 사이트 (미러 묶음 단위 분할)**: 화면 모양이 거의 같거나(이미지 유사도 0.98 초과) OCR 글자가 똑같은 도메인을 "
         "한 묶음으로 보고, 묶음 전체를 학습에서 뺀 채 판정해요. 거의 같은 화면(미러)을 가진 사이트를 묶어 뺀 상황이라 처음 보는 사이트에 가까워요(완전히 처음 보는 사이트는 아니에요). 제품에는 이쪽이 더 보수적인(엄격한) 기준이에요.",
         "- 묶음은 라벨을 보지 않고 위 규칙으로만 만들었어요. 한 묶음은 한 fold 에만 들어가고, 신뢰구간도 묶음 단위로 다시 뽑아요.", "",
         "## A. 새 주소 (도메인 단위)", "", f"{A['n_screens']}쪽 / 도메인 {A['n_groups']}개", ""]
    L += _table(A)
    L += ["", "## B. 처음 보는 사이트 (미러 묶음 단위)", "", f"{B['n_screens']}쪽 / 묶음 {B['n_groups']}개 (도메인 {A['n_groups']}개를 묶은 것)", ""]
    L += _table(B)
    L += ["", "F1은 도박 화면을 놓치지 않으면서 잘못 잡지도 않는 정도를 한 숫자로 합친 점수(1에 가까울수록 좋음), "
          "오탐률은 정상 화면을 도박으로 잘못 잡은 비율(낮을수록 좋음), 재현율은 실제 도박 화면 중 제대로 잡은 비율(높을수록 좋음)이에요.", "",
          "대괄호는 95% 신뢰구간이에요. 학습을 다시 하지 않고, 이미 나온 out-of-fold 예측을 도메인(또는 묶음) 단위로 1,000번 다시 뽑아 계산했어요. "
          "[100~100]처럼 폭이 0인 구간은 어느 재표본에서도 놓친 화면이 없었다는 뜻이지 확실하다는 뜻이 아니에요(퇴화한 구간). "
          "도메인이 적어(도박 78개, 음성 33개) 구간이 넓으니 1차 결과로 읽어 주세요. 하드 네거티브 오탐률 2% 임계값은 같은 out-of-fold 점수로 정해서 다소 낙관적인 참고치예요.", "",
          "## 참고: 라벨 오류 의심 4곳 제외", "",
          "도박 라벨이지만 화면 내용이 맞지 않는 도메인 4곳(바카라 정보 글, 카지노 후기·제휴 글, 무료 영화 스트리밍, 봇 확인 화면이 ok 로 저장된 것)을 "
          "뺀 뒤 같은 out-of-fold 예측으로 다시 센 값이에요(재학습 없음). **이 4곳은 오류 화면을 본 뒤에 찾은 것(사후 지정)이라 "
          "결과가 유리하게 나올 수 있어요.** 라벨은 라벨링 가이드로 다시 검토할 예정이고, 본 지표는 위 A·B 표예요.", ""]
    L += _sens_table(A, "A. 새 주소") + _sens_table(B, "B. 처음 보는 사이트")
    L += ["## 표본 수", "", "| 구분 | 화면(쪽) | 도메인 |", "|---|---|---|"]
    for k, ko in (("gambling", "도박(양성)"), ("gambling_deposit", "  그중 충전 화면"),
                  ("hard_negative", "하드 네거티브"), ("normal", "일반(normal)"),
                  ("embedded_banner", "배너 포함(학습·평가 제외)")):
        L.append(f"| {ko} | {n['screens'].get(k, 0)} | {n['domains'].get(k, 0)} |")
    e = m["embedded_banner_flag_rate"]
    t = m["timing_ms_median"]
    L += ["", f"평가에 쓴 475쪽의 도메인 {A['n_groups']}개는 미러 묶음 {B['n_groups']}개로 묶여요.", "",
          "## 배너 포함 화면 판정 비율", "",
          f"전체 데이터로 학습한 최종 모델(융합, 0.5)이 배너 포함 화면 {e[1]}쪽/{e[2]}개 도메인 중 도박으로 판정한 비율은 "
          f"{e[0]*100:.1f}%예요. 이 값은 합격·불합격이 아니라, 약속 카드가 떠야 하는지(조기 경고인지 과잉 개입인지)를 "
          "사용자 테스트에서 정할 열린 질문이에요.", "",
          "## 화면 1장당 처리 시간 중앙값 (맥, 참고)", "",
          f"OCR {t['ocr']:.0f} ms · 이미지 임베딩 {t['embed']:.0f} ms · 분류 {t['classify']:.1f} ms", "",
          ] + _variability_md(m) + [
          "## 한계", "",
          "- 라벨은 도메인 단위 시드 라벨이고 충전 화면(page_kind)은 수집기의 휴리스틱이에요.",
          "- 같은 운영자의 미러 사이트 때문에 융합·이미지는 A 가 B 보다 높게 나와요. 텍스트는 이번 분할(seed 42)에서 B 가 조금 높지만, "
          "fold 배정만 바꿔도 뒤집히는 범위 안(위 변동 표)이에요. 처음 보는 사이트에 대한 기대는 B 를 기준으로 보세요.",
          *_notes_md(m),
          "- 판정 근거로 뽑힌 상위 글자 조각에 가입·로그인 같은 일반 단어가 섞여 있어, 모델이 이런 단어를 지름길로 쓸 가능성이 있어요. 시안의 근거 칩에서는 이런 일반 단어를 뺐어요.",
          "- 표본이 작아 구간이 넓어요."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _write_error_analysis(samples, y, P, ocr, path: Path) -> None:
    pf = P["fusion"]
    rec = []
    for i, s in enumerate(samples):
        chars = _ocr_chars(ocr[s.id]["text"])
        rec.append((i, s, chars))
    fps = [(i, s, c) for i, s, c in rec if y[i] == 0 and pf[i] >= 0.5]
    fns_all = [(i, s, c) for i, s, c in rec if y[i] == 1 and pf[i] < 0.5]
    fns = sorted(fns_all, key=lambda r: pf[r[0]])[:10]

    def table(items, is_fp):
        out = ["| domain_hash | 라벨 | 화면 종류 | OCR 글자 수 | p_text | p_image | 융합 | 주도 신호 | 추정 원인 |",
               "|---|---|---|---|---|---|---|---|---|"]
        for i, s, c in items:
            sig = _signal(P["text"][i], P["image"][i]) if is_fp else "-"
            out.append(f"| {s.domain_hash} | {s.label} | {s.page_kind or '-'} | {c} | {P['text'][i]:.2f} | "
                       f"{P['image'][i]:.2f} | {pf[i]:.2f} | {sig} | {_cause(s.label, s.page_kind, c, is_fp, sig)} |")
        return out

    L = ["# 오류 분석 (융합, 임계값 0.5, out-of-fold, 시나리오 A·새 주소 기준)", "",
         "이미지·OCR 원문·도메인 이름 없이 도메인 해시만 적었어요. 원인은 규칙으로 붙인 추정이에요(글자 20자 미만, 로그인 화면, "
         "하드 네거티브 오탐, 그 외). 주도 신호는 오탐에만 붙여요: 이미지 주도 = p_image 0.8 이상이고 p_text 0.5 미만, 글자 주도 = 그 반대.", "",
         f"## 오탐 전부 ({len(fps)}쪽)", ""]
    L += table(fps, True) if fps else ["오탐이 없어요."]
    L += ["", f"## 미탐 상위 10 (전체 {len(fns_all)}쪽 중 확률이 낮은 순)", ""]
    L += table(fns, False) if fns else ["미탐이 없어요."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _write_figures(m: dict, P, y, out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_manager.fontManager.addfont(FONT)
    plt.rcParams["font.family"] = "Apple SD Gothic Neo"
    plt.rcParams["axes.unicode_minus"] = False
    M = m["models"]
    metrics = [("f1", "F1"), ("fpr_hard_negative", "하드네거티브\n오탐률"), ("recall_deposit", "충전\n재현율")]
    targets = {"f1": 0.90, "fpr_hard_negative": 0.02, "recall_deposit": 0.90}
    colors = {"text": "#7f9fd0", "image": "#e0a458", "fusion": "#3a7d5c"}
    cmat = confusion(y, P["fusion"])

    MB = m["scenarios"]["mirror_cluster"]["models"]

    def bars(ax, fs):
        from matplotlib.patches import Patch
        w = 0.135
        for j, k in enumerate(("text", "image", "fusion")):
            for s_i, (MM, hatch, alpha) in enumerate(((M, None, 1.0), (MB, "///", 0.55))):
                vals = [MM[k][mk][0] for mk, _ in metrics]
                err = [[MM[k][mk][0] - MM[k][mk][1] for mk, _ in metrics], [MM[k][mk][2] - MM[k][mk][0] for mk, _ in metrics]]
                pos_x = np.arange(3) + (j - 1) * 2 * w + (s_i - 0.5) * w
                ax.bar(pos_x, vals, w, yerr=err, capsize=2, color=colors[k], alpha=alpha, hatch=hatch,
                       edgecolor="white" if hatch is None else colors[k], linewidth=0, error_kw={"elinewidth": 1.2})
        for i, (mk, _) in enumerate(metrics):
            ax.hlines(targets[mk], i - 0.42, i + 0.42, colors="black", linestyles="--", linewidth=1.6)
        ax.set_xticks(range(3), [lab for _, lab in metrics], fontsize=fs)
        ax.set_ylim(0, 1.05)
        ax.tick_params(axis="y", labelsize=fs)
        ax.set_ylabel("비율 (막대 끝 선은 95% 구간)", fontsize=fs - 2)
        handles = [Patch(color=colors[k], label=MODEL_KO[k]) for k in ("text", "image", "fusion")]
        handles += [Patch(facecolor="#bbbbbb", label="A 새 주소"),
                    Patch(facecolor="#dddddd", edgecolor="#888888", hatch="///", label="B 처음 보는 사이트"),
                    plt.Line2D([0], [0], color="black", linestyle="--", label="목표")]
        ax.legend(handles=handles, fontsize=fs - 3, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.3),
                  frameon=False, columnspacing=0.8, handlelength=1.4)

    def cm(ax, fs):
        arr = np.array([[cmat["tn"], cmat["fp"]], [cmat["fn"], cmat["tp"]]])
        ax.imshow(arr, cmap="Greens")
        for (r, c), v in np.ndenumerate(arr):
            ax.text(c, r, str(v), ha="center", va="center", fontsize=fs + 4,
                    color="white" if v > arr.max() / 2 else "black")
        ax.set_xticks([0, 1], ["정상", "도박"], fontsize=fs)
        ax.set_yticks([0, 1], ["정상", "도박"], fontsize=fs)
        ax.set_xlabel("예측", fontsize=fs)
        ax.set_ylabel("실제", fontsize=fs)

    # 개별 그림
    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)
    bars(ax, 13)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_model_compare.png")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(4.5, 4.2), dpi=150)
    cm(ax, 13)
    ax.set_title("융합 모델 혼동행렬 (시나리오 A·새 주소)", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_confusion_fusion.png")
    plt.close(fig)
    # 합본: 2000px 폭, 16cm 인쇄 시 약 0.63배 → 글자 18pt 안팎
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 5.2), dpi=200, gridspec_kw={"width_ratios": [1.7, 1]})
    bars(a1, 17)
    cm(a2, 17)
    a2.set_title("융합 혼동행렬\n(시나리오 A·새 주소)", fontsize=16, pad=14)
    fig.tight_layout()
    fig.savefig(out_dir / "fig4_models.png")
    plt.close(fig)


def _print_summary(m: dict) -> None:
    print("\n모델별 결과 (값 [95% 구간])")
    for k in ("text", "image", "fusion"):
        e = m["models"][k]
        parts = [f"{key}={e[key][0]:.3f}[{e[key][1]:.3f},{e[key][2]:.3f}]"
                 for key in ("f1", "precision", "recall", "fpr_hard_negative", "fpr_normal", "recall_deposit")]
        print(f"  {k}: " + " ".join(parts))
        print(f"     recall_at_fpr2={e['recall_at_fpr2']:.3f} (thr {e['thr_at_fpr2']:.3f})")
    gl = m["fusion_gain_f1_ci"]
    print(f"융합 이득 F1: {m['fusion_gain_f1']:+.3f} [{gl[0]:+.3f},{gl[1]:+.3f}] (유효 {gl[2]})")
    for key, sc in m["scenarios"].items():
        f = sc["models"]["fusion"]
        sn = sc["sensitivity_excluding_suspect_labels"]
        print(f"[{key}] 그룹 {sc['n_groups']}개 융합: F1 {f['f1'][0]:.3f}[{f['f1'][1]:.3f},{f['f1'][2]:.3f}] "
              f"FPR_hn {f['fpr_hard_negative'][0]:.3f} 충전재현 {f['recall_deposit'][0]:.3f} "
              f"gain {sc['fusion_gain_f1']:+.3f} recall@fpr2 {f['recall_at_fpr2']:.3f} | "
              f"text F1 {sc['models']['text']['f1'][0]:.3f} image F1 {sc['models']['image']['f1'][0]:.3f} | "
              f"민감도(4곳 제외) fusion F1 {sn['models']['fusion']['f1'][0]:.3f}")
    print(f"embedded_banner 판정 비율: {m['embedded_banner_flag_rate']}")
    print(f"처리 시간 중앙값(ms): {m['timing_ms_median']}")
