"""후보 검토: 신호·추천 규칙(순수 함수)과 review.csv 입출력. 추천값은 사람의 검토를 돕는 힌트일 뿐 라벨이 아니다."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .config import LABELS
from .fsutil import atomic_write_text
from .store import Store

REF_KEYS = frozenset({"code", "ref", "aff", "partner", "invite", "recommend", "rec", "추천"})
GAMBLING_TLDS = (".bet", ".casino", ".poker", ".vip", ".win")
MENU_TERMS = ("충전", "입금", "출금", "환전", "가입", "배팅", "베팅", "카지노", "슬롯", "바카라", "파워볼")
VERIFY_TERMS = ("먹튀", "검증", "보증업체", "보증", "커뮤니티")
MANY_EXT_MIN = 8
HOME_STATUS_SIGNALS = ("blocked_kr", "challenge", "error")
VERDICTS = LABELS + ("community", "exclude", "blocked", "")
REVIEW_HEADER = ["domain", "url", "title", "status", "signals", "suggested", "verdict", "note", "review_dir"]
_DIGITS3 = re.compile(r"\d{3}")


@dataclass
class ReviewRow:
    domain: str
    url: str
    title: str
    status: str
    signals: list[str] = field(default_factory=list)
    suggested: str = ""
    verdict: str = ""
    note: str = ""
    review_dir: str = ""


def _has_ref_param(url: str | None) -> bool:
    if not url:
        return False
    try:
        query = urlsplit(url).query
        return any(k.lower() in REF_KEYS for k, _ in parse_qsl(query, keep_blank_values=True))
    except ValueError:  # 깨진 URL(잘못된 IPv6 등)은 신호 없음으로 처리
        return False


def home_row(rows: list[dict]) -> dict | None:
    """가장 최근 홈(idx 0) 행. 홈이 없으면 첫 행."""
    homes = [m for m in rows if Store.page_index(m) == 0]
    if homes:
        return max(homes, key=lambda m: m.get("captured_at") or "")
    return rows[0] if rows else None


def signals(domain: str, rows: list[dict]) -> list[str]:
    sig: list[str] = []
    home = home_row(rows)
    urls = [u for m in rows for u in (m.get("url"), m.get("final_url")) if u]
    if any(_has_ref_param(u) for u in urls):
        sig.append("ref_param")
    if domain.endswith(GAMBLING_TLDS):
        sig.append("tld_gambling")
    if "xn--" in domain:
        sig.append("idn")
    if any(_DIGITS3.search(label) for label in domain.split(".")):
        sig.append("numeric")
    if any(m.get("page_kind") in ("deposit", "register", "login") for m in rows):
        sig.append("deposit_page")
    texts = " ".join(f"{m.get('title') or ''} {m.get('text_excerpt') or ''}" for m in rows)
    if sum(1 for t in MENU_TERMS if t in texts) >= 2:
        sig.append("menu_terms")
    if home and len(home.get("ext_domains") or []) >= MANY_EXT_MIN:
        sig.append("many_ext")
    if any(t in texts for t in VERIFY_TERMS):
        sig.append("verify_terms")
    if home and home.get("status") in HOME_STATUS_SIGNALS:
        sig.append(home["status"])
    return sig


def looks_like_community(sig: list[str]) -> bool:
    return {"many_ext", "verify_terms"} <= set(sig)


def suggest(sig: list[str]) -> str:
    s = set(sig)
    if "blocked_kr" in s:
        return "blocked"
    if looks_like_community(sig):
        return "community"
    if ("deposit_page" in s or "menu_terms" in s) and "many_ext" not in s:
        return "gambling"
    if len(s & {"ref_param", "tld_gambling", "idn", "numeric"}) >= 2:
        return "gambling"
    return ""


def build_row(domain: str, url: str, rows: list[dict], review_dir: str) -> ReviewRow:
    home = home_row(rows) or {}
    sig = signals(domain, rows)
    return ReviewRow(domain=domain, url=url, title=home.get("title") or "", status=home.get("status") or "",
                     signals=sig, suggested=suggest(sig), review_dir=review_dir)


def _safe_cell(text: str) -> str:
    """스프레드시트가 수식으로 해석하지 않게 =,+,-,@ 로 시작하는 셀 앞에 ' 를 붙인다(이미 붙어 있으면 그대로)."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def write_review_csv(path: Path, rows: list[ReviewRow], merge: bool = False) -> None:
    """review.csv 를 쓴다. merge=True 이고 파일이 있으면 같은 날짜 재실행으로 사람의 판정이 사라지지 않게 병합한다:
    review_dir 이 아직 있고 새 행에 없는 기존 도메인은 유지, 겹치는 도메인은 새 행에 기존 verdict·note 를 보존, 순서는 기존 먼저·새 행 뒤."""
    path = Path(path)
    if merge and path.exists():
        new_by = {r.domain: r for r in rows}
        merged: list[ReviewRow] = []
        for old in read_review_csv(path):
            hit = new_by.pop(old.domain, None)
            if hit is not None:
                hit.verdict, hit.note = old.verdict or hit.verdict, old.note or hit.note
                merged.append(hit)
            elif old.review_dir and Path(old.review_dir).exists():
                merged.append(old)
        rows = merged + [r for r in rows if r.domain in new_by]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(REVIEW_HEADER)
    for r in rows:
        w.writerow([r.domain, r.url, _safe_cell(r.title), r.status, "|".join(r.signals), r.suggested, r.verdict, _safe_cell(r.note), r.review_dir])
    atomic_write_text(path, buf.getvalue())


def read_review_csv(path: Path) -> list[ReviewRow]:
    out: list[ReviewRow] = []
    with Path(path).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            g = {k: (row.get(k) or "").strip() for k in REVIEW_HEADER}
            out.append(ReviewRow(domain=g["domain"], url=g["url"], title=g["title"], status=g["status"],
                                 signals=[s for s in g["signals"].split("|") if s], suggested=g["suggested"],
                                 verdict=g["verdict"], note=g["note"], review_dir=g["review_dir"]))
    return out
