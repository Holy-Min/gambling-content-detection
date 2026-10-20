"""실행 설정. 우선순위: CLI 인자 > 환경변수/.env > 기본값."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_OUT = Path("/Users/seongmin/datasets/gambling")
LABELS = ("gambling", "embedded_banner", "hard_negative", "normal")
CANDIDATE_LABEL = "candidate"   # 선캡처 전용 라벨. 데이터셋 라벨이 아니며 리뷰 루트에만 쓴다


@dataclass
class Settings:
    out_root: Path
    salt: str
    per_domain: int = 4
    max_domains: int = 300
    concurrency: int = 3
    page_timeout_ms: int = 20_000
    idle_timeout_ms: int = 5_000
    settle_ms: int = 1_500
    max_page_height: int = 15_000
    device: str = "Pixel 7"
    viewport_width: int = 412   # Playwright 기본 프로필(412×839, DPR 2.625)과 달리 스펙 값으로 고정
    viewport_height: int = 915
    dpr: int = 2
    refresh: bool = False   # 최근 창 안에 캡처한 홈도 다시 열어 내부 링크를 새로 모은다
    click_menus: bool = False   # 홈의 충전·입금·가입 메뉴(버튼·JS 링크)를 클릭해 결제 직전 화면을 추가 수집
    max_menu_clicks: int = 2    # 도메인당 클릭할 메뉴 수(내부 URL 메뉴는 클릭 대신 큐 앞에 넣으므로 제외)
    recapture_days: int = 7     # 이 일수 안에 찍은 화면은 유효한 것으로 보고 다시 찍지 않는다(야간 루프는 1)
    skip_blocked_days: int = 7  # 홈이 이 일수 안에 blocked_kr 였던 도메인은 통째로 건너뛴다
    review_root: Path | None = None   # 선캡처(candidate) 저장 루트. None 이면 out_root/_review
    nightly_search_auto: int = 5            # 밤당 돌릴 자동 키워드 수
    nightly_max_candidates: int = 40        # 밤당 선캡처할 새 후보 도메인 수
    nightly_candidate_pages: int = 2        # 후보 도메인당 페이지 수
    nightly_max_auto_communities: int = 5   # 밤당 커뮤니티 자동 등록 수
    auto_keyword_pool: int = 30             # 자동 키워드 풀 상한
    auto_keyword_add_per_day: int = 5       # 하루에 더할 자동 키워드 수
    auto_keyword_retire_streak: int = 3     # 후보 0 이 이만큼 연속이면 퇴역
    nightly_budget_min: dict[str, int] = field(default_factory=lambda: {"search": 12, "community": 8, "explore": 25, "capture": 40})
    delays: dict[str, float] = field(default_factory=lambda: {
        "gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0, "candidate": 5.0})
    robots_labels: frozenset[str] = frozenset({"hard_negative", "normal", "candidate"})

    def __post_init__(self) -> None:
        self.out_root = Path(self.out_root)
        self.review_root = Path(self.review_root) if self.review_root is not None else self.out_root / "_review"


def read_env_file(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def load_settings(out: str | None = None, env: Mapping[str, str] | None = None,
                  env_file: Path = Path(".env"), **overrides) -> Settings:
    env = dict(env if env is not None else os.environ)
    merged = {**read_env_file(env_file), **env}   # 실제 환경변수가 .env보다 우선
    salt = merged.get("CRAWLER_SALT", "").strip()
    if not salt:
        print("CRAWLER_SALT가 없습니다. .env(.env.example 참고) 또는 환경변수로 지정하세요.", file=sys.stderr)
        raise SystemExit(2)
    root = Path(out) if out else Path(merged["CRAWLER_OUT"]) if merged.get("CRAWLER_OUT") else DEFAULT_OUT
    clean = {k: v for k, v in overrides.items() if v is not None}
    if "review_root" not in clean and merged.get("CRAWLER_REVIEW"):
        clean["review_root"] = Path(merged["CRAWLER_REVIEW"])
    return Settings(out_root=root, salt=salt, **clean)
