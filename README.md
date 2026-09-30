# 화면 속 도박 콘텐츠 자동 탐지

OCR 텍스트와 화면 이미지를 함께 사용하는 멀티모달 분류로, 웹·앱 화면 내부의 도박 콘텐츠를 탐지하는 프로젝트.

- **과목** AI활용현업문제해결
- **작성자** 202650299 김성민
- **지도교수** 김영국 교수
- **저장소** https://github.com/Holy-Min/gambling-content-detection

## 문제

기존 대응은 URL·도메인 단위 차단에 의존한다. 운영자가 주소를 바꾸면 무력화되고, 정상 서비스 화면에 삽입된 도박 광고는 애초에 걸러지지 않는다. 노출 시점에 이용자 측에서 작동하는 개입 수단이 없다.

## 접근

주소가 아니라 사용자가 실제로 보는 화면 자체를 판정한다.

```
화면 캡처 ──┬─→ OCR ──→ 텍스트 분류 ──┐
            │                          ├─→ 융합 ──→ 도박 콘텐츠 여부
            └─────→ 이미지 분류 ───────┘
```

비교 대상: OCR 단독 / 이미지 단독 / 융합 모델

## 저장소 구조

```
docs/              조사·기획 문서 (01 배경 조사, 02 디자인 개요서)
docs/superpowers/  수집기 설계 스펙(specs)과 구현 계획(plans)
src/crawler/       데이터 수집기 (Playwright 기반, CLI: python -m crawler)
seeds/             시드 CSV·검색 키워드·차단 목록 (작성법은 seeds/README.md)
tests/             단위 테스트 + 로컬 픽스처 사이트로 도는 통합 테스트
data/raw/, data/processed/  수집 원본·전처리 결과 (git 추적 제외; 실제 수집물은 저장소 밖 dataset/)
notebooks/         실험 노트북 (예정)
references/        선행 연구 정리
```

## 데이터 수집기 (src/crawler)

