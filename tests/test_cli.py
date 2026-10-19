from crawler.__main__ import build_parser


def test_capture_args():
    ns = build_parser().parse_args(["capture", "--label", "gambling", "--seeds", "seeds/gambling.csv", "--per-domain", "3", "--emit-candidates"])
    assert ns.command == "capture" and ns.label == "gambling" and ns.per_domain == 3 and ns.emit_candidates is True
    assert ns.click_menus is False and ns.max_menu_clicks is None


def test_capture_click_menus_args():
    ns = build_parser().parse_args(["capture", "--label", "gambling", "--seeds", "s.csv", "--click-menus", "--max-menu-clicks", "3"])
    assert ns.click_menus is True and ns.max_menu_clicks == 3


def test_discover_subcommands():
    ns = build_parser().parse_args(["discover", "search", "--per-keyword", "5"])
    assert ns.command == "discover" and ns.kind == "search" and ns.per_keyword == 5
    ns2 = build_parser().parse_args(["discover", "community"])
    assert ns2.kind == "community"


def test_stats_default_out_is_none():
    assert build_parser().parse_args(["stats"]).out is None


def test_nightly_args_defaults():
    ns = build_parser().parse_args(["nightly"])
    assert ns.command == "nightly" and ns.date is None and ns.out_dir == "out" and ns.only is None and ns.skip is None
    assert ns.budget_min == 90 and ns.recapture_days == 1 and ns.max_candidates is None and ns.dry_run is False


def test_nightly_args_only_skip_lists():
    ns = build_parser().parse_args(["nightly", "--only", "search,explore", "--skip", "capture", "--budget-min", "30", "--date", "2026-10-20", "--dry-run"])
    assert ns.only == ["search", "explore"] and ns.skip == ["capture"] and ns.budget_min == 30 and ns.date == "2026-10-20" and ns.dry_run is True


def test_explore_and_promote_args():
    ns = build_parser().parse_args(["explore", "--max-candidates", "5", "--per-domain", "1"])
    assert ns.command == "explore" and ns.max_candidates == 5 and ns.per_domain == 1 and ns.out_dir == "out"
    ns2 = build_parser().parse_args(["promote", "out/2026-10-20/review.csv", "--dry-run"])
    assert ns2.command == "promote" and ns2.review_csv == "out/2026-10-20/review.csv" and ns2.dry_run is True


def test_stats_review_and_capture_recapture_days():
    assert build_parser().parse_args(["stats", "--review"]).review is True
    assert build_parser().parse_args(["stats"]).review is False
    assert build_parser().parse_args(["capture", "--label", "normal", "--seeds", "s.csv", "--recapture-days", "1"]).recapture_days == 1
    assert build_parser().parse_args(["capture", "--label", "normal", "--seeds", "s.csv"]).recapture_days is None
