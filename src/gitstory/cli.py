"""Command line interface for git-story.

Exit codes: 0 success, 1 findings/quality gate failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .classify import classify
from .gitio import GitError
from .history import History, scan
from .html import StoryOptions, render_story
from .metrics import (
    bus_factor,
    cochange,
    findings,
    hotspots,
    knowledge_concentration,
    monthly,
    refactor_ratio,
    size_distribution,
)
from .onboard import onboard, read_head_files
from .render import supports_color
from .reports import (
    bus_factor_report,
    chronicle,
    coupling_report,
    hotspots_report,
    onboard_report,
    refactor_table,
    summary,
)

EPILOG = """examples:
  git-story chronicle --since 1y
  git-story hotspots --top 10
  git-story bus-factor src/
  git-story onboard
  git-story story --format html --out story.html
"""


GLOBAL_DEFAULTS = {
    "repo": ".",
    "color": "auto",
    "json": False,
    "since": None,
    "until": None,
    "no_merges": False,
    "max_commits": 20_000,
    "fail_on": None,
    "threshold": 0.5,
}


def _global_options() -> argparse.ArgumentParser:
    """Options accepted before *and* after the subcommand.

    Defaults are suppressed so the subparser copy cannot clobber a value that
    was already given before the subcommand; :func:`apply_defaults` fills in
    the missing ones afterwards.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", "--repo", default=argparse.SUPPRESS,
                        help="path inside the repository (default: .)")
    common.add_argument("--version", action="version", version=f"git-story {__version__}")
    common.add_argument("--color", choices=("auto", "always", "never"),
                        default=argparse.SUPPRESS,
                        help="colourise terminal output (default: auto)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable JSON instead of text")
    common.add_argument("--since", default=argparse.SUPPRESS,
                        help="limit history: 1y, 6m, 2w, 30d or 2024-01-01")
    common.add_argument("--until", default=argparse.SUPPRESS,
                        help="upper bound for the same formats as --since")
    common.add_argument("--no-merges", action="store_true", default=argparse.SUPPRESS,
                        help="exclude merge commits from the analysis")
    common.add_argument("--max-commits", type=int, default=argparse.SUPPRESS,
                        help="hard cap on commits read (default: 20000)")
    common.add_argument("--fail-on", choices=("bus-factor", "hotspot", "unreviewed"),
                        default=argparse.SUPPRESS,
                        help="exit 1 when the named quality signal is tripped")
    common.add_argument("--threshold", type=float, default=argparse.SUPPRESS,
                        help="bus-factor ownership threshold (default 0.5)")
    return common


def apply_defaults(args: argparse.Namespace) -> argparse.Namespace:
    for key, value in GLOBAL_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    return args