모바일 뷰포트(Pixel 7 프로필, 412×915, DPR 2)로 페이지를 렌더링해 전체 화면 스크린샷 + 배너 크롭 + 메타데이터를 저장한다. 설계: `docs/superpowers/specs/2026-09-23-gambling-crawler-design.md`, 구현 계획: `docs/superpowers/plans/2026-09-30-gambling-crawler.md`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -e . && .venv/bin/playwright install chromium
cp .env.example .env   # CRAWLER_SALT를 임의의 긴 문자열로 바꾼다
.venv/bin/python -m crawler discover search            # 후보 → seeds/candidates.csv (사람이 검토해 gambling.csv로)
.venv/bin/python -m crawler capture --label gambling --seeds seeds/gambling.csv
.venv/bin/python -m crawler stats
.venv/bin/pytest -q                                    # 단위 + 로컬 픽스처 통합 테스트
```

내부 링크는 충전·입금·회원가입(결제 직전 화면) → 이벤트·공지·게임 → 나머지 순으로 고르고, 각 페이지에 `page_kind`(home/deposit/register/login/other)를 기록한다. 이미 수집한 도메인에서 충전 페이지를 더 모으려면 `capture --refresh --per-domain 6`. 충전·가입 화면이 링크가 아니라 버튼·JS 메뉴(모달, 팝업) 뒤에 있는 사이트는 `--click-menus`를 붙이면 홈에서 '충전·입금·가입' 글자의 메뉴를 도메인당 2개(`--max-menu-clicks`)까지 클릭해 바뀐 화면을 캡처한다(주소가 바뀌면 전체 페이지, 모달이면 뷰포트만; `via: "menu:<글자>"`로 기록). 내부 URL 메뉴는 클릭 대신 큐 앞에 넣고, 사이트 밖으로 나가는 메뉴는 따라가지 않는다. 결과는 저장소 밖 `/Users/seongmin/Downloads/논문 관련/dataset/<label>/<도메인해시>/`에 쓰이고 `index.jsonl`이 전역 색인이다. 국내 망에서 차단된 도메인은 `blocked_kr`로 기록만 하고, Cloudflare 확인·지역 차단 페이지는 `challenge`로 기록하며 화면은 남기지 않는다. 시드 작성법과 실행 순서는 `seeds/README.md`.

### 수집 현황 (2026-09-30 기준)

| 라벨 | 시드 도메인 | 정상 캡처(페이지) | 국내 망 차단 | 봇 확인·지역 차단 | 배너 크롭 |
|---|---|---|---|---|---|
| gambling | 50 | 67 (28개 도메인) | 46 | 29 | 291 |
| embedded_banner | 21 | 48 | 7 | 1 | 12 |
| hard_negative | 15 | 47 | 0 | 1 | 144 |
| normal | 8 | 27 | 0 | 0 | 81 |

차단·봇 확인 수는 페이지 단위 누적이라 재방문 때마다 늘어난다. 도박 도메인의 절반 이상이 수집 당일 이미 국내 망에서 차단돼 있었고, 충전·가입 화면은 대부분 로그인 뒤에 있어 결제 직전 화면(`page_kind=deposit`)은 아직 2건이다. 시드 후보(`seeds/candidates.csv`, 171건)는 전부 검토가 끝났고 도박 사이트로 판단한 50건만 `gambling.csv`에 있다.

알려진 한계: 화면에 보이지 않는(햄버거 메뉴 속) 충전 버튼은 찾지 못하고, 클릭 뒤 "로그인 후 이용" 안내창만 뜨는 경우는 변화 없음으로 처리해 사유를 기록하지 않는다.

## 문서

| 문서 | 내용 | 형식 |
|---|---|---|
| [01 연구 배경 조사](docs/01_background-research.md) | 배경·필요성, 타겟 고객, 현행 대응 체계, 선행 연구, GAP 분석 | Markdown (바로 열람) |
| [01 연구 배경 조사 (Word)](docs/01_background-research.docx) | 위 문서의 제출용 버전 | docx (다운로드) |
| [02 디자인 개요서 (PDF)](docs/02_design-brief.pdf) | 제출용 양식, 1~5번 작성 완료 | PDF (바로 열람) |
| [02 디자인 개요서 (Word)](docs/02_design-brief.docx) | 위 문서의 편집용 원본 | docx (다운로드) |

> GitHub는 Word 파일을 브라우저에서 미리보기하지 못한다. 내용을 바로 확인하려면 Markdown 또는 PDF 링크를 이용한다.

## 진행 상황

- [x] 배경 조사
- [x] 디자인 개요서 (양식 1) · 문제점 목록 (양식 2)
- [x] 아이디에이션 결과보고서 (양식 3) — 보호자 관점(결제 직전 개입)으로 재정의한 별도 버전 포함
- [x] 데이터 수집기 구현 (discover / capture / stats, 테스트 52개)
- [x] 1차 수집: 도박·삽입 배너·하드 네거티브·일반 4개 라벨, 시드 후보 171건 검토
- [x] 결제 직전 화면 수집: 충전·가입 링크 우선 추적, `--refresh`, `--click-menus`
- [ ] 지도교수 검토 및 방향 확정 (수집 범위·연구윤리 절차 포함)
- [ ] 라벨링 기준서 작성, 수작업 수집 이미지 14장 편입
- [ ] 정상 결제 화면(쇼핑·앱마켓·은행) 하드 네거티브 추가
- [ ] 학부모 2~3인 인터뷰 후 아이디어 재평가
- [ ] OCR 단독 / 이미지 단독 / 융합 모델 실험

## 주의

`data/` 하위의 수집 화면은 저장소에 커밋하지 않는다. 수집 대상의 성격상 원본 이미지 배포는 제한하고, 라벨과 메타데이터(수집일, 도메인 해시, 화면 유형)만 공개하는 방향으로 검토한다.
