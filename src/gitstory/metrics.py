"""The analyses: bus factor, hotspots, co-change, churn, onboarding.

Each function is pure over a :class:`History` (plus, where noted, the file
contents at HEAD) so it can be unit-tested without a repository on disk.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from .classify import classify, size_bucket
from .history import History


# --------------------------------------------------------------------- helpers
def directory_of(path: str) -> str:
    """Top-level directory of a path, or '.' for repository root files."""
    head, _, _ = path.partition("/")
    return head if _ else "."


def _bus_factor_from_counts(counts: Counter[str], threshold: float = 0.5) -> tuple[int, float]:
    """Minimum number of authors needed to own *threshold* of the work."""
    total = sum(counts.values())
    if total == 0:
        return 0, 0.0
    ranked = sorted(counts.values(), reverse=True)
    running = 0
    for i, value in enumerate(ranked, 1):
        running += value
        if running / total >= threshold:
            return i, ranked[0] / total
    return len(ranked), ranked[0] / total


# ------------------------------------------------------------------ bus factor
@dataclass(frozen=True)
class BusFactorRow:
    """How concentrated one directory's history is."""

    directory: str
    commits: int
    authors: int
    bus_factor: int
    top_author: str
    top_share: float
    top_commits: int

    @property
    def risk(self) -> str:
        if self.commits < 5:
            return "low"
        if self.bus_factor <= 1:
            return "critical"
        if self.bus_factor <= 2:
            return "high"
        return "ok"


def bus_factor(history: History, top: int = 15, threshold: float = 0.5) -> list[BusFactorRow]:
    """Bus factor per top-level directory, worst first.

    Bus factor is the smallest set of people whose departure would leave less
    than *threshold* (default 50%) of a directory's commits unattributable.
    """
    per_dir: dict[str, Counter[str]] = defaultdict(Counter)
    for commit in history.commits:
        dirs = {directory_of(f.path) for f in commit.files if f.path}
        for directory in dirs:
            per_dir[directory][commit.author] += 1

    rows: list[BusFactorRow] = []
    for directory, counts in per_dir.items():
        authors = len(counts)
        bf, top_share = _bus_factor_from_counts(counts, threshold)
        top_author, top_commits = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        rows.append(
            BusFactorRow(
                directory=directory,
                commits=sum(counts.values()),
                authors=authors,
                bus_factor=bf,
                top_author=top_author,
                top_share=top_share,
                top_commits=top_commits,
            )
        )
    rows.sort(key=lambda r: (r.bus_factor, -r.top_share, -r.commits, r.directory))
    return rows[:top]


@dataclass(frozen=True)
class ConcentrationPoint:
    """Knowledge concentration over time, in 10-bin buckets of history."""

    index: int
    label: str
    hhi: float
    top_share: float
    authors: int
    commits: int


def knowledge_concentration(history: History, bins: int = 10) -> list[ConcentrationPoint]:
    """Herfindahl-Hirschman index of author share, bucketed over time.

    HHI = sum(share_i ** 2). 1.0 means one person wrote everything; values near
    1/n mean evenly spread knowledge. Buckets are equal-width in *commits*, not
    in calendar time, so a quiet month cannot dominate.
    """
    commits = history.commits
    if not commits or bins <= 0:
        return []
    bins = max(1, min(bins, len(commits)))
    size = math.ceil(len(commits) / bins)
    points: list[ConcentrationPoint] = []
    for i in range(bins):
        chunk = commits[i * size : (i + 1) * size]
        if not chunk:
            break
        counts = Counter(c.author for c in chunk)
        total = sum(counts.values())
        hhi = sum((v / total) ** 2 for v in counts.values())
        points.append(
            ConcentrationPoint(
                index=i,
                label=f"{chunk[0].month} to {chunk[-1].month}",
                hhi=round(hhi, 4),
                top_share=round(max(counts.values()) / total, 4),
                authors=len(counts),
                commits=total,
            )
        )
    return points


