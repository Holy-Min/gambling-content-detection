from pathlib import Path

import pytest

from crawler.config import CANDIDATE_LABEL, DEFAULT_OUT, LABELS, Settings, load_settings, read_env_file


def test_read_env_file_parses_key_values_and_ignores_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nCRAWLER_SALT=abc def\nCRAWLER_OUT=/tmp/x\n\nBAD LINE\n", encoding="utf-8")
    assert read_env_file(p) == {"CRAWLER_SALT": "abc def", "CRAWLER_OUT": "/tmp/x"}


def test_load_settings_requires_salt(tmp_path):
    with pytest.raises(SystemExit) as e:
        load_settings(env={}, env_file=tmp_path / "none")
    assert e.value.code == 2


def test_load_settings_precedence_cli_over_env_over_default(tmp_path):
    envf = tmp_path / ".env"; envf.write_text("CRAWLER_SALT=s\nCRAWLER_OUT=/from/envfile\n", encoding="utf-8")
    s = load_settings(env={}, env_file=envf)
    assert s.out_root == Path("/from/envfile") and s.salt == "s"
    s2 = load_settings(env={"CRAWLER_OUT": "/from/env", "CRAWLER_SALT": "s"}, env_file=tmp_path / "none")
    assert s2.out_root == Path("/from/env")
    s3 = load_settings(out="/from/cli", env={"CRAWLER_SALT": "s"}, env_file=tmp_path / "none", per_domain=2)
    assert s3.out_root == Path("/from/cli") and s3.per_domain == 2
    s4 = load_settings(env={"CRAWLER_SALT": "s"}, env_file=tmp_path / "none")
    assert s4.out_root == DEFAULT_OUT


def test_defaults_match_spec():
    s = Settings(out_root=Path("/x"), salt="s")
    assert (s.per_domain, s.max_domains, s.concurrency, s.page_timeout_ms, s.settle_ms, s.max_page_height) == (4, 300, 3, 20000, 1500, 15000)
    assert s.delays == {"gambling": 3.0, "embedded_banner": 3.0, "hard_negative": 5.0, "normal": 5.0, "candidate": 5.0}
    assert s.robots_labels == frozenset({"hard_negative", "normal", "candidate"}) and s.device == "Pixel 7"
    assert (s.recapture_days, s.skip_blocked_days) == (7, 7)
    assert (s.nightly_search_auto, s.nightly_max_candidates, s.nightly_candidate_pages, s.nightly_max_auto_communities) == (5, 40, 2, 5)
    assert (s.auto_keyword_pool, s.auto_keyword_add_per_day, s.auto_keyword_retire_streak) == (30, 5, 3)
    assert s.nightly_budget_min == {"search": 12, "community": 8, "explore": 25, "capture": 40}


def test_review_root_defaults_under_out_root():
    s = Settings(out_root=Path("/x"), salt="s")
    assert s.review_root == Path("/x/_review")
    assert CANDIDATE_LABEL == "candidate" and CANDIDATE_LABEL not in LABELS


def test_review_root_from_env_and_override(tmp_path):
    s = load_settings(out=str(tmp_path), env={"CRAWLER_SALT": "s", "CRAWLER_REVIEW": "/r/from/env"}, env_file=tmp_path / "none")
    assert s.review_root == Path("/r/from/env")
    s2 = load_settings(out=str(tmp_path), env={"CRAWLER_SALT": "s", "CRAWLER_REVIEW": "/r/from/env"}, env_file=tmp_path / "none",
                       review_root=Path("/r/cli"))
    assert s2.review_root == Path("/r/cli")


def test_default_out_moved_to_datasets():
    assert DEFAULT_OUT == Path("/Users/seongmin/datasets/gambling")
