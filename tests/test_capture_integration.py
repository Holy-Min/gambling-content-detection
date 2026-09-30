import json
import shutil
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from crawler.capture import run_capture
from crawler.config import Settings
from crawler.seeds import Seed

FIXTURES = Path(__file__).parent / "fixtures" / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    shutil.copytree(FIXTURES, root)
    for name, size, color in [("banner1.png", (720, 180), (220, 30, 30)), ("banner2.png", (720, 240), (30, 30, 220)),
                              ("banner3.png", (600, 200), (30, 160, 30)), ("icon.png", (48, 48), (0, 0, 0))]:
        Image.new("RGB", size, color).save(root / name)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def fast_settings(tmp_path) -> Settings:
    return Settings(out_root=tmp_path / "dataset", salt="test-salt", per_domain=2, concurrency=1,
                    delays={"gambling": 0.0, "embedded_banner": 0.0, "hard_negative": 0.0, "normal": 0.0})


async def test_capture_saves_full_page_banners_and_index(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="gambling")
    assert summary["ok"] == 2 and summary["error"] == 0
    rows = [json.loads(l) for l in (settings.out_root / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in rows] == ["ok", "ok"]
    home = rows[0]
    assert home["title"] == "테스트 도박 사이트" and home["viewport"] == {"width": 412, "height": 915, "dpr": 2}
    full = settings.out_root / home["full_path"]
    assert full.exists() and Image.open(full).size[0] == 824      # 412 css px × DPR 2
    assert 3 <= len(home["banners"]) <= 4                           # 24px 아이콘은 제외, 지연 로딩 배너 포함
    ext = [b for b in home["banners"] if b["external"]]
    assert ext and ext[0]["href_domain"] == "toto-partner.com"
    assert all((settings.out_root / b["path"]).exists() for b in home["banners"])
    assert rows[1]["url"].endswith("/charge.html") and rows[1]["page_kind"] == "deposit"   # 충전 페이지 우선
    assert home["page_kind"] == "home"
    assert (settings.out_root / "gambling" / home["domain_hash"] / "meta.jsonl").exists()


async def test_blocked_page_is_recorded_not_captured(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/warning.html", source="test", added_at="2026-09-30")], label="gambling")
    assert summary["blocked_kr"] == 1 and summary["ok"] == 0
    rows = [json.loads(l) for l in (settings.out_root / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "blocked_kr" and rows[0]["full_path"] is None
    assert not list((settings.out_root / "gambling").rglob("*.png"))


async def test_rerun_skips_domain_that_reached_per_domain(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/", source="test", added_at="2026-09-30")]
    await run_capture(settings, seed, label="gambling")
    second = await run_capture(settings, seed, label="gambling")
    assert second["skipped_domains"] == 1 and second["ok"] == 0
    # --refresh + per_domain 상향: 홈을 다시 열어(중복 처리) 새 내부 페이지를 추가로 모은다
    settings.refresh = True; settings.per_domain = 3
    third = await run_capture(settings, seed, label="gambling")
    assert third["duplicate"] >= 1 and third["ok"] >= 1


async def test_click_menus_captures_modal_deposit_screen(site, tmp_path):
    settings = fast_settings(tmp_path)
    settings.click_menus = True; settings.per_domain = 3
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="gambling")
    rows = [json.loads(l) for l in (settings.out_root / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    # 홈 → 메뉴 클릭(입금신청: 모달 캡처, 충전문의: 변화 없음 → 기록 안 함) → 링크(charge.html)
    assert summary["ok"] == 3 and summary["menu_clicks"] == 2 and summary["menu_captures"] == 1
    assert [r["status"] for r in rows] == ["ok", "ok", "ok"]
    home, menu, link = rows
    assert home["via"] is None and menu["via"] == "menu:입금신청" and menu["page_kind"] == "deposit"
    assert menu["url"] == home["url"]                                  # 모달이라 주소는 그대로
    assert Image.open(settings.out_root / menu["full_path"]).size == (824, 1830)   # 모달은 뷰포트만 캡처
    assert link["url"].endswith("/charge.html") and link["via"] is None


async def test_click_menus_off_by_default_changes_nothing(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="gambling")
    assert summary["ok"] == 2 and summary["menu_clicks"] == 0 and summary["menu_captures"] == 0


async def test_emit_candidates_writes_external_banner_domains(site, tmp_path):
    settings = fast_settings(tmp_path)
    cand = tmp_path / "candidates.csv"
    await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-09-30")], label="embedded_banner",
                      emit_candidates=True, candidates_path=cand)
    text = cand.read_text(encoding="utf-8")
    assert "toto-partner.com" in text and "banner:127.0.0.1" in text
