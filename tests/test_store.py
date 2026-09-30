from datetime import datetime, timedelta, timezone

from PIL import Image

from crawler.store import Store, ahash, hamming, ts_label

KST = timezone(timedelta(hours=9))


def meta(label="gambling", domain="a.com", status="ok", url="https://a.com/", phash="0" * 64, at=None):
    at = at or datetime(2026, 9, 30, 20, 0, tzinfo=KST)
    return {"id": f"x_{ts_label(at)}", "label": label, "domain": domain, "status": status, "url": url,
            "url_norm": url, "phash": phash, "captured_at": at.isoformat()}


def test_domain_dir_uses_salted_hash(tmp_path):
    s = Store(tmp_path, "salt")
    d = s.domain_dir("gambling", "a.com")
    assert d.parent.name == "gambling" and len(d.name) == 12 and d.name == s.hash_of("a.com")


def test_record_appends_to_meta_and_index_and_counts(tmp_path):
    s = Store(tmp_path, "salt")
    s.record(meta()); s.record(meta(status="blocked_kr", url="https://a.com/b"))
    assert (tmp_path / "index.jsonl").read_text().count("\n") == 2
    assert (s.domain_dir("gambling", "a.com") / "meta.jsonl").exists()
    assert s.ok_count("gambling", "a.com") == 1
    # 새 인스턴스가 디스크에서 다시 읽어도 같다
    assert Store(tmp_path, "salt").ok_count("gambling", "a.com") == 1


def test_seen_recently_window(tmp_path):
    s = Store(tmp_path, "salt")
    old = datetime(2026, 9, 1, tzinfo=KST); recent = datetime(2026, 9, 29, tzinfo=KST)
    s.record(meta(url="https://a.com/old", at=old)); s.record(meta(url="https://a.com/new", at=recent))
    now = datetime(2026, 9, 30, tzinfo=KST)
    assert s.seen_recently("https://a.com/new#frag", now=now)
    assert not s.seen_recently("https://a.com/old", now=now)
    assert not s.seen_recently("https://a.com/never", now=now)


def base_image():
    # 균일한 이미지는 average hash가 퇴화하므로 실제 화면처럼 구조가 있는 이미지를 쓴다
    im = Image.new("RGB", (400, 800), (255, 255, 255))
    for y in range(800):
        im.paste((y * 255 // 800, 120, 255 - y * 255 // 800), (0, y, 400, y + 1))
    im.paste((0, 0, 0), (40, 100, 360, 180))
    return im


def test_ahash_hamming_and_duplicate(tmp_path):
    p1, p2, p3 = tmp_path / "1.png", tmp_path / "2.png", tmp_path / "3.png"
    base_image().save(p1)
    im = base_image(); im.paste((255, 255, 255), (0, 0, 16, 16)); im.save(p2)  # 작은 변화(16×16) → 거의 같음
    Image.effect_noise((400, 800), 128).convert("RGB").save(p3)               # 전혀 다름
    h1, h2, h3 = ahash(p1), ahash(p2), ahash(p3)
    assert len(h1) == 64 and hamming(h1, h2) <= 5 < hamming(h1, h3)
    s = Store(tmp_path, "salt")
    s.record(meta(phash=h1))
    assert s.find_duplicate("gambling", "a.com", h2) == meta()["id"]
    assert s.find_duplicate("gambling", "a.com", h3) is None
    assert s.find_duplicate("normal", "a.com", h2) is None
