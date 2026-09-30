"""index.jsonl 집계."""
from __future__ import annotations

from collections import defaultdict

STATUSES = ("ok", "blocked_kr", "challenge", "error", "duplicate", "robots_disallow")


def summarize(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    domains: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        lab = r["label"]
        s = out.setdefault(lab, {"domains": 0, **{k: 0 for k in STATUSES}, "banners": 0})
        domains[lab].add(r["domain"])
        s[r["status"]] = s.get(r["status"], 0) + 1
        s["banners"] += len(r.get("banners") or [])
    for lab, s in out.items():
        s["domains"] = len(domains[lab])
    return out


def format_table(summary: dict[str, dict]) -> str:
    cols = ["label", "domains", *STATUSES, "banners"]
    lines = [" | ".join(f"{c:>15}" if c != "label" else f"{c:<16}" for c in cols)]
    lines.append("-" * len(lines[0]))
    for lab in sorted(summary):
        s = summary[lab]
        lines.append(" | ".join([f"{lab:<16}", *(f"{s.get(c, 0):>15}" for c in cols[1:])]))
    if len(lines) == 2:
        lines.append("(index.jsonl 없음 또는 비어 있음)")
    return "\n".join(lines)
