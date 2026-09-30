"""배너 후보 추출(브라우저 JS)과 필터(순수 함수)."""
from __future__ import annotations

from dataclasses import dataclass

from .domains import registrable_domain

# 페이지 좌표(스크롤 보정) 기준 bbox와 src/href를 뽑는다. 요소 핸들은 돌려주지 않는다.
BANNER_JS = r"""() => {
  const out = [];
  const els = document.querySelectorAll('img, iframe, [style*="background-image"]');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'
      && cs.display !== 'none' && parseFloat(cs.opacity || '1') > 0;
    let src = null;
    if (el.tagName === 'IMG') src = el.currentSrc || el.src || null;
    else if (el.tagName === 'IFRAME') src = el.src || null;
    else {
      const m = /url\(["']?([^"')]+)["']?\)/.exec(cs.backgroundImage || '');
      src = m ? m[1] : null;
    }
    const a = el.closest('a[href]');
    out.push({ tag: el.tagName.toLowerCase(), x: r.left + window.scrollX, y: r.top + window.scrollY,
               w: r.width, h: r.height, visible, src, href: a ? a.href : null });
  }
  return out;
}"""

MIN_W, MIN_H, MIN_AREA = 150, 40, 12_000
MIN_ASPECT, MAX_ASPECT = 0.2, 8.0
IOU_DUP = 0.8


@dataclass(frozen=True)
class Candidate:
    tag: str
    x: float
    y: float
    w: float
    h: float
    visible: bool
    src: str | None
    href: str | None

    @property
    def area(self) -> float:
        return self.w * self.h


def from_js(items: list[dict]) -> list[Candidate]:
    return [Candidate(tag=str(i.get("tag", "")), x=float(i.get("x", 0)), y=float(i.get("y", 0)),
                      w=float(i.get("w", 0)), h=float(i.get("h", 0)), visible=bool(i.get("visible", False)),
                      src=i.get("src"), href=i.get("href")) for i in items]


def iou(a: Candidate, b: Candidate) -> float:
    ix = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def href_domain(c: Candidate) -> str | None:
    return registrable_domain(c.href) if c.href else None


def _passes_size(c: Candidate) -> bool:
    if not c.visible or c.w < MIN_W or c.h < MIN_H or c.area < MIN_AREA:
        return False
    aspect = c.w / c.h if c.h else 0
    return MIN_ASPECT <= aspect <= MAX_ASPECT


def filter_candidates(cands: list[Candidate], page_domain: str, label: str, max_n: int = 12) -> list[Candidate]:
    pool = [c for c in cands if _passes_size(c)]
    if label == "embedded_banner":
        pool = [c for c in pool if c.href and href_domain(c) != page_domain]
    pool.sort(key=lambda c: c.area, reverse=True)
    kept: list[Candidate] = []
    for c in pool:
        if any(iou(c, k) >= IOU_DUP for k in kept):
            continue
        kept.append(c)
        if len(kept) >= max_n:
            break
    return kept
