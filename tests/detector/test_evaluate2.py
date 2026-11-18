import json
from pathlib import Path

import numpy as np
import pytest

from detector.data import Sample, load_label_overrides, load_samples
from detector.split import first_seen, first_seen_from_index, time_split
from detector import evaluate2 as e2


def _row(i, label, domain, day="2026-11-10", page_kind="home"):
    return {"id": f"id{i}", "label": label, "status": "ok", "domain": domain,
            "domain_hash": f"h_{domain}", "page_kind": page_kind,
            "full_path": f"img/{i}.png", "captured_at": f"{day}T10:00:00"}


def _write_index(tmp_path, rows):
    p = tmp_path / "index.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _write_labels(tmp_path, lines):
    p = tmp_path / "labels.csv"
    p.write_text("unit,key,label,reason,checked_by,checked_at\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_overrides_priority_and_exclude(tmp_path):
    rows = [_row(0, "gambling", "a.com"), _row(1, "gambling", "a.com"), _row(2, "normal", "b.com"),
            _row(3, "hard_negative", "c.com"), _row(4, "embedded_banner", "d.com")]
    idx = _write_index(tmp_path, rows)
    lab = _write_labels(tmp_path, [
        "site,h_a.com,hard_negative,r,x,d", "screen,id1,normal,r,x,d",
        "site,h_b.com,exclude,r,x,d", "site,h_d.com,gambling,r,x,d"])
    got = {s.id: s.label for s in load_samples(idx, tmp_path, labels_path=lab)}
    assert got == {"id0": "hard_negative", "id1": "normal", "id3": "hard_negative", "id4": "gambling"}


def test_overrides_none_same_as_before(tmp_path):
    idx = _write_index(tmp_path, [_row(0, "gambling", "a.com"), _row(1, "embedded_banner", "d.com")])
    a = load_samples(idx, tmp_path)
    b = load_samples(idx, tmp_path, labels_path=None)
    assert a == b and [s.id for s in a] == ["id0"]
    assert a[0].captured_at.startswith("2026-11-10")


@pytest.mark.parametrize("line", ["page,k,gambling,r,x,d", "site,k,,r,x,d", "site,k,weird,r,x,d"])
def test_overrides_invalid(tmp_path, line):
    with pytest.raises(ValueError):
        load_label_overrides(_write_labels(tmp_path, [line]))


def _s(i, h, day, y=1, label=None, kind=None):
    label = label or ("gambling" if y else "normal")
    return Sample(f"s{i}", label, y, h, h, kind, Path("x.png"), f"{day}T01:00:00")


def test_time_split():
    S = [_s(0, "A", "2026-11-13"), _s(1, "A", "2026-11-15"), _s(2, "B", "2026-11-12"),
         _s(3, "B", "2026-11-14"), _s(4, "C", "2026-11-12"), _s(5, "C", "2026-11-13")]
    assert first_seen(S) == {"A": "2026-11-13", "B": "2026-11-12", "C": "2026-11-12"}
    assert time_split(S, "2026-11-13").tolist() == [True, True, False, False, False, False]


def test_time_split_uses_global_first_seen(tmp_path):
    idx = _write_index(tmp_path, [_row(0, "gambling", "a.com", "2026-11-10"),
                                  _row(1, "gambling", "a.com", "2026-11-15"),
                                  _row(2, "normal", "b.com", "2026-11-15")])
    fs = first_seen_from_index(idx)
    # 이른 화면이 exclude 돼 남은 화면이 늦어도 사이트는 학습 쪽
    S = [_s(1, "h_a.com", "2026-11-15"), _s(2, "h_b.com", "2026-11-15")]
    assert time_split(S, "2026-11-13", fs).tolist() == [False, True]


# ---- 평가 핵심 (합성 데이터) ----
def _synth(n_train_sites=14, n_test_sites=6, seed=0, test_normal=True, mirror=True):
    rng = np.random.default_rng(seed)
    S, texts, X = [], [], []
    def add(h, y, label, day, kind, base, text):
        v = base + rng.normal(0, 0.5, 8)
        v /= np.linalg.norm(v)
        S.append(Sample(f"s{len(S)}", label, y, h, h, kind, Path(f"/img/{len(S)}.png"), f"{day}T00:00:00"))
        X.append(v); texts.append(text)
    pos, neg = np.eye(8)[0] * 3 + np.eye(8)[1], np.eye(8)[2] * 3 + np.eye(8)[3]
    for i in range(n_train_sites):
        y = i % 2
        lab = "gambling" if y else ("hard_negative" if i % 4 == 0 else "normal")
        for j in range(3):
            add(f"T{i}", y, lab, "2026-11-10", "deposit" if (y and j == 0) else "home",
                pos if y else neg, f"{'bet casino win' if y else 'news weather sport'} t{i} {j} abc")
    for i in range(n_test_sites):
        y = i % 2
        lab = "gambling" if y else ("hard_negative" if (i % 4 == 0 or not test_normal) else "normal")
        for j in range(2):
            add(f"E{i}", y, lab, "2026-11-14", "deposit" if (y and j == 0) else "home",
                pos if y else neg, f"{'bet casino win' if y else 'news weather sport'} e{i} {j} xyz")
    for i in range(2):  # 배너
        for j in range(2):
            add(f"B{i}", None, "embedded_banner", "2026-11-14", "home", pos, "bet casino win banner")
    if mirror:  # 시험 사이트 E1 은 학습 사이트 T1 과 같은 글(미러)
        t1 = [i for i, s in enumerate(S) if s.domain_hash == "T1"][0]
        for i, s in enumerate(S):
            if s.domain_hash == "E1":
                texts[i] = "this is an identical mirrored page text for twin"
                texts[t1] = texts[i]
    return S, texts, np.stack(X).astype(np.float32)


def _run(S, texts, X, **kw):
    return e2.run_core(S, texts, X, time_split(S, "2026-11-13"), n_boot=30, k=3, **kw)


def test_core_runs_and_banner_not_in_training():
    S, texts, X = _synth()
    out = _run(S, texts, X)
    m = out["metrics"]
    assert m["n"]["banner"]["screens"] == 4 and m["n"]["train"]["screens"] == 42
    assert m["n"]["test"]["screens"] == 12
    assert set(out["rows"]["split"]) == {"train", "test", "banner"}
    assert m["banner"]["models"]["fusion"]["0.5"]["screen_rate"][0] is not None
    assert not any(r_split == "banner" and lab in ("gambling", "normal", "hard_negative")
                   for r_split, lab in zip(out["rows"]["split"], out["rows"]["label"]))


def test_threshold_fixed_by_train_oof_only():
    S, texts, X = _synth()
    a = _run(S, texts, X)["metrics"]["thr_fpr2"]
    S2, _, _ = _synth()
    # 시험 사이트의 이미지·글자를 바꿔도 임계값은 같아야 한다 (시험 화면은 학습에 안 들어감)
    X2 = X.copy(); texts2 = list(texts)
    for i, s in enumerate(S):
        if s.domain_hash.startswith("E"):
            X2[i] = X[(i + 7) % len(S)]; texts2[i] = "zzz qqq changed " + str(i)
    b = _run(S, texts2, X2)["metrics"]["thr_fpr2"]
    assert a == b


def test_mirror_flag_only_for_twin():
    S, texts, X = _synth()
    out = _run(S, texts, X)
    rows = out["rows"]
    flagged = {h for h, sp, m in zip(rows["domain_hash"], rows["split"], rows["mirror_of_train"])
               if sp == "test" and m == 1}
    assert flagged == {"E1"}
    sub = out["metrics"]["test_mirror"]
    assert sub["n"]["sites"] == 1 and out["metrics"]["test_unseen"]["n"]["sites"] == 5


def test_no_normal_in_test_gives_null():
    S, texts, X = _synth(test_normal=False)
    m = _run(S, texts, X)["metrics"]
    v = m["test"]["models"]["fusion"]["0.5"]["fpr_normal"]
    assert v == [None, None, None]
    json.dumps(m)  # NaN 없이 직렬화 가능


def test_disagreements_only_train_and_thresholds():
    S, texts, X = _synth()
    out = _run(S, texts, X)
    rows = out["rows"]
    for i in out["disagree_idx"]:
        assert rows["split"][i] == "train"
        p, lab = rows["p_fusion"][i], rows["label"][i]
        assert (lab == "gambling" and p < 0.2) or (lab != "gambling" and p > 0.8)




# ---- 2차 보강: 시험 상한·합법 사행·상표 낱말 규칙 ----
import dataclasses

from detector import rules


def test_time_split_until():
    S = [_s(0, "A", "2026-11-13"), _s(1, "B", "2026-11-18"), _s(2, "C", "2026-11-19"),
         _s(3, "D", "2026-11-12")]
    assert time_split(S, "2026-11-13", until="2026-11-18").tolist() == [True, True, False, False]
    assert time_split(S, "2026-11-13", until=None).tolist() == [True, True, True, False]
    assert time_split(S, "2026-11-13").tolist() == time_split(S, "2026-11-13", until=None).tolist()


def test_time_split_until_later_site_is_train_even_with_early_screen_excluded():
    S = [_s(0, "A", "2026-11-19"), _s(1, "A", "2026-11-20")]
    assert time_split(S, "2026-11-13", until="2026-11-18").tolist() == [False, False]


def test_screen_exclude_beats_site_gambling(tmp_path):
    idx = _write_index(tmp_path, [_row(0, "normal", "a.com"), _row(1, "normal", "a.com")])
    lab = _write_labels(tmp_path, ["site,h_a.com,gambling,r,x,d", "screen,id0,exclude,r,x,d"])
    got = {s.id: s.label for s in load_samples(idx, tmp_path, labels_path=lab)}
    assert got == {"id1": "gambling"}


def test_legal_gambling_label_loading(tmp_path):
    idx = _write_index(tmp_path, [_row(0, "normal", "a.com"), _row(1, "normal", "b.com")])
    lab = _write_labels(tmp_path, ["site,h_b.com,legal_gambling,r,x,d"])
    on = {s.id: (s.label, s.y) for s in load_samples(idx, tmp_path, include_embedded=True, labels_path=lab)}
    assert on == {"id0": ("normal", 0), "id1": ("legal_gambling", None)}
    off = [s.id for s in load_samples(idx, tmp_path, include_embedded=False, labels_path=lab)]
    assert off == ["id0"]


def test_rules_normalize_and_hits():
    assert rules.normalize("BET Man　A\n") == "betmana"
    assert rules.legal_brand_hits("동행 복권 안내") == ["동행복권"]
    assert rules.legal_brand_hits("BETMAN official") == ["betman"]
    assert rules.legal_brand_hits("news weather") == []
    assert not rules.legal_rule("news weather")
    assert rules.legal_rule("동행 복권")
    # 입력 목록 순서 유지: 베트맨 ... betman ... 스포츠토토 ... 한국마사회
    assert rules.legal_brand_hits("스포츠토토 betman 한국마사회") == ["betman", "스포츠토토", "한국마사회"]
    assert rules.legal_brand_hits("seven luck") == ["sevenluck"]  # 정규화 후 같은 낱말은 한 번만
    assert rules.legal_brand_hits("betman", terms=("BET man", "x")) == ["BET man"]
    assert rules.legal_brand_hits("anything", terms=("",)) == []


def test_rules_short_terms_no_false_hit():
    assert rules.legal_rule("Select your country / region") is False
    assert rules.legal_rule("서울시 대기환경정보 홈페이지") is False


def test_rules_product_terms_catch_misread_logo():
    t = "hetman\n발매중게임\n프로토 승부식 130회차\n구매투표지"
    assert rules.legal_rule(t) is True
    assert rules.legal_brand_hits(t) == ["프로토승부식", "구매투표지"]


def _synth_legal(**kw):
    S, texts, X = _synth(**kw)
    rng = np.random.default_rng(5)
    for i in range(2):
        for j in range(2):
            v = np.eye(8)[4] * 3 + rng.normal(0, 0.3, 8)
            S.append(Sample(f"s{len(S)}", "legal_gambling", None, f"L{i}", f"L{i}", "home",
                            Path(f"/img/{len(S)}.png"), "2026-11-14T00:00:00"))
            texts.append("베트맨 sports " if (i == 0 or j == 0) else "nothing here")
            X = np.vstack([X, (v / np.linalg.norm(v)).astype(np.float32)])
    return S, texts, X


def test_legal_screens_not_in_train_or_test_only_legal_bucket():
    S, texts, X = _synth_legal()
    base = _run(*_synth())
    out = _run(S, texts, X)
    m = out["metrics"]
    assert m["n"]["train"] == base["metrics"]["n"]["train"]
    assert m["n"]["test"] == base["metrics"]["n"]["test"]
    assert m["thr_fpr2"] == base["metrics"]["thr_fpr2"]
    assert m["n"]["banner"]["screens"] == 4
    assert m["legal"]["n"] == {"sites": 2, "screens": 4}
    for i, s in enumerate(S):
        assert (out["rows"]["split"][i] == "legal") == (s.label == "legal_gambling")
    # 규칙: L0 두 화면, L1 한 화면 → 3/4 화면, 2/2 사이트
    assert m["legal"]["rule"]["screen_rate"][0] == pytest.approx(0.75)
    assert m["legal"]["rule"]["site_rate"][0] == 1.0
    assert set(m["legal"]["models"]) == {"text", "image", "fusion"}
    assert out["rows"]["rule_hit"][[i for i, s in enumerate(S) if s.label == "legal_gambling"][0]] == 1


def test_rule_false_hits_and_text_plus_rule():
    S, texts, X = _synth()
    for i, s in enumerate(S):
        if s.domain_hash == "E0":  # 시험 hard_negative 사이트 (2화면)
            texts[i] += " 베트맨"
        if s.domain_hash == "T0":  # 학습 hard_negative 사이트 (3화면), 낱말 2개
            texts[i] += " kcycle betman"
    m = _run(S, texts, X)["metrics"]
    f = m["rule_false_hits"]
    assert f["test_hard_negative"]["hits"] == 2 and f["test_hard_negative"]["screens"] == 4
    assert f["test_hard_negative"]["rate"] == pytest.approx(0.5)
    assert f["train_hard_negative"]["hits"] == 3
    assert f["test_gambling"]["hits"] == 0 and f["banner"]["hits"] == 0
    terms = dict((t["term"], t["screens"]) for t in f["by_term_negative"])
    assert terms == {"베트맨": 2, "kcycle": 3, "betman": 3}
    assert [t["screens"] for t in f["by_term_negative"]] == sorted(terms.values(), reverse=True)
    tr = m["text_plus_rule"]["test"]["0.5"]
    assert tr["text_or_rule"]["fpr_hard_negative"][0] >= 0.5
    assert tr["text_or_rule"]["fpr_hard_negative"][0] >= tr["text_only"]["fpr_hard_negative"][0]
    json.dumps(m, allow_nan=False)


def test_text_plus_rule_report_recall_up():
    y = np.array([1, 1, 1, 0, 0, 0])
    label = np.array(["gambling"] * 3 + ["hard_negative", "hard_negative", "normal"], dtype=object)
    kind = np.array([""] * 6, dtype=object)
    hashes = np.array(list("abcdef"), dtype=object)
    p = np.array([0.9, 0.1, 0.1, 0.1, 0.1, 0.1])
    rule = np.array([False, True, False, True, False, False])
    r = e2.text_plus_rule_report(y, label, kind, hashes, p, rule, {"text": 0.7}, n_boot=20)
    t, c = r["0.5"]["text_only"], r["0.5"]["text_or_rule"]
    assert t["recall"][0] == pytest.approx(1 / 3) and c["recall"][0] == pytest.approx(2 / 3)
    assert t["fpr_hard_negative"][0] == 0.0 and c["fpr_hard_negative"][0] == pytest.approx(0.5)
    assert c["precision"][0] == pytest.approx(2 / 3)
    assert r["fpr2"]["text_or_rule"]["recall"][0] == pytest.approx(2 / 3)


def test_fusion_gain_nan_order_independent():
    # 시험 부분집합에 양성이 없으면 f1 이 NaN. 어느 쪽이 NaN 이든 gain 은 NaN
    y = np.array([0, 0, 1, 1]); h = np.array(list("abcd"), dtype=object)
    lab = np.array(["normal", "normal", "gambling", "gambling"], dtype=object)
    kind = np.array([""] * 4, dtype=object)
    P = {"text": np.array([0.1, 0.1, 0.9, 0.9]), "image": np.array([0.9, 0.9, 0.1, 0.1]),
         "fusion": np.array([0.5, 0.5, 0.5, 0.5])}
    thr = {m: 0.5 for m in e2.MODELS}
    r = e2.subset_report(y[:2], lab[:2], kind[:2], h[:2], {m: P[m][:2] for m in e2.MODELS}, thr, 10)
    assert r["fusion_gain_f1"]["0.5"] == [None, None, None]
    # 텍스트만 NaN 이 되는 경우: f1(text) NaN(예측·양성 없음), image 유효 → NaN
    y2 = np.array([0, 0]); P2 = {"text": np.array([0.1, 0.1]), "image": np.array([0.9, 0.1]),
                                 "fusion": np.array([0.9, 0.1])}
    r2 = e2.subset_report(y2, lab[:2], kind[:2], h[:2], P2, thr, 10)
    assert r2["fusion_gain_f1"]["0.5"][0] is None
    # 이미지만 NaN 인 경우도 같다 (예전엔 max 인자 순서에 따라 값이 나왔다)
    P3 = {"text": P2["image"], "image": P2["text"], "fusion": P2["fusion"]}
    r3 = e2.subset_report(y2, lab[:2], kind[:2], h[:2], P3, thr, 10)
    assert r3["fusion_gain_f1"]["0.5"][0] is None


def test_write_reports_no_names(tmp_path):
    S, texts, X = _synth_legal()
    S = [dataclasses.replace(s, domain=f"casino-leak-{s.domain_hash}.example",
                             domain_hash=f"hashleak{s.domain_hash}.fake") for s in S]
    texts = [t + " OCRSECRETMARK" for t in texts]
    m = _run(S, texts, X)["metrics"]
    m |= {"cutoff": "2026-11-13", "index": "i.jsonl", "labels": "l.csv", "n_disagreements": 0}
    e2.write_reports(m, tmp_path, tmp_path)
    js = (tmp_path / "metrics_v2.json").read_text(encoding="utf-8")
    md = (tmp_path / "metrics_v2.md").read_text(encoding="utf-8")
    assert json.loads(js)["test_until"] is None
    assert "시험 세트" in md and "합법 사행" in md and "규칙" in md
    for txt in (js, md):
        for leak in ("hashleak", ".fake", "casino-leak", "OCRSECRETMARK", "/img/", ".png"):
            assert leak not in txt


# ---- 건지기(글자 우선 + 이미지) · 전체 판정 ----
def _synth_noisy(seed=3, n_train=40, n_test=16, noise=1.0):
    """글자·이미지 둘 다 일부 틀리는 합성 데이터(양성/음성 반반). 마지막에 합법 사행·배너 사이트."""
    rng = np.random.default_rng(seed)
    S, texts, X = [], [], []

    def add(h, y, label, day, kind, text):
        base = np.eye(8)[0] * 2 if y == 1 else (np.eye(8)[1] * 2 if y == 0 else np.eye(8)[2] * 2)
        v = base + rng.normal(0, noise, 8)
        S.append(Sample(f"s{len(S)}", label, y, h, h, kind, Path(f"/img/{len(S)}.png"), f"{day}T00:00:00"))
        X.append((v / np.linalg.norm(v)).astype(np.float32)); texts.append(text)

    for pre, n, day in (("T", n_train, "2026-11-10"), ("E", n_test, "2026-11-14")):
        for i in range(n):
            y = i % 2
            lab = "gambling" if y else ("hard_negative" if i % 4 == 0 else "normal")
            for j in range(3):
                text_says_bet = (rng.random() < 0.6) if y else (rng.random() < 0.12)
                words = "bet casino win slot" if text_says_bet else "news weather sport shop"
                add(f"{pre}{i}", y, lab, day, "deposit" if (y and j == 0) else "home", f"{words} {pre}{i} {j} {rng.integers(99)}")
    for i in range(2):
        for j in range(2):
            add(f"B{i}", None, "embedded_banner", "2026-11-14", "home", "bet casino win banner" if j == 0 else "x")
    for i in range(2):
        for j in range(2):
            add(f"L{i}", None, "legal_gambling", "2026-11-14", "home", "베트맨 sports" if (i == 0 or j == 0) else "nothing here")
    return S, texts, np.stack(X)


def _run_noisy(**kw):
    S, texts, X = _synth_noisy()
    return S, texts, X, _run(S, texts, X, **kw)


def test_regression_existing_metrics_unchanged():
    # 건지기·전체 판정을 넣기 전 코드로 같은 합성 데이터를 돌려 얻은 값(소수 6자리)
    m = _run_noisy()[3]["metrics"]
    assert m["thr_fpr2"] == pytest.approx({"text": 0.840949518144198, "image": 0.8127551078796388,
                                           "fusion": 0.5484103313688594})
    want = {("train_oof", "text", "0.5"): (0.742857, 0.866667, 0.65, 0.1),
            ("train_oof", "text", "fpr2"): (0.09375, 0.75, 0.05, 0.0),
            ("train_oof", "fusion", "0.5"): (0.92562, 0.918033, 0.933333, 0.1),
            ("train_oof", "fusion", "fpr2"): (0.93913, 0.981818, 0.9, 1 / 30),
            ("test", "text", "0.5"): (0.731707, 0.882353, 0.625, 1 / 12),
            ("test", "image", "0.5"): (0.978723, 1.0, 0.958333, 0.0),
            ("test", "fusion", "fpr2"): (0.956522, 1.0, 0.916667, 0.0)}
    for (sub, mo, tk), (f, p, r, h) in want.items():
        c = m[sub]["models"][mo][tk]
        got = (c["f1"][0], c["precision"][0], c["recall"][0], c["fpr_hard_negative"][0])
        assert got == pytest.approx((f, p, r, h), abs=1e-6), (sub, mo, tk)
    assert m["banner"]["models"]["fusion"]["fpr2"]["screen_rate"][0] == 0.25
    assert m["legal"]["rule"]["screen_rate"][0] == 0.75


def _hand_counts(rows, y_of, t, split):
    """rows(공개 CSV 와 같은 값)에서 손으로 센 (건진 수, 글자가 놓친 양성 수, 추가 오탐 수, 글자가 통과시킨 음성 수)."""
    r = e_n = a = b = 0
    for i, sp in enumerate(rows["split"]):
        if sp != split:
            continue
        passed = rows["p_text"][i] < 0.5
        hit = rows["p_image"][i] >= t
        if y_of(rows["label"][i]) == 1 and passed:
            a += 1; r += hit
        if y_of(rows["label"][i]) == 0 and passed:
            b += 1; e_n += hit
    return r, a, e_n, b


def test_rescue_counts_match_hand_count_and_recall_goes_up():
    S, texts, X, out = _run_noisy()
    m, rows = out["metrics"], out["rows"]
    rs = m["rescue"]
    t = rs["t_img"]
    assert t is not None and rs["fp_budget"] == 0.01
    y_of = lambda lab: 1 if lab == "gambling" else 0
    for key, split in (("train_oof", "train"), ("test", "test")):
        r, a, e, b = _hand_counts(rows, y_of, t, split)
        c = rs["counts"][key]
        assert (c["rescued"]["n"], c["rescued"]["d"], c["extra_fp"]["n"], c["extra_fp"]["d"]) == (r, a, e, b)
    assert rs["counts"]["train_oof"]["rescued"]["d"] > 0 and rs["counts"]["test"]["rescued"]["n"] > 0
    # 학습 OOF 에서 글자가 통과시킨 음성 중 t 이상 비율은 예산 이하
    c = rs["counts"]["train_oof"]["extra_fp"]
    assert c["n"] / c["d"] <= 0.01
    # 이미지가 건진 양성 → 재현율은 글자 단독보다 높고, pred_rescue 는 글자 OR 이미지
    te = m["test"]["models"]["text"]["0.5"]["recall"][0]
    assert rs["test"]["recall"][0] > te
    for i, sp in enumerate(rows["split"]):
        assert rows["pred_rescue"][i] == int(rows["p_text"][i] >= 0.5 or rows["p_image"][i] >= t)
    assert set(rs) >= {"test", "test_mirror", "test_unseen", "train_oof"}
    for k in ("f1", "precision", "recall", "fpr_hard_negative", "fpr_normal", "recall_deposit"):
        assert len(rs["test"][k]) == 3


def test_rescue_image_false_positive_counted():
    # 글자가 통과시킨 하드 네거티브를 이미지가 높게 보면 오탐으로 센다
    y = np.array([1, 0, 0, 0]); lab = np.array(["gambling", "hard_negative", "hard_negative", "normal"], dtype=object)
    kind = np.array([""] * 4, dtype=object); h = np.array(list("abcd"), dtype=object)
    pt = np.array([0.1, 0.1, 0.1, 0.1]); pi = np.array([0.9, 0.9, 0.1, 0.9])
    r = e2.rescue_report(y, lab, kind, h, pt, pi, 0.5, 10)
    assert r["recall"][0] == 1.0 and r["fpr_hard_negative"][0] == 0.5 and r["fpr_normal"][0] == 1.0
    assert r["precision"][0] == pytest.approx(1 / 3)  # 맞힌 1, 오탐 2


def test_t_img_from_train_oof_only_and_not_from_legal_or_banner():
    S, texts, X, base = _run_noisy()
    X2, texts2 = X.copy(), list(texts)
    rng = np.random.default_rng(9)
    for i, s in enumerate(S):
        if s.domain_hash.startswith(("E", "B", "L")):  # 시험·배너·합법 사행 쪽을 통째로 바꿈
            X2[i] = rng.normal(size=8).astype(np.float32); texts2[i] = "zzz changed " + str(i)
    out = _run(S, texts2, X2)
    assert out["metrics"]["rescue"]["t_img"] == base["metrics"]["rescue"]["t_img"]
    assert out["metrics"]["rescue"]["counts"]["train_oof"] == base["metrics"]["rescue"]["counts"]["train_oof"]
    assert out["metrics"]["rescue"]["counts"]["test"] != base["metrics"]["rescue"]["counts"]["test"]


def test_fp_budget_changes_t_img():
    S, texts, X, a = _run_noisy()
    b = _run(S, texts, X, fp_budget=0.2)["metrics"]["rescue"]
    assert b["fp_budget"] == 0.2 and b["t_img"] <= a["metrics"]["rescue"]["t_img"]


def test_system_includes_rule_and_rates_by_hand():
    S, texts, X = _synth_noisy()
    for i, s in enumerate(S):
        if s.domain_hash == "E0":  # 시험 하드 네거티브 사이트(3화면)에 상표 낱말
            texts[i] += " 베트맨"
    out = _run(S, texts, X)
    m, rows = out["metrics"], out["rows"]
    t = m["rescue"]["t_img"]
    for i in range(len(S)):
        assert rows["pred_system"][i] == int(rows["pred_rescue"][i] or rows["rule_hit"][i])
        if S[i].domain_hash == "E0":
            assert rows["pred_system"][i] == 1
    assert m["system"]["test"]["fpr_hard_negative"][0] >= m["rescue"]["test"]["fpr_hard_negative"][0]
    assert m["system"]["test"]["recall"][0] >= m["rescue"]["test"]["recall"][0]
    # 합법 사행: L0 두 화면과 L1 한 화면에 낱말 → 최소 3/4 화면, 2/2 사이트
    lg = [i for i, s in enumerate(S) if s.label == "legal_gambling"]
    want = [rows["pred_system"][i] for i in lg]
    assert m["system"]["legal"]["screen_rate"][0] == pytest.approx(sum(want) / 4) and sum(want) >= 3
    assert m["system"]["legal"]["site_rate"][0] == 1.0
    ba = [i for i, s in enumerate(S) if s.label == "embedded_banner"]
    pb = [rows["pred_system"][i] for i in ba]
    assert m["system"]["banner"]["screen_rate"][0] == pytest.approx(sum(pb) / 4)
    sites = {}
    for i in ba:
        sites[S[i].domain_hash] = sites.get(S[i].domain_hash, 0) or rows["pred_system"][i]
    assert m["system"]["banner"]["site_rate"][0] == pytest.approx(sum(sites.values()) / 2)
    assert set(m["system"]) == {"test", "test_unseen", "legal", "banner"}
    json.dumps(m, allow_nan=False)


def test_other_encoder_keeps_folds_and_text_predictions():
    S, texts, X = _synth_noisy()
    mask = time_split(S, "2026-11-13")
    base = e2.run_core(S, texts, X, mask, n_boot=10, k=3)
    rng = np.random.default_rng(1)
    X_other = rng.normal(size=(len(S), 5)).astype(np.float32)
    alt = e2.run_core(S, texts, X_other, mask, n_boot=10, k=3, X_mirror=X)
    assert alt["rows"]["p_text"] == base["rows"]["p_text"]
    assert alt["rows"]["mirror_of_train"] == base["rows"]["mirror_of_train"]
    assert alt["metrics"]["thr_fpr2"]["text"] == base["metrics"]["thr_fpr2"]["text"]
    assert alt["rows"]["p_image"] != base["rows"]["p_image"]


def _meta(m):
    return m | {"cutoff": "2026-11-13", "index": "i.jsonl", "labels": "l.csv", "n_disagreements": 0}


def test_output_names_and_default_not_overwritten(tmp_path):
    assert e2.output_names("clip-b32") == {"json": "metrics_v2.json", "md": "metrics_v2.md",
                                           "pred": "predictions_v2.csv", "disagree": "disagreements_v2.csv"}
    n = e2.output_names("siglip2-b16")
    assert n == {"json": "metrics_v2__siglip2-b16.json", "md": "metrics_v2__siglip2-b16.md",
                 "pred": "predictions_v2__siglip2-b16.csv", "disagree": None}
    S, texts, X, out = _run_noisy()
    m = _meta(out["metrics"])
    (tmp_path / "metrics_v2.md").write_text("DEFAULT", encoding="utf-8")
    e2.write_reports(m | {"image_encoder": "siglip2-b16"}, tmp_path, tmp_path)
    assert (tmp_path / "metrics_v2.md").read_text(encoding="utf-8") == "DEFAULT"
    assert not (tmp_path / "metrics_v2.json").exists()
    js = json.loads((tmp_path / "metrics_v2__siglip2-b16.json").read_text(encoding="utf-8"))
    assert js["image_encoder"] == "siglip2-b16"
    assert "siglip2-b16" in (tmp_path / "metrics_v2__siglip2-b16.md").read_text(encoding="utf-8")
    # 예측 CSV: 기본 인코더만 어긋남 CSV 를 쓴다
    feats = tmp_path / "f"
    e2.write_predictions(out["rows"], out["disagree_idx"], feats, "siglip2-b16")
    assert sorted(p.name for p in feats.iterdir()) == ["predictions_v2__siglip2-b16.csv"]
    e2.write_predictions(out["rows"], out["disagree_idx"], feats, "clip-b32")
    assert {p.name for p in feats.iterdir()} == {"predictions_v2__siglip2-b16.csv", "predictions_v2.csv",
                                                "disagreements_v2.csv"}
    head = (feats / "predictions_v2.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "pred_rescue" in head and "pred_system" in head


def test_md_has_adopted_section_and_no_leaks(tmp_path):
    S, texts, X = _synth_noisy()
    S = [dataclasses.replace(s, domain=f"casino-leak-{s.domain_hash}.example",
                             domain_hash=f"hashleak{s.domain_hash}.fake") for s in S]
    texts = [t + " OCRSECRETMARK" for t in texts]
    m = _meta(_run(S, texts, X)["metrics"]) | {"image_encoder": "clip-b32"}
    e2.write_reports(m, tmp_path, tmp_path)
    md = (tmp_path / "metrics_v2.md").read_text(encoding="utf-8")
    js = (tmp_path / "metrics_v2.json").read_text(encoding="utf-8")
    assert md.index("채택한 판정 방식") < md.index("## 시험 세트 (전체)")
    for row in ("글자 단독", "평균 융합(이전 방식)", "글자 우선+이미지 건지기", "전체 판정(+상표 낱말)"):
        assert row in md
    assert "clip-b32" in md and "t_img" in md
    assert json.loads(js)["image_encoder"] == "clip-b32"
    for txt in (js, md):
        for leak in ("hashleak", ".fake", "casino-leak", "OCRSECRETMARK", "/img/", ".png"):
            assert leak not in txt
