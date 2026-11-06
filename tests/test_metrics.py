"""The analyses, tested on synthetic histories with known answers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gitstory.gitio import GitRepo
from gitstory.history import Commit, FileChange, History, Tag
from gitstory.metrics import (
    bus_factor,
    cochange,
    directory_of,
    findings,
    hotspots,
    knowledge_concentration,
    monthly,
    refactor_ratio,
    size_distribution,
)


class FakeRepo:
    name = "fake"

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {}
        self.root = None

    def run_text(self, *args, check=True):  # pragma: no cover - not used directly
        return ""

    def show_file(self, spec, limit=400_000):
        return self.files.get(spec.split(":", 1)[1])


def build(commits: list[Commit], tags: list[Tag] | None = None) -> History:
    return History(FakeRepo(), commits, tags or [])


def commit(index: int, author: str, files: list[str], subject: str = "feat: x",
           insertions: int = 5, deletions: int = 0) -> Commit:
    return Commit(
        sha=f"{index:040d}",
        parents=("a",),
        author=author,
        email=author.lower() + "@example.com",
        timestamp=1_700_000_000 + index * 86_400,
        subject=subject,
        body="",
        files=[FileChange(path, None, insertions, deletions) for path in files],
    )


def test_directory_of_root_and_nested():
    assert directory_of("README.md") == "."
    assert directory_of("src/a.py") == "src"
    assert directory_of("src/deep/a.py") == "src"


def test_bus_factor_single_owner_is_critical():
    commits = [commit(i, "Ada", ["app/main.py"]) for i in range(6)]
    rows = bus_factor(build(commits))
    assert rows[0].directory == "app"
    assert rows[0].bus_factor == 1
    assert rows[0].risk == "critical"
    assert rows[0].top_share == 1.0


def test_bus_factor_spreads_with_more_authors():
    commits = [commit(i, name, ["app/main.py"]) for i, name in enumerate(["A", "B", "C", "D", "E"])]
    row = bus_factor(build(commits))[0]
    assert row.bus_factor >= 3
    assert row.risk == "ok"


def test_bus_factor_orders_worst_first():
    commits = []
    for i in range(8):
        commits.append(commit(i, "Ada", ["hot/a.py"]))
    for i in range(8):
        commits.append(commit(100 + i, f"Dev{i % 4}", ["calm/b.py"]))
    rows = bus_factor(build(commits))
    assert rows[0].directory == "hot"
    assert rows[0].bus_factor == 1


def test_concentration_is_high_for_one_author():
    commits = [commit(i, "Ada", [f"f{i}.py"]) for i in range(10)]
    points = knowledge_concentration(build(commits), bins=5)
    assert len(points) == 5
    assert all(p.hhi == 1.0 for p in points)


def test_concentration_drops_for_many_authors():
    commits = [commit(i, f"Dev{i % 5}", [f"f{i}.py"]) for i in range(20)]
    points = knowledge_concentration(build(commits), bins=4)
    assert all(p.hhi < 0.5 for p in points)
    assert points[0].top_share <= 0.5


def test_hotspots_split_into_quadrants():
    commits = []
    for i in range(12):
        commits.append(commit(i, "Ada", ["hot.py"], insertions=80))
        commits.append(commit(100 + i, "Bob", ["cold.py"], insertions=2))
    sources = {"hot.py": "\n".join("if x: y" for _ in range(60)),
               "cold.py": "x = 1\n"}
    spots = hotspots(build(commits), sources=sources, min_commits=1)
    by_path = {s.path: s for s in spots}
    assert by_path["hot.py"].quadrant == "danger"
    assert by_path["cold.py"].quadrant == "stable"
    assert spots[0].path == "hot.py"


def test_hotspots_respect_min_commits():
    commits = [commit(i, "Ada", ["rare.py"]) for i in range(2)]
    assert hotspots(build(commits), sources={}, min_commits=5) == []


def test_cochange_finds_a_paired_file():
    commits = [commit(i, "Ada", ["a.py", "b.py"]) for i in range(6)]
    pairs = cochange(build(commits), min_together=3)
    assert pairs[0].left == "a.py"
    assert pairs[0].confidence == 1.0
    assert pairs[0].together == 6


def test_cochange_ignores_giant_commits():
    files = [f"f{i}.py" for i in range(40)]
    commits = [commit(0, "Ada", files)]
    assert cochange(build(commits), min_together=1, min_confidence=0.0) == []


def test_cochange_requires_repetition():
    commits = [commit(0, "Ada", ["a.py", "b.py"])]
    assert cochange(build(commits), min_together=3) == []


def test_monthly_aggregates_themes_and_churn():
    commits = [
        commit(0, "Ada", ["a.py"], subject="feat: one", insertions=10),
        commit(1, "Ada", ["a.py"], subject="fix: two", insertions=3, deletions=1),
        commit(2, "Bob", ["b.py"], subject="refactor: three", insertions=5),
    ]
    points = monthly(build(commits))
    assert len(points) == 1
    assert points[0].commits == 3
    assert points[0].insertions == 18
    assert points[0].deletions == 1
    assert points[0].authors == 2
    assert points[0].feature == 1 and points[0].fix == 1 and points[0].refactor == 1


def test_refactor_ratio_math():
    commits = [
        commit(0, "Ada", ["a.py"], subject="refactor: split"),
        commit(1, "Ada", ["a.py"], subject="feat: add"),
        commit(2, "Ada", ["a.py"], subject="feat: add more"),
        commit(3, "Ada", ["a.py"], subject="feat: even more"),
        commit(4, "Ada", ["a.py"], subject="refactor: split again"),
    ]
    row = refactor_ratio(build(commits))[0]
    assert row.refactor == 2
    assert row.feature == 3
    assert row.ratio == pytest.approx(0.4)


def test_size_distribution_sums_to_one():
    commits = [commit(i, "Ada", ["a.py"], insertions=i * 100) for i in range(6)]
    dist = size_distribution(build(commits))
    assert [d.bucket for d in dist] == ["XS", "S", "M", "L", "XL"]
    assert sum(d.count for d in dist) == 6
    assert sum(d.share for d in dist) == pytest.approx(1.0, abs=1e-3)


def test_findings_flag_a_dominant_author():
    commits = [commit(i, "Ada" if i % 5 else "Bob", [f"f{i % 3}.py"]) for i in range(20)]
    keys = {f.key for f in findings(build(commits))}
    assert "author-share" in keys


def test_findings_include_hotspot_and_coupling():
    commits = [commit(i, "Ada", ["hot.py"], insertions=200) for i in range(6)]
    found = {f.key for f in findings(build(commits))}
    assert "hotspot" in found


def test_findings_are_severity_sorted():
    commits = [commit(i, "Ada", ["hot.py"], insertions=200) for i in range(12)]
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    severities = [order[f.severity] for f in findings(build(commits))]
    assert severities == sorted(severities)


def test_empty_history_is_handled_everywhere():
    empty = build([])
    assert bus_factor(empty) == []
    assert monthly(empty) == []
    assert hotspots(empty) == []
    assert cochange(empty) == []
    assert knowledge_concentration(empty) == []
    assert size_distribution(empty)[0].share == 0.0
    assert findings(empty) == []


def test_repo_property_points_at_the_repo():
    history = build([])
    assert isinstance(history.repo, FakeRepo)
    assert history.name == "fake"


def test_git_repo_dataclass_is_frozen(tmp_path):
    repo = GitRepo(root=tmp_path)
    with pytest.raises(FrozenInstanceError):
        repo.root = tmp_path  # type: ignore[misc]
