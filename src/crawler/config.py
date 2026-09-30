"""실행 설정. 우선순위: CLI 인자 > 환경변수/.env > 기본값."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_OUT = Path("/Users/seongmin/Downloads/논문 관련/dataset")
LABELS = ("gambling", "embedded_banner", "hard_negative", "normal")


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
    refresh: bool = False   # 최근 7일 내 캡처한 홈도 다시 열어 내부 링크를 새로 모은다
    delays: dict[str, float] = field(default_factory=lambda: {
        "gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0})
    robots_labels: frozenset[str] = frozenset({"hard_negative", "normal"})


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
        raise SystemExit("CRAWLER_SALT가 없습니다. .env(.env.example 참고) 또는 환경변수로 지정하세요.")
    root = Path(out) if out else Path(merged["CRAWLER_OUT"]) if merged.get("CRAWLER_OUT") else DEFAULT_OUT
    clean = {k: v for k, v in overrides.items() if v is not None}
    return Settings(out_root=root, salt=salt, **clean)
