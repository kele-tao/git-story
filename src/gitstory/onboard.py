"""The onboarding guide: the ten files a newcomer should read first.

Three honest signals, weighted:

* **reverse imports** -- how many files import this one (from a real AST parse).
  A module that everything depends on is the architecture.
* **churn** -- files that change constantly are where the work is.
* **co-change centrality** -- files that co-change with the widest set of other
  files sit at the centre of the codebase's hidden coupling.

Every entry carries its evidence so a reader can challenge the ranking.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from dataclasses import dataclass

from .history import History
from .imports import ImportGraph, build_import_graph, is_noise
from .metrics import cochange

W_IMPORTS = 3.0
W_CHURN = 1.5
W_COCHANGE = 1.0
W_ENTRY = 2.0

ENTRY_POINT_HINTS = (
    "__main__.py",
    "cli.py",
    "main.py",
    "app.py",
    "index.js",
    "index.ts",
    "main.rs",
    "main.go",
)


@dataclass(frozen=True)
class OnboardEntry:
    """One recommended read, with the reasons it was recommended."""

    rank: int
    path: str
    score: float
    importers: int
    commits: int
    authors: int
    coupled_files: int
    reasons: tuple[str, ...]

    @property
    def read_minutes(self) -> int:
        return max(2, min(45, self.commits // 2 + 3))


def read_head_files(history: History, limit_bytes: int = 200_000) -> dict[str, str]:
    """Read every tracked text source file at HEAD, bounded per file."""
    sources: dict[str, str] = {}
    for path in history.head_files():
        if not path.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs")):
            continue
        text = history.repo.show_file(f"HEAD:{path}", limit=limit_bytes)
        if text is not None:
            sources[path] = text
    return sources


def onboard(
    history: History,
    sources: dict[str, str] | None = None,
    top: int = 10,
    include_tests: bool = False,
) -> list[OnboardEntry]:
    """Rank the files a newcomer should read, from imports + churn + coupling."""
    if sources is None:
        sources = read_head_files(history)
    graph: ImportGraph = build_import_graph(sources)
    in_degree = graph.in_degree
    churn = history.file_churn()
    authors = history.file_authors()
    couplings = cochange(history, top=200, min_together=2, min_confidence=0.2)
    coupled: Counter[str] = Counter()
    for pair in couplings:
        coupled[pair.left] += 1
        coupled[pair.right] += 1

    candidates: list[str] = []
    for path in sources:
        if not include_tests and _looks_like_test(path):
            continue
        if is_noise(path) and path not in in_degree:
            continue
        candidates.append(path)
    if not candidates:
        candidates = list(sources)

    max_imports = max((in_degree.get(p, 0) for p in candidates), default=0) or 1
    max_churn = max((churn.get(p, (0, 0, 0))[2] for p in candidates), default=0) or 1
    max_coupled = max((coupled.get(p, 0) for p in candidates), default=0) or 1

    scored: list[OnboardEntry] = []
    for path in candidates:
        imports = in_degree.get(path, 0)
        commits = churn.get(path, (0, 0, 0))[2]
        author_count = len(authors.get(path, {}))
        coupled_count = coupled.get(path, 0)
        reasons: list[str] = []
        score = 0.0
        if imports:
            score += W_IMPORTS * (imports / max_imports)
            reasons.append(f"imported by {imports} file{'s' if imports != 1 else ''}")
        if commits:
            score += W_CHURN * (commits / max_churn)
            reasons.append(f"{commits} commit{'s' if commits != 1 else ''}")
        if coupled_count:
            score += W_COCHANGE * (coupled_count / max_coupled)
            plural = "" if coupled_count == 1 else "s"
            reasons.append(f"co-changes with {coupled_count} file{plural}")
        if posixpath.basename(path) in ENTRY_POINT_HINTS:
            score += W_ENTRY
            reasons.append("entry point")
        if author_count >= 3:
            score += 0.5
            reasons.append(f"{author_count} authors touched it")
        if score <= 0:
            continue
        scored.append(
            OnboardEntry(
                rank=0,
                path=path,
                score=round(score, 3),
                importers=imports,
                commits=commits,
                authors=author_count,
                coupled_files=coupled_count,
                reasons=tuple(reasons[:3]),
            )
        )
    scored.sort(key=lambda e: (-e.score, -e.importers, e.path))
    trimmed = scored[:top]
    return [
        OnboardEntry(
            rank=i,
            path=e.path,
            score=e.score,
            importers=e.importers,
            commits=e.commits,
            authors=e.authors,
            coupled_files=e.coupled_files,
            reasons=e.reasons,
        )
        for i, e in enumerate(trimmed, 1)
    ]


def _looks_like_test(path: str) -> bool:
    lower = "/" + path.lower()
    base = posixpath.basename(lower)
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base == "conftest.py"
        or "/tests/" in lower
        or "/test/" in lower
    )
