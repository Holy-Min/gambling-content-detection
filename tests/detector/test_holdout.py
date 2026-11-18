import numpy as np

from detector.holdout import apply_rule, near_dup_mask, rule_metrics, select_holdout


def test_apply_rule_boundary_inclusive():
    pt = np.array([0.5, 0.49, 0.9, 0.5])
    pi = np.array([0.5, 0.9, 0.49, 0.8])
    assert apply_rule(pt, pi, "text").tolist() == [True, False, True, True]
    assert apply_rule(pt, pi, "and").tolist() == [True, False, False, True]
    assert apply_rule(pt, pi, "mean").tolist() == [True, True, True, True]
    assert apply_rule(np.array([0.4]), np.array([0.6]), "mean").tolist() == [True]
    assert apply_rule(np.array([0.4]), np.array([0.5]), "mean").tolist() == [False]


def test_apply_rule_unknown():
    import pytest

    with pytest.raises(ValueError):
        apply_rule(np.zeros(1), np.zeros(1), "or")


def _row(id, label="gambling", status="ok", at="2026-11-09T15:00:00+09:00"):
    return {"id": id, "label": label, "status": status, "captured_at": at, "full_path": "x.png"}


def test_select_holdout_filters():
    rows = [
        _row("a"),
        _row("b", at="2026-11-09T14:00:00+09:00"),  # cutoff 경계 포함
        _row("c", at="2026-11-09T13:59:59+09:00"),  # 이전
        _row("d", status="challenge"),
        _row("e", label="embedded_banner"),
        _row("f", label="hard_negative"),
        _row("g", label="normal"),
        _row("h"),  # 스냅숏에 있음
    ]
    out = select_holdout(rows, {"h"}, "2026-11-09T14:00")
    assert [r["id"] for r in out] == ["a", "b", "f", "g"]


def test_near_dup_mask():
    train = np.array([[1.0, 0.0], [0.0, 1.0]])
    hold = np.array([[1.0, 0.0], [0.7071, 0.7071], [0.999, 0.0447]])
    m = near_dup_mask(hold, train, cos=0.98)
    # 첫째·셋째는 학습 화면과 코사인 >= 0.98 → 근사 중복, 둘째는 0.707
    assert m.tolist() == [True, False, True]
    assert near_dup_mask(np.array([[0.6, 0.8]]), np.array([[1.0, 0.0]]), 0.98).tolist() == [False]
    # 경계: 0.98 와 같으면 근사 중복이 아님(<= 0.98 이 '근사 중복 없음')
    b = np.array([[0.98, np.sqrt(1 - 0.98**2)]])
    assert near_dup_mask(b, np.array([[1.0, 0.0]]), 0.98).tolist() == [False]


def test_rule_metrics():
    label = np.array(["gambling", "gambling", "gambling", "hard_negative", "hard_negative", "normal", "normal"])
    kind = np.array(["deposit", "deposit", "", "", "", "", ""], dtype=object)
    domain = np.array(["a", "a", "b", "c", "d", "e", "f"])
    pred = np.array([True, False, True, True, False, False, False])
    m = rule_metrics(label, kind, domain, pred)
    assert m["n"] == {"gambling": 3, "hard_negative": 2, "normal": 2}
    assert m["domains"] == {"gambling": 2, "hard_negative": 2, "normal": 2}
    assert abs(m["recall"] - 2 / 3) < 1e-9
    assert m["deposit_recall"] == 0.5
    assert m["hn_fpr"] == 0.5
    assert m["normal_fpr"] == 0.0
    assert abs(m["precision"] - 2 / 3) < 1e-9
    assert abs(m["f1"] - 2 * 2 / (2 * 2 + 1 + 1)) < 1e-9


def test_rule_metrics_empty_class_is_nan():
    m = rule_metrics(np.array(["gambling"]), np.array([""], dtype=object), np.array(["a"]), np.array([True]))
    assert np.isnan(m["hn_fpr"]) and np.isnan(m["deposit_recall"])
