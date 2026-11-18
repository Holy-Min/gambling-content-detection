# 중간보고서용 1차 판정 모델 · 클릭 시안 · 페르소나 점검 · 보고서 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집한 화면 592쪽으로 OCR·이미지·융합 1차 판정 모델을 평가하고, 「멈칫」 클릭 시안과 AI 페르소나 사전 점검 결과를 만들어 11/11 중간보고서 docx를 채운다.

**Architecture:** `src/detector/`(데이터 적재·분할 → OCR 캐시 → CLIP 임베딩 캐시 → out-of-fold 3모델 평가·지표·부트스트랩 → 리포트 파일)와 `scripts/vision_ocr.swift`(Apple Vision OCR CLI). 문제 검증 집계는 `src/detector/evidence.py`. 시안은 `prototype/web/index.html` 단일 파일 + Playwright 캡처 스크립트. 페르소나 점검과 보고서 작성은 코드 밖 작업(Task 7·8).

**Tech Stack:** Python 3.12(시스템 python3 기반 `.venv-detector`, `--system-site-packages`로 torch 2.14 재사용), scikit-learn, transformers(CLIP ViT-B/32), matplotlib, Swift 6.4 + Vision, Playwright(기존 `.venv`), python-docx.

**Spec:** `docs/superpowers/specs/2026-11-09-midterm-prototype-design.md`

## Global Constraints

- 데이터는 `~/datasets/gambling/index.jsonl`의 `status == "ok"` 행만. 경로는 `full_path`(데이터셋 루트 기준 상대 경로).
- 첫 화면 = PNG 상단 높이 1830px(824×1830, 412×915 @DPR2). 더 짧으면 있는 만큼.
- 양성 `gambling`=1, 음성 `hard_negative`·`normal`=0, `embedded_banner`는 학습·평가 제외(별도 판정 비율만).
- 분할: 도메인 단위 `StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)`, 3모델 공통. 지표는 out-of-fold 예측으로.
- 임계값 0.5 고정. 부트스트랩 도메인 단위 1,000회, 95% 구간, seed 42.
- 목표치: F1 ≥ 0.90, 하드 네거티브 오탐률 ≤ 0.02(분모 hard_negative만), 충전(`page_kind=="deposit"`) 재현율 ≥ 0.90, 융합 F1 − max(텍스트, 이미지) F1 ≥ 0.03.
- OCR 원문·임베딩·도메인 원문은 저장소 밖 `~/datasets/gambling/_features/`에만. 저장소 `docs/week11/`에는 개수·비율·해시만.
- 실제 도박 화면 이미지를 저장소·보고서에 넣지 않는다. 외부 AI API로 화면을 보내지 않는다.
- 회사·회사 앱 이름 금지. 시안 문구는 해요체, "중독" 대신 행동 표현.
- 커밋·푸시는 하지 않는다(사용자 승인 후 내가 일괄). 각 Task 끝에 바뀐 파일 목록만 보고.
- 테스트 실행: `cd /Users/seongmin/gambling-content-detection && .venv-detector/bin/python -m pytest tests/detector -q`

## Review Focus

- OCR이 빈 결과를 내는 화면(이미지형 화면·흰 화면) → 텍스트 모델이 빈 문자열을 받아도 예외 없이 확률을 낸다. (Task 4 테스트 `test_empty_text_gets_probability`)
- 높이가 1830보다 작은 PNG·RGBA·팔레트 PNG → 첫 화면 크롭이 예외 없이 RGB로 나온다. (Task 1 `test_first_screen_short_and_rgba`)
- 어떤 fold에 양성 또는 음성이 0개 → 분할이 그런 fold를 만들지 않는다(실데이터 도메인 수로 검증). (Task 1 `test_every_fold_has_both_classes`)
- 부트스트랩 재표본에 한 클래스만 뽑힘 → 그 재표본은 건너뛰고 유효 횟수를 기록, NaN을 내지 않는다. (Task 4 `test_bootstrap_skips_degenerate`)
- 캐시가 중간에 끊긴 상태에서 재실행 → 이미 처리한 id는 건너뛰고 나머지만 처리한다. (Task 2 `test_ocr_cache_resume`, Task 3 `test_embed_cache_resume`)

