"""시드 CSV 읽기·쓰기, 등록 도메인 기준 중복 제거, 플랫폼 제외 목록."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .domains import registrable_domain

HEADER = ["url", "source", "added_at", "note"]

PLATFORM_BLOCKLIST = frozenset({
    "naver.com", "google.com", "kakao.com", "daum.net", "youtube.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "t.me", "telegram.org", "tistory.com",
    "blogspot.com", "wikipedia.org", "apple.com", "microsoft.com", "cloudflare.com",
})


@dataclass(frozen=True)
class Seed:
    url: str
    source: str
    added_at: str
    note: str = ""


def is_platform(domain: str) -> bool:
    return domain in PLATFORM_BLOCKLIST


def read_seeds(path: Path) -> list[Seed]:
    path = Path(path)
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[Seed] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            dom = registrable_domain(url)
            if dom in seen:
                continue
            seen.add(dom)
            out.append(Seed(url=url, source=(row.get("source") or "").strip(),
                            added_at=(row.get("added_at") or "").strip(), note=(row.get("note") or "").strip()))
    return out


def seed_domains(paths: Iterable[Path]) -> set[str]:
    doms: set[str] = set()
    for p in paths:
        doms.update(registrable_domain(s.url) for s in read_seeds(Path(p)))
    return doms


def load_blocklist(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def append_candidates(path: Path, urls: Iterable[str], source: str, known_domains: set[str],
                      blocklist: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """새 등록 도메인의 URL만 candidates 파일에 추가하고 추가된 URL 목록을 돌려준다."""
    path = Path(path)
    existing = {registrable_domain(s.url) for s in read_seeds(path)}
    skip = set(known_domains) | existing | set(blocklist)
    added: list[str] = []
    rows: list[list[str]] = []
    today = date.today().isoformat()
    for url in urls:
        dom = registrable_domain(url)
        if not dom or dom in skip or is_platform(dom):
            continue
        skip.add(dom)
        added.append(url)
        rows.append([url, source, today, "unverified"])
    if not rows:
        return added
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new_file:
            writer.writerow(HEADER)
        writer.writerows(rows)
    return added
