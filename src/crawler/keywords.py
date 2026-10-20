"""검색 키워드 자동 확장: 제목에서 용어 추출, 자동 키워드 회전·수확 기록·퇴역. 상태는 seeds/explore_state.json."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from .fsutil import atomic_write_text

SUFFIXES = ("사이트", "놀이터", "검증", "카지노", "토토", "슬롯", "바카라", "파워볼", "홀덤", "릴게임")
AUTO_HEADER = "# 자동 키워드 — nightly 가 관리. 손으로 고치려면 keywords.txt 를 쓸 것"
_SPLIT = re.compile(r"[\s|\-–—·,.:;!?()\[\]【】\"'/\\<>]+")
_HANGUL = re.compile(r"[가-힣]")


def _tokens(title: str) -> list[str]:
    return [t for t in _SPLIT.split(title or "") if t]


def _acceptable(term: str, known: set[str], min_len: int, max_len: int) -> bool:
    return (min_len <= len(term) <= max_len and term.endswith(SUFFIXES) and term not in SUFFIXES
            and bool(_HANGUL.search(term)) and term not in known)


def extract_terms(titles: Iterable[str], known: set[str], min_len: int = 3, max_len: int = 12) -> list[tuple[str, int]]:
    """제목들에서 접미사(사이트·놀이터·…)로 끝나는 1~2 토큰 용어를 뽑아 (용어, 등장 제목 수) 로 돌려준다.
    등장 수 내림차순, 같으면 가나다. 2토큰 용어는 앞 토큰이 한글이고 숫자가 없을 때만."""
    counts: Counter[str] = Counter()
    for title in titles:
        toks = _tokens(title)
        seen: set[str] = set()
        for i, tok in enumerate(toks):
            cands = [tok]
            if i > 0 and _HANGUL.search(toks[i - 1]) and not any(ch.isdigit() for ch in toks[i - 1]):
                cands.append(f"{toks[i - 1]} {tok}")
            for c in cands:
                if c not in seen and _acceptable(c, known, min_len, max_len):
                    seen.add(c)
                    counts[c] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _blank(origin: str) -> dict:
    return {"origin": origin, "runs": 0, "added_total": 0, "zero_streak": 0, "last_run": None, "retired": False}


def load_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"keywords": {}, "bot_check_date": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("keywords", {})
    state.setdefault("bot_check_date", None)
    return state


def save_state(path: Path, state: dict) -> None:
    atomic_write_text(Path(path), json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def pick_auto_keywords(state: dict, auto_keywords: list[str], n: int) -> list[str]:
    """회전: last_run 이 없는 것부터, 그다음 가장 오래된 것부터 n개."""
    def key(kw: str) -> tuple[str, int]:
        return (state["keywords"].get(kw, {}).get("last_run") or "", auto_keywords.index(kw))
    return sorted(auto_keywords, key=key)[:n]


def record_run(state: dict, keyword: str, added: int, today: str, origin: str) -> None:
    info = state["keywords"].setdefault(keyword, _blank(origin))
    info["runs"] += 1
    info["added_total"] += added
    info["zero_streak"] = 0 if added > 0 else info.get("zero_streak", 0) + 1
    info["last_run"] = today


def expand(state: dict, auto_keywords: list[str], terms: list[tuple[str, int]], *,
           add_per_day: int, pool: int, retire_streak: int) -> tuple[list[str], list[str], list[str]]:
    """퇴역(zero_streak ≥ retire_streak) 뒤 새 용어를 더한다. (새 자동 키워드 목록, 추가된 것, 퇴역한 것)."""
    retired = [kw for kw in auto_keywords if state["keywords"].get(kw, {}).get("zero_streak", 0) >= retire_streak]
    for kw in retired:
        state["keywords"][kw]["retired"] = True
    kept = [kw for kw in auto_keywords if kw not in retired]
    retired_all = {kw for kw, info in state["keywords"].items() if info.get("retired")}
    added: list[str] = []
    for term, _n in terms:
        if len(kept) + len(added) >= pool or len(added) >= add_per_day:
            break
        if term in kept or term in retired_all or term in added:
            continue
        added.append(term)
        state["keywords"][term] = _blank("auto")
    return kept + added, added, retired
