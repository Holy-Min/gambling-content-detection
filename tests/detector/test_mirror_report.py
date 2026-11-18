import numpy as np

from detector.report import score_scenario
from detector.split import mirror_groups


def test_mirror_groups_links_by_image_and_text():
    doms = np.array(["a", "a", "b", "c", "d", "e", "f"])
    X = np.eye(7, 8, dtype=np.float32)
    X[2] = X[0]  # b 는 a 와 같은 이미지
    texts = ["x"] * 7
    texts[3] = "  Same   TEXT that is long enough to count  "
    texts[4] = "same text that is long enough to count"  # c-d 텍스트 동일
    texts[5] = "short"
    texts[6] = "short"  # 20자 미만은 연결하지 않음
    g = mirror_groups(doms, X, texts, cos=0.98)
    assert g[0] == g[1] == g[2]
    assert g[3] == g[4]
    assert g[0] != g[3]
    assert g[5] != g[6]


def test_score_scenario_keep_mask_drops_screens():
    # 도메인 6개, 화면 1쪽씩. 양성 3개 중 1개는 미탐(p=0.1), 이 화면을 빼면 재현율 1.0
    domain = np.array(list("abcdef"))
    y = np.array([1, 1, 1, 0, 0, 0])
    label = np.array(["gambling"] * 3 + ["hard_negative"] * 3, dtype=object)
    kind = np.array(["deposit", "", "", "", "", ""], dtype=object)
    p = np.array([0.9, 0.9, 0.1, 0.1, 0.1, 0.1])
    P = {"text": p, "image": p, "fusion": p}
    full = score_scenario(y, label, kind, P, domain, n_boot=50)
    keep = np.array([True, True, False, True, True, True])
    part = score_scenario(y, label, kind, P, domain, keep=keep, n_boot=50)
    assert abs(full["models"]["fusion"]["recall"][0] - 2 / 3) < 1e-9
    assert part["models"]["fusion"]["recall"][0] == 1.0
