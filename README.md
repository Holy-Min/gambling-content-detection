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
docs/         조사·기획 문서
data/raw/     수집 원본 (git 추적 제외)
data/processed/  라벨링·전처리 결과 (git 추적 제외)
src/          모델 및 파이프라인 코드
notebooks/    실험 노트북
references/   선행 연구 정리
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

내부 링크는 충전·입금·회원가입(결제 직전 화면) → 이벤트·공지·게임 → 나머지 순으로 고르고, 각 페이지에 `page_kind`(home/deposit/register/login/other)를 기록한다. 이미 수집한 도메인에서 충전 페이지를 더 모으려면 `capture --refresh --per-domain 6`. 결과는 저장소 밖 `/Users/seongmin/Downloads/논문 관련/dataset/<label>/<도메인해시>/`에 쓰이고 `index.jsonl`이 전역 색인이다. 국내 망에서 차단된 도메인은 `blocked_kr`로 기록만 한다. 시드 작성법과 실행 순서는 `seeds/README.md`.

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
- [x] 디자인 개요서 1~5번
- [ ] 지도교수 검토 및 방향 확정
- [ ] 데이터 수집 범위 및 연구윤리 절차 확인
- [ ] 개요서 6~8번 작성
- [ ] 문제정의서 (4주차)

## 주의

`data/` 하위의 수집 화면은 저장소에 커밋하지 않는다. 수집 대상의 성격상 원본 이미지 배포는 제한하고, 라벨과 메타데이터(수집일, 도메인 해시, 화면 유형)만 공개하는 방향으로 검토한다.
