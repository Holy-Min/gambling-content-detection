from crawler.__main__ import build_parser


def test_capture_args():
    ns = build_parser().parse_args(["capture", "--label", "gambling", "--seeds", "seeds/gambling.csv", "--per-domain", "3", "--emit-candidates"])
    assert ns.command == "capture" and ns.label == "gambling" and ns.per_domain == 3 and ns.emit_candidates is True


def test_discover_subcommands():
    ns = build_parser().parse_args(["discover", "search", "--per-keyword", "5"])
    assert ns.command == "discover" and ns.kind == "search" and ns.per_keyword == 5
    ns2 = build_parser().parse_args(["discover", "community"])
    assert ns2.kind == "community"


def test_stats_default_out_is_none():
    assert build_parser().parse_args(["stats"]).out is None
