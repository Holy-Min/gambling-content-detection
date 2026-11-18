"""텍스트(TF-IDF)·이미지(CLIP) 로지스틱 회귀와 out-of-fold 예측."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def text_model() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True, min_df=2)),
        ("lr", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ])


def image_model() -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("lr", LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0)),
    ])


def oof_predict(
    texts: list[str],
    X_img: np.ndarray,
    y: np.ndarray,
    folds: np.ndarray,
    text_models_out: dict[int, Pipeline] | None = None,
) -> dict[str, np.ndarray]:
    """fold 별로 나머지 fold 에서만 학습해 그 fold 를 예측. text_models_out 이 주어지면 fold 별 텍스트 모델을 담는다."""
    texts = np.asarray(texts, dtype=object)
    y = np.asarray(y)
    folds = np.asarray(folds)
    p_text = np.zeros(len(y))
    p_img = np.zeros(len(y))
    for f in np.unique(folds):
        te = folds == f
        tr = ~te
        tm = text_model().fit(list(texts[tr]), y[tr])
        im = image_model().fit(X_img[tr], y[tr])
        p_text[te] = tm.predict_proba(list(texts[te]))[:, 1]
        p_img[te] = im.predict_proba(X_img[te])[:, 1]
        if text_models_out is not None:
            text_models_out[int(f)] = tm
    return {"text": p_text, "image": p_img, "fusion": (p_text + p_img) / 2}


def fit_full(texts: list[str], X_img: np.ndarray, y: np.ndarray) -> tuple[Pipeline, Pipeline]:
    return text_model().fit(list(texts), y), image_model().fit(X_img, y)


def ngram_contributions(pipeline: Pipeline, text: str) -> dict[str, float]:
    """양성 쪽으로 미는 n-gram 기여도(계수 × TF-IDF), 양수만."""
    vec, lr = pipeline.named_steps["tfidf"], pipeline.named_steps["lr"]
    row = vec.transform([text])
    names = vec.get_feature_names_out()
    coef = lr.coef_[0]
    out: dict[str, float] = {}
    for j, v in zip(row.indices, row.data):
        c = float(coef[j] * v)
        if c > 0:
            out[str(names[j])] = c
    return out


def top_ngrams(pipeline: Pipeline, text: str, k: int = 3) -> list[str]:
    contrib = ngram_contributions(pipeline, text)
    return [g for g, _ in sorted(contrib.items(), key=lambda kv: -kv[1])[:k]]