# -------------------------------------------------------------------- hotspots
@dataclass(frozen=True)
class Hotspot:
    """One file placed in the churn x complexity quadrant."""

    path: str
    commits: int
    authors: int
    insertions: int
    deletions: int
    lines: int
    complexity: int
    churn_score: float
    complexity_score: float
    quadrant: str

    @property
    def total_churn(self) -> int:
        return self.insertions + self.deletions


BRANCH_TOKENS = ("if ", "elif ", "for ", "while ", "case ", "catch", "except", "&&", "||", "? ")


def _complexity_proxy(source: str) -> int:
    """Cheap language-agnostic complexity: branchy lines + nesting depth.

    This is deliberately a proxy, not a real cyclomatic number: it must work
    for Python, JS, Go and Rust without a parser per language. It correlates
    well enough to rank files for a human to look at.
    """
    if not source:
        return 1
    branchy = 0
    depth = 0
    max_depth = 0
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//", "*")):
            continue
        low = line.lower()
        for token in BRANCH_TOKENS:
            if token in low:
                branchy += 1
                break
        indent = len(raw) - len(raw.lstrip(" \t"))
        depth = indent // 4
        max_depth = max(max_depth, depth)
    return max(1, branchy + max_depth)


def hotspots(
    history: History,
    sources: dict[str, str] | None = None,
    top: int = 15,
    min_commits: int = 2,
) -> list[Hotspot]:
    """Rank files by churn and place them in four quadrants.

    x = churn rank, y = complexity rank (branchiness + nesting depth), both
    normalised to [0, 1]. The interesting quadrant is "danger": high churn and
    high complexity, i.e. the file that changes constantly and is hard to read.
    """
    churn = history.file_churn()
    authors = history.file_authors()
    if not churn:
        return []
    rows: list[Hotspot] = []
    for path, (ins, dels, commits) in churn.items():
        if commits < min_commits:
            continue
        info = authors.get(path, {})
        key = path
        if sources is not None:
            key = next((p for p in sources if p == path), path)
            if key not in sources:
                key = path if path in sources else ""
        source = sources.get(key, "") if sources else ""
        lines = source.count("\n") + 1 if source else 0
        complexity = _complexity_proxy(source)
        rows.append(
            Hotspot(
                path=path,
                commits=commits,
                authors=len(info),
                insertions=ins,
                deletions=dels,
                lines=lines,
                complexity=complexity,
                churn_score=0.0,
                complexity_score=0.0,
                quadrant="",
            )
        )
    if not rows:
        return []
    # Both axes are percentile ranks, not fractions of the maximum: churn spans
    # orders of magnitude, so a max-relative score would squash every file but
    # the worst one onto the origin and call it "stable". A rank split at the
    # median is what makes the four quadrants mean "top half / bottom half".
    churn_rank = _percentiles({r.path: r.total_churn for r in rows})
    complex_rank = _percentiles({r.path: r.complexity for r in rows})
    scored: list[Hotspot] = []
    for r in rows:
        cx = churn_rank[r.path]
        cy = complex_rank[r.path]
        if cx >= HOTSPOT_HIGH and cy >= HOTSPOT_HIGH:
            quadrant = "danger"
        elif cx >= HOTSPOT_HIGH:
            quadrant = "churny"
        elif cy >= HOTSPOT_HIGH:
            quadrant = "fragile"
        else:
            quadrant = "stable"
        scored.append(
            Hotspot(
                path=r.path,
                commits=r.commits,
                authors=r.authors,
                insertions=r.insertions,
                deletions=r.deletions,
                lines=r.lines,
                complexity=r.complexity,
                churn_score=round(cx, 4),
                complexity_score=round(cy, 4),
                quadrant=quadrant,
            )
        )
    scored.sort(key=lambda r: (-(r.churn_score * 0.6 + r.complexity_score * 0.4), r.path))
    return scored[:top]