def build_parser() -> argparse.ArgumentParser:
    common = _global_options()
    parser = argparse.ArgumentParser(
        prog="git-story",
        description="Read a git history as an engineering narrative.",
        epilog=EPILOG,
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def child(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    p_sum = child("summary", "one-screen overview with findings")
    p_sum.add_argument("path", nargs="?", default=None, help="repository path")

    p_chr = child("chronicle", "month-by-month timeline with themes")
    p_chr.add_argument("path", nargs="?", default=None)
    p_chr.add_argument(
        "--per-month", type=int, default=4, help="commits listed per month (default 4)"
    )
    p_chr.add_argument("--with-merges", action="store_true", help="also list merge commits")

    p_bus = child("bus-factor", "knowledge concentration per directory")
    p_bus.add_argument("path", nargs="?", default=None)
    p_bus.add_argument("--top", type=int, default=15)

    p_hot = child("hotspots", "churn x complexity quadrants")
    p_hot.add_argument("path", nargs="?", default=None)
    p_hot.add_argument("--top", type=int, default=15)
    p_hot.add_argument("--min-commits", type=int, default=2)

    p_coup = child("coupling", "files that change together")
    p_coup.add_argument("path", nargs="?", default=None)
    p_coup.add_argument("--top", type=int, default=15)
    p_coup.add_argument("--min-together", type=int, default=3)
    p_coup.add_argument("--min-confidence", type=float, default=0.3)

    p_onb = child("onboard", "the files a newcomer should read first")
    p_onb.add_argument("path", nargs="?", default=None)
    p_onb.add_argument("--top", type=int, default=10)
    p_onb.add_argument("--with-tests", action="store_true", help="include test files")

    p_story = child("story", "render the narrative page")
    p_story.add_argument("path", nargs="?", default=None)
    p_story.add_argument("--format", choices=("html", "text", "json"), default="text")
    p_story.add_argument("--out", default=None, help="write to a file instead of stdout")
    p_story.add_argument("--title", default=None)
    p_story.add_argument("--max-months", type=int, default=24)

    p_ref = child("refactor", "refactor vs feature split per month")
    p_ref.add_argument("path", nargs="?", default=None)
    return parser


def _use_color(args, stream) -> bool:
    if args.color == "always":
        return True
    if args.color == "never":
        return False
    return supports_color(stream)


def _payload(history: History, command: str, args) -> dict:
    """The JSON representation shared by --json and story --format json."""
    months = monthly(history)
    authors: dict[str, int] = {}
    for commit in history.commits:
        authors[commit.author] = authors.get(commit.author, 0) + 1
    base = {
        "repo": history.name,
        "root": str(history.repo.root),
        "commits": len(history.commits),
        "authors": dict(sorted(authors.items(), key=lambda kv: (-kv[1], kv[0]))),
        "tags": [t.name for t in history.tags],
        "first": history.first_commit.date.isoformat() if history.first_commit else None,
        "last": history.last_commit.date.isoformat() if history.last_commit else None,
    }
    if command == "chronicle":
        base["months"] = [
            {
                "month": m.month,
                "commits": m.commits,
                "insertions": m.insertions,
                "deletions": m.deletions,
                "authors": m.authors,
                "themes": {"feature": m.feature, "fix": m.fix, "refactor": m.refactor,
                           "other": m.other},
            }
            for m in months
        ]
    elif command == "bus-factor":
        base["directories"] = [
            {
                "directory": r.directory,
                "commits": r.commits,
                "authors": r.authors,
                "bus_factor": r.bus_factor,
                "top_author": r.top_author,
                "top_share": r.top_share,
                "risk": r.risk,
            }
            for r in bus_factor(history, top=args.top, threshold=args.threshold)
        ]
    elif command == "hotspots":
        sources = read_head_files(history)
        base["files"] = [
            {
                "path": h.path,
                "commits": h.commits,
                "authors": h.authors,
                "insertions": h.insertions,
                "deletions": h.deletions,
                "lines": h.lines,
                "complexity": h.complexity,
                "churn_score": h.churn_score,
                "complexity_score": h.complexity_score,
                "quadrant": h.quadrant,
            }
            for h in hotspots(history, sources=sources, top=args.top, min_commits=args.min_commits)
        ]
    elif command == "coupling":
        base["pairs"] = [
            {
                "left": p.left,
                "right": p.right,
                "together": p.together,
                "confidence": p.confidence,
                "support": p.support,
                "lift": round(p.lift, 3),
            }
            for p in cochange(history, top=args.top, min_together=args.min_together,
                              min_confidence=args.min_confidence)
        ]
    elif command == "onboard":
        sources = read_head_files(history)
        base["reads"] = [
            {
                "rank": e.rank,
                "path": e.path,
                "score": e.score,
                "importers": e.importers,
                "commits": e.commits,
                "authors": e.authors,
                "coupled_files": e.coupled_files,
                "reasons": list(e.reasons),
            }
            for e in onboard(history, sources=sources, top=args.top,
                             include_tests=args.with_tests)
        ]
    elif command == "refactor":
        base["ratios"] = [
            {"month": r.month, "feature": r.feature, "refactor": r.refactor,
             "total": r.total, "ratio": r.ratio}
            for r in refactor_ratio(history)
        ]
    elif command == "summary":
        base["findings"] = [
            {"key": f.key, "headline": f.headline, "detail": f.detail, "severity": f.severity}
            for f in findings(history)
        ]
        base["themes"] = _theme_counts(history)
        base["sizes"] = [{"bucket": s.bucket, "count": s.count, "share": s.share}
                        for s in size_distribution(history)]
        base["concentration"] = [
            {"label": p.label, "hhi": p.hhi, "top_share": p.top_share, "authors": p.authors}
            for p in knowledge_concentration(history)
        ]
    elif command == "story":
        base["months"] = [
            {"month": m.month, "commits": m.commits, "insertions": m.insertions,
             "deletions": m.deletions}
            for m in months
        ]
        base["findings"] = [
            {"key": f.key, "headline": f.headline, "severity": f.severity}
            for f in findings(history)
        ]
    return base


def _theme_counts(history: History) -> dict[str, int]:
    counts: dict[str, int] = {}
    for commit in history.commits:
        theme = classify(commit).theme
        counts[theme] = counts.get(theme, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _quality_gate(history: History, args) -> int:
    """Apply --fail-on and report what tripped."""
    if not args.fail_on:
        return 0
    if args.fail_on == "bus-factor":
        rows = bus_factor(history, top=100, threshold=args.threshold)
        critical = [r for r in rows if r.risk == "critical" and r.directory != "."]
        if critical:
            names = ", ".join(r.directory for r in critical[:5])
            sys.stderr.write(f"git-story: quality gate failed: bus factor 1 in {names}\n")
            return 1
        return 0
    if args.fail_on == "hotspot":
        sources = read_head_files(history)
        danger = [h for h in hotspots(history, sources=sources, top=100)
                  if h.quadrant == "danger"]
        if danger:
            names = ", ".join(h.path for h in danger[:3])
            sys.stderr.write(
                f"git-story: quality gate failed: {len(danger)} danger hotspots: {names}\n"
            )
            return 1
        return 0
    if args.fail_on == "unreviewed":
        merges = history.merges()
        unreviewed = [m for m in merges if "reviewed-by:" not in (m.subject + m.body).lower()]
        if unreviewed:
            sys.stderr.write(
                f"git-story: quality gate failed: {len(unreviewed)}/{len(merges)} merges "
                "have no reviewed-by trailer\n"
            )
            return 1
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = apply_defaults(parser.parse_args(argv))
    if not args.command:
        parser.print_help()
        return 2

    target = args.path or args.repo
    color = _use_color(args, sys.stdout)
    include_merges = not args.no_merges

    try:
        history = scan(
            target,
            since=args.since,
            until=args.until,
            include_merges=include_merges,
            max_commits=args.max_commits,
        )
    except GitError as exc:
        sys.stderr.write(f"git-story: {exc}\n")
        return 2

    if not history.commits:
        sys.stderr.write(
            "git-story: no commits matched the filters\n"
            "hint: widen --since or check that you are on a branch with history\n"
        )
        return 2

    command = args.command

    if command == "story" and args.format == "html":
        sources = read_head_files(history)
        page = render_story(
            history,
            StoryOptions(title=args.title, since=args.since, max_months=args.max_months),
            sources=sources,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(page, encoding="utf-8")
            sys.stderr.write(f"git-story: wrote {out} ({out.stat().st_size:,} bytes)\n")
        else:
            sys.stdout.write(page)
        return _quality_gate(history, args)

    if args.json or (command == "story" and args.format == "json"):
        payload = _payload(history, command, args)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return _quality_gate(history, args)

    if command == "summary":
        sys.stdout.write(summary(history, color))
    elif command == "chronicle":
        sys.stdout.write(chronicle(history, color, per_month=args.per_month,
                                   include_merges=args.with_merges))
    elif command == "bus-factor":
        sys.stdout.write(bus_factor_report(history, color, top=args.top, threshold=args.threshold))
    elif command == "hotspots":
        sources = read_head_files(history)
        sys.stdout.write(hotspots_report(history, sources, color, top=args.top,
                                         min_commits=args.min_commits))
    elif command == "coupling":
        sys.stdout.write(coupling_report(history, color, top=args.top,
                                        min_together=args.min_together,
                                        min_confidence=args.min_confidence))
    elif command == "onboard":
        sources = read_head_files(history)
        entries = onboard(history, sources=sources, top=args.top,
                          include_tests=args.with_tests)
        sys.stdout.write(onboard_report(history, entries, color))
    elif command == "refactor":
        sys.stdout.write(refactor_table(history, color))
    elif command == "story":
        sys.stdout.write(summary(history, color))
    else:  # pragma: no cover - argparse rejects unknown commands
        parser.error(f"unknown command {command}")
        return 2
    return _quality_gate(history, args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
