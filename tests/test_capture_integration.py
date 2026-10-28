import json
import time

from PIL import Image

from crawler.capture import run_capture
from crawler.seeds import Seed
from crawler.store import Store
from tests.conftest import fast_settings


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


def index_rows(root):
    return [json.loads(l) for l in (root / "index.jsonl").read_text(encoding="utf-8").splitlines()]


async def test_meta_has_text_excerpt_and_external_domains(site, tmp_path):
    settings = fast_settings(tmp_path)
    await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="gambling")
    home, charge = index_rows(settings.out_root)
    assert "첫 충전 100% 보너스" in home["text_excerpt"] and len(home["text_excerpt"]) <= 300
    assert home["ext_domains"] == ["toto-partner.com", "elsewhere.net"]
    assert charge["ext_domains"] == [] and charge["text_excerpt"].startswith("충전 신청")


async def test_recapture_window_zero_reshoots_and_dedups(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/", source="test", added_at="2026-10-20")]
    first = await run_capture(settings, seed, label="gambling")
    settings.recapture_days = 0
    second = await run_capture(settings, seed, label="gambling")
    assert first["ok"] == 2
    assert second["skipped_domains"] == 0 and second["ok"] == 0 and second["duplicate"] == 2
    assert len([p for p in (settings.out_root / "gambling").rglob("*_full.png")]) == 2   # 중복 파일은 남기지 않는다


async def test_recently_blocked_domain_is_skipped_until_window_passes(site, tmp_path):
    settings = fast_settings(tmp_path)
    seed = [Seed(url=site + "/warning.html", source="test", added_at="2026-10-20")]
    first = await run_capture(settings, seed, label="gambling")
    settings.recapture_days = 0
    second = await run_capture(settings, seed, label="gambling")
    assert first["blocked_kr"] == 1 and second["skipped_blocked"] == 1 and second["blocked_kr"] == 0 and second["domains"] == 1
    settings.skip_blocked_days = 0
    third = await run_capture(settings, seed, label="gambling")
    assert third["blocked_kr"] == 1 and third["skipped_blocked"] == 0


async def test_run_capture_writes_to_external_store(site, tmp_path):
    settings = fast_settings(tmp_path)
    review = Store(tmp_path / "_review", settings.salt)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="candidate", store=review)
    assert summary["ok"] == 2 and not (settings.out_root / "index.jsonl").exists()
    rows = index_rows(tmp_path / "_review")
    assert rows[0]["label"] == "candidate" and rows[0]["full_path"].startswith("candidate/")


async def test_run_capture_deadline_in_the_past_skips_every_domain(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="gambling", deadline=time.monotonic())
    assert summary["skipped_deadline"] == 1 and summary["deadline_hit"] == 0 and summary["ok"] == 0 and summary["domains"] == 0
    assert not (settings.out_root / "index.jsonl").exists()


async def test_run_capture_far_deadline_changes_nothing(site, tmp_path):
    settings = fast_settings(tmp_path)
    summary = await run_capture(settings, [Seed(url=site + "/", source="test", added_at="2026-10-20")], label="gambling", deadline=time.monotonic() + 600)
    assert summary["ok"] == 2 and summary["skipped_deadline"] == 0 and summary["deadline_hit"] == 0


async def test_webtoon_banners_without_anchor_are_extracted(site, tmp_path):
    settings = fast_settings(tmp_path)
    cand = tmp_path / "candidates.csv"
    await run_capture(settings, [Seed(url=site + "/webtoon.html", source="test", added_at="2026-10-28")], label="embedded_banner",
                      emit_candidates=True, candidates_path=cand)
    home = index_rows(settings.out_root)[0]
    domains = {b["href_domain"] for b in home["banners"]}
    assert {"toto-button.com", "toto-onclick.com", "toto-anchor.com"} <= domains
    assert not any(b["href_domain"] == "127.0.0.1" for b in home["banners"])
    text = cand.read_text(encoding="utf-8")
    assert all(d in text for d in ("toto-button.com", "toto-onclick.com", "toto-anchor.com"))


def _mean(path):
    px = Image.open(path).convert("RGB").resize((1, 1), Image.BILINEAR).getpixel((0, 0))
    return px


async def test_overlay_hidden_for_embedded_banner_crop_is_the_banner(site, tmp_path):
    settings = fast_settings(tmp_path)
    await run_capture(settings, [Seed(url=site + "/overlay.html", source="test", added_at="2026-10-28")], label="embedded_banner")
    home = index_rows(settings.out_root)[0]
    assert home["overlays_hidden"] == 1      # 스크림만 숨김, 불투명 헤더는 그대로
    b = next(b for b in home["banners"] if b["href_domain"] == "toto-overlay.com")
    r, g, bl = _mean(settings.out_root / b["path"])
    assert r > 180 and g < 70 and bl < 70    # banner1.png = (220,30,30)


async def test_overlay_untouched_for_other_labels(site, tmp_path):
    settings = fast_settings(tmp_path)
    await run_capture(settings, [Seed(url=site + "/overlay.html", source="test", added_at="2026-10-28")], label="gambling")
    assert index_rows(settings.out_root)[0]["overlays_hidden"] is None
