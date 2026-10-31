"""Text reports for the CLI.

Every renderer takes plain data and a ``colour`` flag, so the same code path
produces the screenshot and the test assertions.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter

from .classify import THEME_LABELS, classify
from .history import Commit, History
from .metrics import (
    bus_factor,
    cochange,
    findings,
    hotspots,
    monthly,
    refactor_ratio,
    size_distribution,
)
from .onboard import OnboardEntry
from .render import THEME_COLORS, bar, colorize, sparkline, table

SEVERITY_COLOR = {"critical": "red", "high": "yellow", "medium": "cyan", "info": "grey"}
QUADRANT_COLOR = {"danger": "red", "churny": "yellow", "fragile": "blue", "stable": "grey"}


def _c(text: str, *styles: str, color: bool) -> str:
    return colorize(text, *styles, enabled=color)


def _fmt_date(ts: int) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%d")


def _theme_chip(theme: str, color: bool) -> str:
    label = THEME_LABELS.get(theme, theme).ljust(8)
    return _c(f" {label}", THEME_COLORS.get(theme, "grey"), color=color)


def header(history: History, color: bool = True) -> str:
    span = history.span
    authors = len(history.authors)
    span_text = f"{span[0].isoformat()} to {span[1].isoformat()}" if span else "no commits"
    lines = [
        _c(f"{history.name}", "bold", "white", color=color)
        + _c("  engineering history", "grey", color=color),
        _c(
            f"{len(history.commits):,} commits | {authors} authors | "
            f"{len(history.tags)} tags | {span_text}",
            "grey",
            color=color,
        ),
    ]
    return "\n".join(lines)


def chronicle(
    history: History,
    color: bool = True,
    per_month: int = 4,
    include_merges: bool = False,
) -> str:
    """A month-by-month timeline with auto-classified themes."""
    months = monthly(history)
    if not months:
        return "no commits in range\n"
    by_month: dict[str, list[Commit]] = {}
    for commit in history.commits:
        by_month.setdefault(commit.month, []).append(commit)

    out: list[str] = [header(history, color), ""]
    peak = max(m.commits for m in months)
    for point in reversed(months):
        commits = by_month.get(point.month, [])
        if not include_merges:
            commits = [c for c in commits if not c.is_merge]
        counts: Counter[str] = Counter(classify(c).theme for c in commits)
        chips = " ".join(
            _theme_chip(theme, color) + _c(f"{count:>3}", "grey", color=color)
            for theme, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        label = _dt.datetime.strptime(point.month + "-01", "%Y-%m-%d").strftime("%b %Y")
        out.append(
            _c(label[:8].ljust(8), "bold", color=color)
            + _c(f"{point.commits:>4} commits  ", "white", color=color)
            + _c(bar(point.commits, peak, 18), "cyan", color=color)
            + _c(
                f"  {point.authors} authors  +{point.insertions}/-{point.deletions}",
                "grey",
                color=color,
            )
        )
        out.append("          " + chips)
        for commit in commits[:per_month]:
            info = classify(commit)
            out.append(
                "          "
                + _c(commit.sha[:7], "grey", color=color)
                + " "
                + _theme_chip(info.theme, color)
                + " "
                + _c(commit.subject[:78], color=color)
            )
        hidden = len(commits) - per_month
        if hidden > 0:
            out.append(_c(f"          ... {hidden} more", "grey", color=color))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def summary(history: History, color: bool = True) -> str:
    """One-screen overview: findings, theme mix, size mix, cadence."""
    out = [header(history, color), ""]
    out.append(_c("Findings", "bold", color=color))
    for finding in findings(history):
        marker = _c("!", SEVERITY_COLOR.get(finding.severity, "grey"), color=color)
        out.append(f"  {marker} {finding.headline}")
        out.append(_c(f"    {finding.detail}", "grey", color=color))
    out.append("")

    months = monthly(history)
    counts: Counter[str] = Counter()
    for commit in history.commits:
        counts[classify(commit).theme] += 1
    total = sum(counts.values()) or 1
    out.append(_c("Theme mix", "bold", color=color))
    rows = [
        [theme, str(count), f"{count / total:.0%}", bar(count, max(counts.values()), 24)]
        for theme, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    out.append(table(["theme", "commits", "share", ""], rows, ["left", "right", "right", "left"]))
    out.append("")

    out.append(_c("Commit size", "bold", color=color))
    dist = size_distribution(history)
    out.append(
        "  "
        + "  ".join(f"{d.bucket}:{d.count}" for d in dist)
        + _c("   (lines changed per commit: XS<10 ... XL>=1000)", "grey", color=color)
    )
    out.append("")
    out.append(_c("Commits per month", "bold", color=color))
    out.append("  " + _c(sparkline([m.commits for m in months]), "cyan", color=color)
               + _c(
                   f"  peak {max((m.commits for m in months), default=0)}/month",
                   "grey",
                   color=color,
               ))
    return "\n".join(out) + "\n"


def bus_factor_report(history: History, color: bool = True, top: int = 15,
                      threshold: float = 0.5) -> str:
    rows = bus_factor(history, top=top, threshold=threshold)
    out = [header(history, color), ""]
    out.append(
        _c("Bus factor by directory", "bold", color=color)
        + _c(f"  (fewest people owning {threshold:.0%} of the commits)", "grey", color=color)
    )
    out.append("")
    if not rows:
        return "\n".join(out) + "no directories to analyse\n"
    body = [
        [
            row.directory,
            str(row.commits),
            str(row.authors),
            (str(row.bus_factor) if row.bus_factor > 1
             else _c("1", "red", "bold", color=color)),
            row.top_author,
            f"{row.top_share:.0%}",
            row.risk,
        ]
        for row in rows
    ]
    out.append(
        table(
            ["directory", "commits", "authors", "bus", "top author", "share", "risk"],
            body,
            ["left", "right", "right", "right", "left", "right", "left"],
            max_width=40,
        )
    )
    critical = [r for r in rows if r.risk == "critical" and r.directory != "."]
    out.append("")
    if critical:
        out.append(
            _c(
                f"!! {len(critical)} director{'y' if len(critical) == 1 else 'ies'}"
                " would be orphaned "
                "if one person left.",
                "red",
                color=color,
            )
        )
    else:
        out.append(_c("No directory is owned by a single person.", "green", color=color))
    return "\n".join(out) + "\n"


def hotspots_report(history: History, sources: dict[str, str] | None = None,
                    color: bool = True, top: int = 15, min_commits: int = 2) -> str:
    spots = hotspots(history, sources=sources, top=top, min_commits=min_commits)
    out = [header(history, color), ""]
    out.append(
        _c("Hotspots", "bold", color=color)
        + _c(
            "  (churn x complexity proxy; danger = high churn AND high complexity)",
            "grey",
            color=color,
        )
    )
    out.append("")
    if not spots:
        return "\n".join(out) + "no file was changed often enough to rank\n"
    body = [
        [
            spot.path,
            str(spot.commits),
            str(spot.authors),
            f"+{spot.insertions}/-{spot.deletions}",
            str(spot.lines),
            str(spot.complexity),
            _c(spot.quadrant, QUADRANT_COLOR.get(spot.quadrant, "grey"), color=color),
        ]
        for spot in spots
    ]
    out.append(
        table(
            ["file", "commits", "authors", "churn", "lines", "cx", "quadrant"],
            body,
            ["left", "right", "right", "right", "right", "right", "left"],
            max_width=56,
        )
    )
    danger = [s for s in spots if s.quadrant == "danger"]
    if danger:
        out.append("")
        out.append(_c("Danger quadrant:", "bold", "red", color=color)
                   + _c(" " + ", ".join(s.path for s in danger[:5]), color=color))
    return "\n".join(out) + "\n"


def coupling_report(history: History, color: bool = True, top: int = 15,
                    min_together: int = 3, min_confidence: float = 0.3) -> str:
    pairs = cochange(history, top=top, min_together=min_together,
                    min_confidence=min_confidence)
    out = [header(history, color), ""]
    out.append(
        _c("Co-change coupling", "bold", color=color)
        + _c("  (files that keep landing in the same commit)", "grey", color=color)
    )
    out.append("")
    if not pairs:
        return "\n".join(out) + "no repeated file pairs found (try --min-together 2)\n"
    body = [
        [
            pair.left,
            pair.right,
            str(pair.together),
            f"{pair.confidence:.0%}",
            f"{pair.support:.1%}",
            f"{pair.lift:.2f}",
        ]
        for pair in pairs
    ]
    out.append(
        table(
            ["file", "changes with", "times", "confidence", "support", "lift"],
            body,
            ["left", "left", "right", "right", "right", "right"],
            max_width=48,
        )
    )
    out.append("")
    out.append(
        _c(
            "High confidence + low support = a private contract between two files.",
            "grey",
            color=color,
        )
    )
    return "\n".join(out) + "\n"


def onboard_report(history: History, entries: list[OnboardEntry],
                   color: bool = True) -> str:
    out = [header(history, color), ""]
    out.append(
        _c("Read these first", "bold", color=color)
        + _c("  (reverse imports + churn + co-change centrality)", "grey", color=color)
    )
    out.append("")
    if not entries:
        return "\n".join(out) + "no source files found at HEAD\n"
    body = [
        [
            f"{entry.rank}.",
            entry.path,
            str(entry.importers),
            str(entry.commits),
            str(entry.authors),
            ", ".join(entry.reasons) or "-",
        ]
        for entry in entries
    ]
    out.append(
        table(
            ["#", "file", "imported by", "commits", "authors", "why"],
            body,
            ["right", "left", "right", "right", "right", "left"],
            max_width=46,
        )
    )
    out.append("")
    total_minutes = sum(entry.read_minutes for entry in entries)
    out.append(_c(f"Estimated deep-read time: about {total_minutes} minutes.", "grey", color=color))
    return "\n".join(out) + "\n"


def refactor_table(history: History, color: bool = True) -> str:
    rows = refactor_ratio(history)
    out = [_c("Refactor vs feature, per month", "bold", color=color), ""]
    body = [
        [row.month, str(row.feature), str(row.refactor), f"{row.ratio:.0%}"]
        for row in rows
        if row.total
    ]
    if not body:
        return "\n".join(out) + "not enough classified commits\n"
    out.append(table(["month", "feature", "refactor", "refactor share"], body,
                     ["left", "right", "right", "right"]))
    return "\n".join(out) + "\n"