---

### Task 1: 데이터 적재·첫 화면 크롭·도메인 분할

**Files:**
- Create: `src/detector/__init__.py`, `src/detector/data.py`, `src/detector/split.py`, `requirements-detector.txt`, `tests/detector/__init__.py`, `tests/detector/test_data_split.py`
- 환경: `python3 -m venv --system-site-packages .venv-detector && .venv-detector/bin/pip install -e . scikit-learn transformers matplotlib pytest pytest-asyncio` (requirements-detector.txt에 scikit-learn·transformers·matplotlib 기록). `.gitignore`에 `.venv-detector/` 추가.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Sample: id: str; label: str; y: int | None; domain: str; domain_hash: str; page_kind: str | None; image_path: Path`
  - `load_samples(index_path: Path, dataset_root: Path, include_embedded: bool = False) -> list[Sample]` — ok 행만, `y` = 1/0, embedded_banner는 `include_embedded=True`일 때만 포함(`y=None`).
  - `first_screen(path: Path, height: int = 1830) -> PIL.Image.Image` — RGB.
  - `make_folds(samples: list[Sample], k: int = 5, seed: int = 42) -> np.ndarray` — 샘플별 fold 번호(0..k-1).

- [ ] **Step 1: 실패하는 테스트 작성** — 임시 디렉터리에 가짜 index.jsonl(행 6~10개: gambling·hard_negative·normal·embedded_banner·status≠ok 섞어서)과 작은 PNG를 만들어:
  - `test_load_samples_filters_ok_and_labels`: ok가 아닌 행 제외, `y` 매핑(gambling→1, hard_negative/normal→0), embedded_banner 기본 제외·`include_embedded=True`면 `y is None`.
  - `test_first_screen_short_and_rgba`: 824×3000 → (824, 1830); 824×900 RGBA → (824, 900) 모드 "RGB"; 팔레트("P") PNG도 RGB.
  - `test_folds_never_share_domain`: 도메인 12개(양성 6·음성 6, 도메인당 1~3쪽)에서 각 도메인의 fold 번호가 하나뿐.
  - `test_every_fold_has_both_classes`: 실데이터(`~/datasets/gambling/index.jsonl`이 있으면, 없으면 skip)로 5개 fold 모두 양성·음성 ≥ 1.
- [ ] **Step 2: 실패 확인** — Run: `.venv-detector/bin/python -m pytest tests/detector/test_data_split.py -q` → ImportError로 FAIL
- [ ] **Step 3: 구현** — `make_folds`는 `sklearn.model_selection.StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=seed)`, `groups=domain`.
- [ ] **Step 4: 통과 확인** — 같은 명령 → 4 passed
- [ ] **Step 5: 기존 테스트 깨지지 않음** — `.venv/bin/python -m pytest -q` (기존 115개) 통과

### Task 2: Apple Vision OCR CLI와 캐시

**Files:**
- Create: `scripts/vision_ocr.swift`, `src/detector/ocr.py`, `tests/detector/test_ocr.py`

**Interfaces:**
- Consumes: `Sample`, `first_screen`
- Produces:
  - `scripts/vision_ocr.swift`: 인자 = 이미지 경로들(이미 크롭된 PNG). 표준출력에 경로당 JSON 한 줄 `{"path": str, "lines": [{"text": str, "conf": float, "box": [x, y, w, h]}], "ms": float}`. `VNRecognizeTextRequest`, `.accurate`, `recognitionLanguages = ["ko-KR", "en-US"]`, `usesLanguageCorrection = true`. 실행은 `swiftc -O`로 `~/datasets/gambling/_features/bin/vision_ocr`에 한 번 컴파일 후 재사용.
  - `run_ocr(samples: list[Sample], cache_dir: Path, batch: int = 32) -> dict[str, dict]` — id → `{"text": str(줄을 "\n"으로 이음), "lines": [...], "ms": float}`. 캐시 `cache_dir/<id>.json`, 있으면 건너뜀. 크롭 PNG는 임시 디렉터리에 쓰고 지움.

- [ ] **Step 1: 실패하는 테스트** — PIL + `/System/Library/Fonts/AppleSDGothicNeo.ttc`로 흰 바탕 824×600에 "첫 충전 보너스 100%"를 큰 글씨로 그린 이미지:
  - `test_vision_ocr_reads_korean`: `run_ocr` 결과 text에 "충전" 포함, `ms > 0`.
  - `test_ocr_cache_resume`: 첫 실행 후 캐시 파일 존재; 두 번째 실행에서 OCR 실행 함수(서브프로세스 호출부)를 monkeypatch로 감시해 이미 처리한 id는 다시 넘기지 않음.
  - `test_blank_image_gives_empty_text`: 흰 이미지 → text == "" (예외 없음).
- [ ] **Step 2: 실패 확인** — `.venv-detector/bin/python -m pytest tests/detector/test_ocr.py -q` → FAIL
- [ ] **Step 3: 구현** — Swift는 `CGImageSource`로 읽고 박스는 Vision 정규화 좌표 그대로(0~1). 파이썬은 `subprocess.run([...], capture_output=True, check=True)`.
- [ ] **Step 4: 통과 확인** → 3 passed
- [ ] **Step 5: 실데이터 캐시 생성** — `.venv-detector/bin/python -m detector ocr` (Task 4의 CLI가 아직 없으면 `python -c`로 `run_ocr(load_samples(..., include_embedded=True), ~/datasets/gambling/_features/ocr)`) → 592개 캐시. 처리 시간 중앙값 출력.

### Task 3: CLIP 이미지 임베딩과 캐시

**Files:**
- Create: `src/detector/embed.py`, `tests/detector/test_embed.py`

**Interfaces:**
- Consumes: `Sample`, `first_screen`
- Produces: `embed_images(samples: list[Sample], cache_dir: Path, model_name: str = "openai/clip-vit-base-patch32", device: str | None = None) -> np.ndarray` — shape `(len(samples), 512)`, float32, L2 정규화. 첫 화면을 위·아래 두 타일(824×915)로 잘라 각각 `CLIPModel.get_image_features` 후 평균, 다시 L2 정규화. 캐시 `cache_dir/<id>.npy`. device 기본은 mps 가능하면 mps, 아니면 cpu.

- [ ] **Step 1: 실패하는 테스트** — 서로 다른 무늬 PNG 3장:
  - `test_embed_shape_and_norm`: shape (3, 512), 각 행 노름 ≈ 1(±1e-4).
  - `test_embed_cache_resume`: 두 번째 호출에서 모델 forward를 monkeypatch로 감시해 0회 호출, 결과 동일.
  - `test_short_image_single_tile`: 높이 900 이미지도 예외 없이 (1, 512).
- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** → 3 passed
- [ ] **Step 5: 실데이터 캐시 생성** — 592개 → `~/datasets/gambling/_features/clip/`. 장당 시간 중앙값 출력.

### Task 4: 3모델 out-of-fold 평가·지표·부트스트랩·리포트

**Files:**
- Create: `src/detector/metrics.py`, `src/detector/models.py`, `src/detector/report.py`, `src/detector/__main__.py`, `tests/detector/test_metrics.py`, `tests/detector/test_models.py`
- Output(공개): `docs/week11/metrics.json`, `docs/week11/metrics.md`, `docs/week11/fig_model_compare.png`, `docs/week11/fig_confusion_fusion.png`, `docs/week11/error_analysis.md`
- Output(비공개): `~/datasets/gambling/_features/predictions.csv`(id·domain·label·page_kind·p_text·p_image·p_fusion·fold), `~/datasets/gambling/_features/evidence.json`(양성 판정 화면별 근거 n-gram·OCR 줄)

**Interfaces:**
- Consumes: Task 1~3 전부
- Produces:
  - `metrics.py`: `confusion(y, p, thr=0.5) -> dict(tp, fp, tn, fn)`, `f1(y, p, thr=0.5) -> float`, `rate(y_pred_positive_mask) -> float`, `bootstrap_ci(stat_fn: Callable[[np.ndarray], float], groups: np.ndarray, n: int = 1000, seed: int = 42) -> tuple[float, float, int]` — 도메인을 복원추출, `stat_fn(idx)`가 예외·NaN이면 그 회차 제외, (하한, 상한, 유효 횟수). `threshold_for_fpr(y_neg_scores: np.ndarray, target: float = 0.02) -> float`.
  - `models.py`: `text_model() -> Pipeline`(TfidfVectorizer(analyzer="char_wb", ngram_range=(2,4), lowercase=True, min_df=2) + LogisticRegression(class_weight="balanced", max_iter=2000)), `image_model() -> Pipeline`(StandardScaler + LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0)), `oof_predict(texts: list[str], X_img: np.ndarray, y: np.ndarray, folds: np.ndarray) -> dict[str, np.ndarray]` — 키 "text"·"image"·"fusion"(두 확률 평균). `fit_full(...)`로 전체 학습 모델 반환(embedded_banner 판정용). `top_ngrams(pipeline, text, k=3) -> list[str]`.
  - CLI: `python -m detector ocr|embed|evaluate|evidence`.
  - `metrics.json` 구조: `{"n": {"screens": {...}, "domains": {...}}, "models": {"text"|"image"|"fusion": {"f1": [v, lo, hi], "precision": [...], "recall": [...], "fpr_hard_negative": [...], "fpr_normal": [...], "recall_deposit": [...], "recall_at_fpr2": v, "thr_at_fpr2": v}}, "fusion_gain_f1": v, "targets": {...}, "embedded_banner_flag_rate": [v, n_screens, n_domains], "timing_ms_median": {"ocr": v, "embed": v, "classify": v}}`

- [ ] **Step 1: 실패하는 테스트**
  - `test_f1_and_confusion`: y=[1,1,0,0], p=[0.9,0.4,0.6,0.1] → tp1 fp1 tn1 fn1, f1 = 0.5.
  - `test_bootstrap_ci_contains_point`: 도메인 20개 합성 데이터에서 lo ≤ 점추정 ≤ hi, 유효 횟수 1000.
  - `test_bootstrap_skips_degenerate`: 양성 도메인 1개뿐인 데이터 → 일부 회차 제외, 결과에 NaN 없음, 유효 횟수 < 1000.
  - `test_threshold_for_fpr`: 음성 점수 0.00~0.99 100개 → 반환 임계값에서 음성의 양성 판정 비율 ≤ 0.02.
  - `test_oof_never_sees_test_domain`: 도메인마다 고유 토큰("dom7tok")이 텍스트에 들어 있고 라벨이 도메인과 완전히 연동된 합성 데이터 — 학습 fold에 없는 토큰이라 out-of-fold 텍스트 확률이 도메인 고유 토큰만으로 1.0에 수렴하지 않음(누수 검출용: 같은 데이터로 학습한 in-sample 확률 평균보다 OOF 확률 평균이 확실히 낮음).
  - `test_fusion_is_mean`: `oof_predict` 결과 fusion == (text + image) / 2.
  - `test_empty_text_gets_probability`: 학습 텍스트에 빈 문자열이 섞여도 예외 없고 확률이 0~1.
- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — `report.py`가 metrics.json·metrics.md(3모델 비교표: 지표·점추정·95% 구간·목표·달성 여부, 표본 수 표), 그래프 2장(matplotlib, 한글 폰트 AppleSDGothicNeo), error_analysis.md(오탐 전부·미탐 상위 10: domain_hash·label·page_kind·OCR 글자 수·p_text·p_image·추정 원인 — 원인은 규칙: OCR 글자 < 20 → "글자 거의 없는 화면", page_kind login → "로그인 화면", hard_negative 오탐 → "정상 결제·게임 문구 유사", 그 외 "기타(확인 필요)")를 쓴다. 원문·도메인은 공개 파일에 넣지 않는다.
- [ ] **Step 4: 통과 확인** → 7 passed
- [ ] **Step 5: 실데이터 평가** — `.venv-detector/bin/python -m detector evaluate` → 공개·비공개 산출물 생성, 표준출력에 3모델 F1·오탐률·충전 재현율 요약.

### Task 5: 리서치 문제 검증 집계

**Files:**
- Create: `src/detector/evidence.py`, `tests/detector/test_evidence.py`
- Output: `docs/week11/problem_evidence.md`, `docs/week11/problem_evidence.json`

**Interfaces:**
- Consumes: `index.jsonl`, `seeds/*.csv`(gambling·embedded_banner·candidates 등 — 실제 파일명·열은 `seeds/README.md` 확인)
- Produces: `domain_status(index_rows: list[dict], label: str = "gambling") -> dict[str, str]`(도메인 → 최신 캡처 시각 기준 대표 상태: ok/duplicate가 한 번이라도 있으면 "open", 아니면 최신 상태), `summarize(index_path: Path, seeds_dir: Path) -> dict` — 키: `gambling_domains_total`, `status_counts`(open/blocked_kr/challenge/error), `open_share`(open ÷ (open+blocked_kr), challenge·error는 분모 제외), `embedded_seeds`, `banner_links`(embedded_banner ok 행의 external 배너 수), `banner_promoted_gambling`(seed_source가 `banner:`로 시작하는 gambling 도메인 수), `rotation_groups`(숫자를 지운 등록도메인 이름이 같은 gambling 도메인 묶음 중 크기 ≥ 2인 묶음 수와 도메인 수 — 규칙을 md에 명시), `redirected`(final_url 등록도메인 ≠ domain인 gambling 도메인 수).

- [ ] **Step 1: 실패하는 테스트** — 가짜 index 행으로:
  - `test_domain_status_prefers_open`: 같은 도메인 blocked_kr(9/30) + ok(10/7) → "open"; blocked_kr만 → "blocked_kr".
  - `test_open_share_excludes_challenge`: open 3·blocked 1·challenge 2 → 0.75.
  - `test_rotation_groups`: toto12.com·toto34.net·abc.com → 묶음 1개·도메인 2개.
- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — md는 쉬운 말 문장 + 표(도메인 원문 없음).
- [ ] **Step 4: 통과 확인** → 3 passed
- [ ] **Step 5: 실데이터 실행** — `python -m detector evidence` → md·json 생성, 수치 출력.

### Task 6: 「멈칫」 클릭 시안과 캡처

**Files:**
- Create: `prototype/web/index.html`, `prototype/web/README.md`(여는 법·화면 목록), `prototype/capture.py`
- Output: `docs/week11/prototype/*.png`

**Interfaces:**
- Consumes: 판정 근거 키워드 — 처음엔 자리값 `["첫충 보너스", "입금 계좌", "실시간 배당"]`, Task 4 후 `evidence.json`에서 빈도 높은 일반 키워드로 교체(사이트명·도메인·숫자 계좌 제외, 내가 고름).
- Produces: URL 해시로 상태 진입 가능(`#onboarding`, `#chat`, `#judging`, `#card`, `#charge`, `#cooldown`, `#cooldown-done`, `#trusted-preview`, `#record`, `#game-pay`, `#game-pay-false-positive`, `#settings-off`) + `?speed=10`(타이머 10배속) + `?level=notify|pause|block`(개입 강도). `capture.py`는 기존 `.venv`의 Playwright로 각 해시를 412×915 @DPR2로 열어 `docs/week11/prototype/<해시>.png` 저장.

- [ ] **Step 1: 화면 구현** — 스펙 §7.3의 흐름·버튼·강도별 동작 그대로. 데이터(약속 문구·기간·시작 금액·신뢰인)는 온보딩 입력을 `localStorage` 없이 메모리 상태로 유지, 기본값은 문제정의서 TO-BE 1(약속 "다시 안 한다. 잃은 180만 원을 기억한다", 90일, 180만 원, 멈칫하기, 신뢰인 사촌 형·충전 시도 때만·금액·유형만). 쿨다운: 잃은 돈 185만 원·이번 5만 원. 도박·충전 화면은 CSS 목업(슬롯 아이콘 도형, "첫 충전 보너스" 같은 일반 문구, 실제 사이트명 없음). 정상 결제 = 가상 모바일 게임 "보석 1,200개 ₩12,000" 화면 → 개입 없음 + 하단 작은 "잘못 잡혔나요? 정상 게임으로 표시" 경로(`#game-pay-false-positive`).
- [ ] **Step 2: 동작 확인(수동 체크 스크립트)** — `capture.py`에 각 해시에서 핵심 요소 존재를 단언: `#card`에 "나가기" 버튼 활성·"계속 보기" 비활성(멈칫하기), `?level=block#cooldown`에 "계속" 버튼 없음, `?level=notify#cooldown`에 "계속" 즉시 활성, `#cooldown-done`에 "계속" 활성. Run: `.venv/bin/python prototype/capture.py` → 단언 통과·PNG 12장 이상
- [ ] **Step 3: 캡처 이미지 육안 확인** — 글자 잘림·겹침 없음(내가 PNG를 열어 확인)

### Task 7: AI 페르소나 사전 점검 (코드 아님 — 오케스트레이터가 진행)

**Files:**
- Create: `docs/week11/persona_test/README.md`(방법·한계, 머리 문구 "AI 페르소나(합성 사용자) 사전 점검 — 실제 사용자 테스트 아님"), `personas.md`(8개 카드), `transcripts/<번호>_<역할>.md`(1·2회차 전문), `summary.md`(선택 기록 집계·발견·검토 표)

- [ ] **Step 1:** 페르소나 카드 8개 작성(스펙 §7.4 구성).
- [ ] **Step 2:** sonnet 에이전트 8개 동시 실행 — 입력: 카드, AS-IS 1·2, `docs/week11/prototype/*.png` 경로(Read로 보게), 1회차 질문지. 답은 정해진 JSON(선택·이유·감시감 1~5·켜 두기 여부·지우고 싶은 순간·인용 3개) + 생각 말하기 본문.
- [ ] **Step 3:** 1회차 답을 읽고 페르소나별 꼬리 질문 2~3개 → SendMessage로 같은 에이전트에 2회차.
- [ ] **Step 4:** `summary.md`에 집계(나가기 선택 비율 등 — "가설" 표기)와 검토 표(발견 → AI 반응 → 판단 수용/보류/기각 → 이유 → 반영). 수용 1~3개는 Task 6 시안에 반영하고 before/after PNG(`docs/week11/prototype/before_after/`).

### Task 8: 중간보고서 docx (코드 아님 — 오케스트레이터가 진행, 그림·채우기 스크립트는 위임 가능)

**Files:**
- Create: `/Users/seongmin/Documents/대학원/AI활용현업문제해결/week11_images/` 아래 `scripts/build_midterm.py`(양식 docx를 python-docx로 채움 — 안내 상자 삭제, 장별 본문·표·그림 삽입), 그림(그림 1 AS-IS vs TO-BE 흐름, 그림 2 시스템 구성도, 그림 3 시안 화면 묶음, 그림 4 3모델 비교, 그림 5 혼동행렬), 출력 `중간보고서_김성민_멈칫.docx`(과목 폴더)
- 원본 양식: `/Users/seongmin/Downloads/AI활용현업문제해결_중간보고서_양식_2026.docx`

- [ ] **Step 1:** 장별 본문 초안(스펙 §7.5) — 수치는 `metrics.json`·`problem_evidence.json`·`persona_test/summary.md`에서만 가져온다.
- [ ] **Step 2:** 그림 생성(흐름도·구성도는 matplotlib 또는 HTML→Playwright 캡처), `build_midterm.py`로 docx 생성.
- [ ] **Step 3:** LibreOffice로 PDF→PNG 렌더, 쪽마다 확인(표 쪼개짐·그림 번호·본문 10쪽 내외·회사명 없음 `grep`).
- [ ] **Step 4:** 사용자 확인 → 수정 → (승인 시) 저장소 커밋·푸시 여부 질문.
