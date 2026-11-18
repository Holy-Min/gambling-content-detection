"""리서치 문제 검증 집계: 차단목록 누락·배너 경유·주소 갈아타기를 우리 수집 데이터로 센다.

공개 산출물(md/json)에는 개수·비율만 쓴다. 도메인·URL 원문은 넣지 않는다.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from crawler.domains import registrable_domain

OPEN_STATUSES = {"ok", "duplicate"}
SEED_FILES = ("gambling.csv", "embedded_banner.csv", "candidates.csv")


def domain_status(index_rows: list[dict], label: str = "gambling") -> dict[str, str]:
    """도메인별 대표 상태. ok/duplicate가 한 번이라도 있으면 "open", 아니면 최신 캡처의 상태."""
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for r in index_rows:
        if r.get("label") == label and r.get("domain"):
            by_domain[r["domain"]].append(r)
    out: dict[str, str] = {}
    for dom, rows in by_domain.items():
        if any(r["status"] in OPEN_STATUSES for r in rows):
            out[dom] = "open"
        else:
            out[dom] = max(rows, key=lambda r: r.get("captured_at") or "")["status"]
    return out


def open_share(counts: dict[str, int]) -> float:
    """open ÷ (open + blocked_kr). challenge·error·robots_disallow는 분모에서 뺀다."""
    denom = counts.get("open", 0) + counts.get("blocked_kr", 0)
    return counts.get("open", 0) / denom if denom else 0.0


def open_share_variants(index_rows: list[dict]) -> dict:
    """열린 비율이 판정 규칙에 얼마나 민감한지. challenge·error·robots_disallow 는 두 규칙 모두 분모에서 뺀다.

    latest_status: 도메인의 최신 캡처 상태만 본다.
    blocked_if_never_open: 열린 적 있으면 open, 열린 적 없고 blocked_kr 기록이 있으면 blocked."""
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for r in index_rows:
        if r.get("label") == "gambling" and r.get("domain"):
            by_domain[r["domain"]].append(r)
    latest = {"open": 0, "blocked_kr": 0}
    ever = {"open": 0, "blocked_kr": 0}
    for rows in by_domain.values():
        st = max(rows, key=lambda r: r.get("captured_at") or "")["status"]
        st = "open" if st in OPEN_STATUSES else st
        if st in latest:
            latest[st] += 1
        statuses = {r["status"] for r in rows}
        if statuses & OPEN_STATUSES:
            ever["open"] += 1
        elif "blocked_kr" in statuses:
            ever["blocked_kr"] += 1
    return {k: v | {"share": open_share(v)} for k, v in
            (("latest_status", latest), ("blocked_if_never_open", ever))}


def _name_key(domain: str) -> str:
    """등록도메인의 이름 부분(첫 점 앞)에서 숫자를 지운 값."""
    return re.sub(r"\d+", "", domain.split(".")[0])


def rotation_groups(domains: list[str]) -> tuple[int, int]:
    """숫자를 지운 이름이 같은 도메인 묶음 중 크기 ≥ 2인 묶음 수와 그 안의 도메인 수."""
    groups: dict[str, set[str]] = defaultdict(set)
    for d in domains:
        key = _name_key(d)
        if key:
            groups[key].add(d)
    # 숫자가 실제로 지워진 도메인이 하나라도 있는 묶음만 센다(숫자 없이 이름만 같은 경우 제외)
    big = [g for g in groups.values()
           if len(g) >= 2 and any(re.search(r"\d", d.split(".")[0]) for d in g)]
    return len(big), sum(len(g) for g in big)


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("url") or "").strip()]


def _banner_seed_domains(seeds_dir: Path) -> set[str]:
    """seeds의 source/note에 `banner:`가 있는 행의 등록도메인(gambling.csv·candidates.csv)."""
    doms: set[str] = set()
    for name in ("gambling.csv", "candidates.csv"):
        for r in _read_rows(seeds_dir / name):
            if "banner:" in (r.get("source") or "") or "banner:" in (r.get("note") or ""):
                doms.add(registrable_domain(r["url"]))
    return doms


def _load_index(index_path: Path) -> list[dict]:
    rows = []
    with Path(index_path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize(index_path: Path, seeds_dir: Path) -> dict:
    rows = _load_index(Path(index_path))
    seeds_dir = Path(seeds_dir)
    status = domain_status(rows)
    counts = {"open": 0, "blocked_kr": 0, "challenge": 0, "error": 0}
    for st in status.values():
        counts[st] = counts.get(st, 0) + 1

    embedded = {registrable_domain(r["url"]) for r in _read_rows(seeds_dir / "embedded_banner.csv")}
    ext_banners = [
        b
        for r in rows
        if r.get("label") == "embedded_banner" and r.get("status") == "ok"
        for b in r.get("banners") or []
        if b.get("external")
    ]
    banner_links = len(ext_banners)
    banner_link_domains = len({b.get("href_domain") for b in ext_banners if b.get("href_domain")})
    by_dom: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r.get("label") == "gambling" and r.get("domain"):
            by_dom[r["domain"]].add("open" if r.get("status") in OPEN_STATUSES else r.get("status"))
    blocked_and_open = sum(1 for v in by_dom.values() if "open" in v and "blocked_kr" in v)

    gambling = set(status)
    banner_doms = _banner_seed_domains(seeds_dir) & gambling
    banner_doms |= {
        r["domain"] for r in rows
        if r.get("label") == "gambling" and (r.get("seed_source") or "").startswith("banner:")
    }

    groups, group_doms = rotation_groups(sorted(gambling))

    latest_open: dict[str, dict] = {}
    for r in rows:
        if r.get("label") == "gambling" and r.get("status") in OPEN_STATUSES and r.get("final_url"):
            cur = latest_open.get(r["domain"])
            if cur is None or (r.get("captured_at") or "") > (cur.get("captured_at") or ""):
                latest_open[r["domain"]] = r
    redirected = sum(1 for d, r in latest_open.items() if registrable_domain(r["final_url"]) != d)

    captured = [r["captured_at"][:10] for r in rows if r.get("captured_at")]
    return {
        "gambling_domains_total": len(gambling),
        "status_counts": counts,
        "open_share": open_share(counts),
        "open_share_sensitivity": open_share_variants(rows),
        "embedded_seeds": len(embedded),
        "banner_links": banner_links,
        "banner_link_domains_unique": banner_link_domains,
        "blocked_and_open": blocked_and_open,
        "banner_promoted_gambling": len(banner_doms),
        "rotation_groups": {"groups": groups, "domains": group_doms},
        "redirected": redirected,
        "captured_from": min(captured) if captured else None,
        "captured_to": max(captured) if captured else None,
    }


def materialize_seeds(ref: str, repo: Path, dest: Path) -> Path:
    """git ref(예: HEAD)의 seeds/*.csv를 dest로 꺼낸다. 작업 트리의 진행 중 변경을 피하기 위해 쓴다."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in SEED_FILES:
        out = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:seeds/{name}"],
                             capture_output=True, check=True).stdout
        (dest / name).write_bytes(out)
    return dest


def summarize_at_ref(index_path: Path, repo: Path, seeds_ref: str = "HEAD") -> dict:
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", seeds_ref],
                         capture_output=True, check=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        return summarize(index_path, materialize_seeds(seeds_ref, repo, Path(tmp))) | {"seeds_ref_sha": sha}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def write_reports(summary: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "problem_evidence.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = summary["status_counts"]
    rg = summary["rotation_groups"]
    sens = summary["open_share_sensitivity"]
    shares = [summary["open_share"], sens["latest_status"]["share"], sens["blocked_if_never_open"]["share"]]
    lo, hi = f"{min(shares) * 100:.0f}", f"{max(shares) * 100:.0f}"
    sens_line = (f"열린 비율은 세는 규칙에 따라 {lo}~{hi}%예요. 도메인의 최신 캡처 상태만 보면 "
                 f"{_pct(sens['latest_status']['share'])} ({sens['latest_status']['open']}/"
                 f"{sens['latest_status']['open'] + sens['latest_status']['blocked_kr']}), "
                 f"한 번도 열린 적 없고 막힘 기록이 있으면 막힘으로 세면 {_pct(sens['blocked_if_never_open']['share'])} "
                 f"({sens['blocked_if_never_open']['open']}/"
                 f"{sens['blocked_if_never_open']['open'] + sens['blocked_if_never_open']['blocked_kr']}).")
    rg_lo = rg["groups"] - 4  # 이름이 짧아 우연히 같아진 묶음(검토 필요 약 4묶음)을 뺀 하한
    md = f"""# 연구 문제가 실제로 있는지 확인한 결과

우리가 직접 모은 화면 데이터({summary.get('captured_from')} ~ {summary.get('captured_to')} 수집분)를 세어 봤어요. 도메인 이름과 주소는 적지 않고 개수와 비율만 적었어요.

| 확인한 것 | 결과 |
|---|---|
| 조사한 도박 사이트(도메인) 수 | {summary['gambling_domains_total']}개 |
| 한국에서 열린 곳 | {c.get('open', 0)}개 |
| 한국에서 막힌 곳 | {c.get('blocked_kr', 0)}개 |
| 확인 불가(봇 확인 화면) | {c.get('challenge', 0)}개 |
| 확인 불가(접속 오류 등) | {c.get('error', 0)}개 |
| 열린 비율 (열림 ÷ (열림 + 막힘)) | {_pct(summary['open_share'])} |
| 웹툰·무료 중계 같은 일반 사이트(조사 대상) | {summary['embedded_seeds']}개 |
| 그 사이트에서 찾은 바깥 배너 링크(같은 배너를 다시 수집한 것 포함) | {summary['banner_links']}개 |
| 위 배너 링크의 서로 다른 도착 도메인 수(중복 제거) | {summary['banner_link_domains_unique']}개 |
| 배너 링크를 따라가다 찾은 도박 사이트(최소치) | {summary['banner_promoted_gambling']}개 |
| 숫자만 바꿔 이어지는 주소 묶음 | {rg['groups']}묶음 (도메인 {rg['domains']}개; 일부는 끝자리만 같거나 우연일 수 있어 실제는 {rg_lo}~{rg['groups']}묶음) |
| 국내 차단 기록과 열림 기록이 모두 있는 도메인 | {summary['blocked_and_open']}개 |
| 다른 주소로 넘어가는 도박 사이트 | {summary['redirected']}개 |

## 읽는 법

- {sens_line}
- 열린 곳은 한 번이라도 화면이 열렸으면(정상 또는 재방문 성공) 열린 것으로 셌어요. 열린 비율에서 봇 확인 화면·접속 오류·robots 거부는 막힘인지 알 수 없어 분모에서 뺐어요.
- 배너 링크 도박 사이트는 (1) 수집 기록의 출처가 `banner:`로 시작하거나, (2) 검토 후 옮겨진 목록의 출처·메모에 `banner:`가 남은 도메인을 센 값이에요. 수집 기록의 출처로만 추적되고 검토 후 옮겨진 사이트는 거슬러 올라가 확인할 수 없어서, 이 값은 실제보다 작은 최소치예요.
- 숫자 묶음은 도메인 이름(첫 점 앞)에서 숫자를 지웠을 때 같아지는 도메인이 2개 이상인 경우예요. 이름이 짧아 우연히 같은 묶음이 섞일 수 있어요(검토 필요 약 4묶음).
- 차단 기록과 열림 기록이 모두 있는 도메인은 차단이 늦게 적용됐거나 주소·경로가 바뀌었을 수 있어요. 어느 쪽인지는 이 데이터만으로 알 수 없어요.
- 조사한 사이트는 검색·커뮤니티·배너를 통해 찾은 것이라 무작위로 뽑은 표본이 아니에요. 또 봇 확인 화면이 전체의 약 25%라서 열린 비율이 한쪽으로 치우쳤을 수 있어요.
- 주의: 한 곳의 네트워크 한 줄로만 접속했고, 봇 확인 화면은 판단에서 빠졌어요. 그래서 숫자는 정확한 전체 모습이 아니라 문제가 있다는 근거로 봐 주세요. 시드 목록은 커밋된 버전(HEAD{' ' + summary['seeds_ref_sha'][:10] if summary.get('seeds_ref_sha') else ''}) 기준이에요.
"""
    (out_dir / "problem_evidence.md").write_text(md, encoding="utf-8")