# A file is "high" on an axis when it is in the top third of the repository.
HOTSPOT_HIGH = 2 / 3


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Map each key to its percentile rank in [0, 1]; ties break on the key."""
    ordered = sorted(values.items(), key=lambda kv: (kv[1], kv[0]))
    count = len(ordered)
    if count == 1:
        return {ordered[0][0]: 1.0}
    return {key: index / (count - 1) for index, (key, _value) in enumerate(ordered)}


# -------------------------------------------------------------------- co-change
@dataclass(frozen=True)
class Coupling:
    """Two files that keep changing together."""

    left: str
    right: str
    together: int
    left_commits: int
    right_commits: int
    confidence: float
    support: float

    @property
    def lift(self) -> float:
        denom = self.left_commits * self.right_commits
        return (self.together * self.together * 1.0) / denom if denom else 0.0


def cochange(
    history: History,
    top: int = 15,
    min_together: int = 3,
    min_confidence: float = 0.3,
    max_files_per_commit: int = 30,
) -> list[Coupling]:
    """Rank file pairs by how often they are committed together.

    confidence = P(right | left) for the more frequent direction
    support    = together / total commits
    Pairs from giant commits are ignored: a 300-file release commit couples
    everything to everything and carries no signal.
    """
    file_commits = history.file_commits()
    total_commits = len(history.commits) or 1
    pair_counts: Counter[tuple[str, str]] = Counter()
    for commit in history.commits:
        paths = sorted({f.path for f in commit.files if f.path and not f.is_rename})
        if not paths or len(paths) > max_files_per_commit:
            continue
        for i, left in enumerate(paths):
            for right in paths[i + 1 :]:
                pair_counts[(left, right)] += 1

    rows: list[Coupling] = []
    for (left, right), together in pair_counts.items():
        if together < min_together:
            continue
        lc = file_commits.get(left, 0)
        rc = file_commits.get(right, 0)
        confidence = max(together / lc if lc else 0.0, together / rc if rc else 0.0)
        if confidence < min_confidence:
            continue
        rows.append(
            Coupling(
                left=left,
                right=right,
                together=together,
                left_commits=lc,
                right_commits=rc,
                confidence=round(confidence, 3),
                support=round(together / total_commits, 4),
            )
        )
    rows.sort(key=lambda r: (-r.confidence, -r.together, r.left, r.right))
    return rows[:top]


# --------------------------------------------------------------------- churn
@dataclass(frozen=True)
class MonthPoint:
    month: str
    commits: int
    insertions: int
    deletions: int
    feature: int = 0
    fix: int = 0
    refactor: int = 0
    other: int = 0
    authors: int = 0
    files_touched: int = 0


@dataclass(frozen=True)
class RefactorRatio:
    month: str
    refactor: int
    feature: int
    total: int
    ratio: float


def monthly(history: History) -> list[MonthPoint]:
    """Aggregate commits per calendar month, oldest first."""
    buckets: dict[str, dict[str, int]] = {}
    authors: dict[str, set[str]] = defaultdict(set)
    files: dict[str, set[str]] = defaultdict(set)
    for commit in history.commits:
        month = commit.month
        bucket = buckets.setdefault(
            month, {"commits": 0, "insertions": 0, "deletions": 0, "feature": 0, "fix": 0,
                    "refactor": 0, "other": 0}
        )
        bucket["commits"] += 1
        bucket["insertions"] += commit.insertions
        bucket["deletions"] += commit.deletions
        theme = classify(commit).theme
        if theme in ("feature",):
            bucket["feature"] += 1
        elif theme in ("fix",):
            bucket["fix"] += 1
        elif theme in ("refactor",):
            bucket["refactor"] += 1
        else:
            bucket["other"] += 1
        authors[month].add(commit.author)
        if commit.files:
            files[month].add(commit.files[0].path)
    points = [
        MonthPoint(
            month=month,
            commits=b["commits"],
            insertions=b["insertions"],
            deletions=b["deletions"],
            feature=b["feature"],
            fix=b["fix"],
            refactor=b["refactor"],
            other=b["other"],
            authors=len(authors[month]),
            files_touched=len(files[month]),
        )
        for month, b in buckets.items()
    ]
    points.sort(key=lambda p: p.month)
    return points


def refactor_ratio(history: History) -> list[RefactorRatio]:
    """Share of feature-or-refactor commits that are refactors, per month."""
    rows: list[RefactorRatio] = []
    for point in monthly(history):
        total = point.feature + point.refactor
        ratio = point.refactor / total if total else 0.0
        rows.append(
            RefactorRatio(
                month=point.month,
                refactor=point.refactor,
                feature=point.feature,
                total=total,
                ratio=round(ratio, 4),
            )
        )
    return rows


@dataclass(frozen=True)
class SizeDistribution:
    bucket: str
    count: int
    share: float


def size_distribution(history: History) -> list[SizeDistribution]:
    buckets = Counter(size_bucket(c.churn) for c in history.commits)
    total = sum(buckets.values()) or 1
    order = ["XS", "S", "M", "L", "XL"]
    return [
        SizeDistribution(
            bucket=b,
            count=buckets.get(b, 0),
            share=round(buckets.get(b, 0) / total, 4),
        )
        for b in order
    ]


@dataclass(frozen=True)
class HaveFunFinding:
    """A one-line, falsifiable observation about the repository."""

    key: str
    headline: str
    detail: str
    severity: str


def findings(history: History) -> list[HaveFunFinding]:
    """High-signal observations, ordered by severity then key."""
    out: list[HaveFunFinding] = []
    total = len(history.commits) or 1
    authors = Counter(c.author for c in history.commits)
    if not authors:
        return out
    top_author, top_count = sorted(authors.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    share = top_count / total
    if len(authors) > 1 and share >= 0.5:
        out.append(
            HaveFunFinding(
                "author-share",
                f"{top_author} wrote {share:.0%} of all commits",
                f"{top_count} of {total} commits; {len(authors)} authors total",
                "critical" if share >= 0.7 else "high",
            )
        )
    bf = bus_factor(history, top=50)
    critical = [r for r in bf if r.risk == "critical" and r.directory != "."]
    if critical:
        names = ", ".join(r.directory for r in critical[:3])
        noun = "directory has" if len(critical) == 1 else "directories have"
        out.append(
            HaveFunFinding(
                "bus-factor",
                f"{len(critical)} {noun} a bus factor of 1",
                f"worst: {names}",
                "critical",
            )
        )
    spots = [h for h in hotspots(history, top=50) if h.quadrant == "danger"]
    if spots:
        top_spot = spots[0]
        out.append(
            HaveFunFinding(
                "hotspot",
                f"{top_spot.path} is in the danger quadrant",
                f"{top_spot.commits} commits by {top_spot.authors} authors, "
                f"{top_spot.total_churn} lines churned",
                "high",
            )
        )
    pairs = cochange(history, top=3, min_together=4, min_confidence=0.5)
    if pairs:
        pair = pairs[0]
        out.append(
            HaveFunFinding(
                "coupling",
                f"{pair.left} changes with {pair.right} {pair.confidence:.0%} of the time",
                f"{pair.together} shared commits, support {pair.support:.1%}, lift {pair.lift:.2f}",
                "medium",
            )
        )
    dist = size_distribution(history)
    huge = next((b for b in dist if b.bucket == "XL"), None)
    if huge and huge.count:
        out.append(
            HaveFunFinding(
                "commit-size",
                f"{huge.count} commits change more than 1000 lines",
                f"{huge.share:.0%} of history is in XL commits",
                "high",
            )
        )
    merges = history.merges()
    if merges:
        untyped = sum(1 for m in merges if "reviewed-by:" not in (m.subject + m.body).lower())
        out.append(
            HaveFunFinding(
                "merges",
                f"{untyped}/{len(merges)} merge commits carry no reviewed-by trailer",
                "an upper bound on unreviewed merges; git has no approval record",
                "medium",
            )
        )
    tags = sorted(history.tags, key=lambda t: (t.timestamp, t.version_key))
    if len(tags) >= 2:
        pairs = zip(tags, tags[1:], strict=False)
        gaps = sorted((b.timestamp - a.timestamp) / 86400 for a, b in pairs)
        median = gaps[len(gaps) // 2]
        out.append(
            HaveFunFinding(
                "release-cadence",
                f"a tag lands every {median:.0f} days (median gap)",
                f"{len(tags)} tags from {tags[0].name} to {tags[-1].name}",
                "info",
            )
        )
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    out.sort(key=lambda f: (order.get(f.severity, 9), f.key))
    return out
