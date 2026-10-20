"""시드 CSV 읽기·쓰기, 등록 도메인 기준 중복 제거, 플랫폼 제외 목록."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .config import LABELS
from .domains import registrable_domain
from .fsutil import atomic_write_text

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


def read_rows(path: Path) -> list[dict[str, str]]:
    """원본 행 그대로(중복 포함). 다시 써야 할 때 쓴다."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (row.get(k) or "").strip() for k in HEADER} for row in csv.DictReader(f)]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """HEADER 순서로 파일을 덮어쓴다."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows([[r.get(k, "") for k in HEADER] for r in rows])
    atomic_write_text(Path(path), buf.getvalue())


def update_notes(path: Path, notes: dict[str, str]) -> int:
    """등록 도메인 -> note 로 갱신하고 바뀐 행 수를 돌려준다."""
    rows = read_rows(path)
    n = 0
    for r in rows:
        new = notes.get(registrable_domain(r["url"]))
        if new is not None and r["note"] != new:
            r["note"] = new
            n += 1
    if n:
        write_rows(path, rows)
    return n


def append_seed(path: Path, url: str, source: str, note: str = "", added_at: str | None = None) -> bool:
    """같은 등록 도메인이 이미 있으면 False, 아니면 한 행 추가하고 True."""
    path = Path(path)
    dom = registrable_domain(url)
    if dom in {registrable_domain(r["url"]) for r in read_rows(path)}:
        return False
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new_file:
            w.writerow(HEADER)
        w.writerow([url, source, added_at or date.today().isoformat(), note])
    return True


def remove_domain(path: Path, domain: str) -> int:
    """해당 등록 도메인 행을 지우고 지운 행 수를 돌려준다."""
    rows = read_rows(path)
    kept = [r for r in rows if registrable_domain(r["url"]) != domain]
    if len(kept) != len(rows):
        write_rows(path, kept)
    return len(rows) - len(kept)


def update_source(path: Path, domain: str, source: str) -> bool:
    """해당 등록 도메인 행의 source 를 바꾼다. 바뀐 행이 있으면 True."""
    rows = read_rows(path)
    hit = False
    for r in rows:
        if registrable_domain(r["url"]) == domain:
            r["source"] = source
            hit = True
    if hit:
        write_rows(path, rows)
    return hit


def read_keywords(path: Path) -> list[str]:
    """주석·빈 줄을 뺀 키워드 목록(순서 유지, 중복 제거)."""
    path = Path(path)
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        kw = line.strip()
        if kw and not kw.startswith("#") and kw not in out:
            out.append(kw)
    return out


def write_keywords(path: Path, keywords: list[str], header: str) -> None:
    """헤더 한 줄과 키워드를 한 줄씩 덮어쓴다."""
    atomic_write_text(Path(path), "".join([header + "\n"] + [k + "\n" for k in keywords]))


def all_seed_files(seeds_dir: Path) -> list[Path]:
    """라벨 4개 + community_lists + candidates 시드 파일 경로."""
    seeds_dir = Path(seeds_dir)
    return [seeds_dir / f"{lab}.csv" for lab in LABELS] + [seeds_dir / "community_lists.csv", seeds_dir / "candidates.csv"]
