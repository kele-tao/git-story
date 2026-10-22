"""Classify commits into engineering themes.

Two independent signals are combined, in this order:

1. **The message** -- Conventional Commits types (feat:, fix:, refactor: ...)
   and keyword fallbacks for teams that do not use them.
2. **The diff shape** -- a commit where every changed file is a rename is a
   refactor whatever the message says; a commit that only touches docs is docs.

Shape wins only when the message is ambiguous, so an explicit "refactor: move
parser" is never overruled by a rename heuristic. The classifier is pure and
deterministic, which is why chronicle output is byte-identical between runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .history import Commit

THEMES = ("feature", "fix", "refactor", "docs", "test", "build", "release", "chore", "other")

THEME_LABELS = {
    "feature": "Feature",
    "fix": "Fix",
    "refactor": "Refactor",
    "docs": "Docs",
    "test": "Test",
    "build": "Build",
    "release": "Release",
    "chore": "Chore",
    "other": "Other",
}

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$"
)
MERGE_RE = re.compile(r"^Merge\b", re.I)
RELEASE_RE = re.compile(r"^(release|v?\d+\.\d+\.\d+)\b", re.I)

TYPE_THEME = {
    "feat": "feature",
    "feature": "feature",
    "fix": "fix",
    "hotfix": "fix",
    "bugfix": "fix",
    "refactor": "refactor",
    "perf": "refactor",
    "style": "refactor",
    "docs": "docs",
    "doc": "docs",
    "test": "test",
    "tests": "test",
    "build": "build",
    "ci": "build",
    "deps": "build",
    "chore": "chore",
    "release": "release",
    "revert": "fix",
}

KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("release", re.compile(r"\b(release|bump(?:ed)? version|cut v?\d|changelog)\b", re.I)),
    ("refactor", re.compile(r"\b(refactor|rename|move|extract|dedupe|simplif\w*|cleanup)\b", re.I)),
    ("fix", re.compile(r"\b(fix(?:es|ed)?|bug|hotfix|repair|regression|crash|broken)\b", re.I)),
    ("docs", re.compile(r"\b(docs?|readme|typo|comment)\b", re.I)),
    ("test", re.compile(r"\b(tests?|specs?|coverage|fixtures?)\b", re.I)),
    ("build", re.compile(r"\b(ci|build|docker|deps|dependencies|bump)\b", re.I)),
    ("feature", re.compile(r"\b(add(?:ed|s)?|implement(?:ed|s)?|support|introduc\w*|new)\b", re.I)),
)

DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
TEST_MARKERS = ("test_", "_test.", "/tests/", "/test/", "spec.", "conftest.py")

SIZE_BUCKETS = (
    (0, 10, "XS"),
    (10, 50, "S"),
    (50, 250, "M"),
    (250, 1000, "L"),
    (1000, 10**9, "XL"),
)


@dataclass(frozen=True)
class Classification:
    """The theme of one commit plus the evidence that produced it."""

    theme: str
    source: str  # "message", "diff" or "fallback"
    scope: str | None
    conventional: str | None

    @property
    def label(self) -> str:
        return THEME_LABELS.get(self.theme, self.theme.title())


def conventional_type(subject: str) -> tuple[str | None, str | None]:
    """Return (type, scope) for a Conventional Commit subject, else (None, None)."""
    match = CONVENTIONAL_RE.match(subject.strip())
    if not match:
        return None, None
    return match.group("type").lower(), (match.group("scope") or None)


def _shape_theme(commit: Commit) -> str | None:
    files = [f for f in commit.files if f.path]
    if not files:
        return None
    if all(f.is_rename for f in files):
        return "refactor"
    lower = [f.path.lower() for f in files]
    if all(p.endswith(DOC_SUFFIXES) or p.startswith("docs/") for p in lower):
        return "docs"
    if all(any(m in p for m in TEST_MARKERS) for p in lower):
        return "test"
    return None


def classify(commit: Commit) -> Classification:
    """Classify a commit by message first, diff shape second."""
    subject = commit.subject.strip()
    ctype, scope = conventional_type(subject)
    if ctype and ctype in TYPE_THEME:
        return Classification(TYPE_THEME[ctype], "message", scope, ctype)

    if MERGE_RE.match(subject):
        return Classification("chore", "message", None, None)
    if RELEASE_RE.match(subject):
        return Classification("release", "message", None, None)

    shape = _shape_theme(commit)
    if shape:
        return Classification(shape, "diff", scope, ctype)

    haystack = subject + " " + commit.body[:400]
    for theme, pattern in KEYWORDS:
        if pattern.search(haystack):
            return Classification(theme, "fallback", scope, ctype)
    return Classification("other", "fallback", scope, ctype)


def size_bucket(churn: int) -> str:
    """Map a churn value to XS/S/M/L/XL."""
    for low, high, name in SIZE_BUCKETS:
        if low <= churn < high:
            return name
    return "XL"


def is_review_less(commit: Commit) -> bool:
    """A merge commit with no reviewer trailer in its message.

    Git metadata does not record pull-request approvals, so git-story only
    trusts machine-readable trailers. The number is therefore an upper bound
    on merges that skipped review; the README says so explicitly.
    """
    if not commit.is_merge:
        return False
    text = (commit.subject + "\n" + commit.body).lower()
    for trailer in ("reviewed-by:", "approved-by:", "co-authored-by:", "signed-off-by:"):
        if trailer in text:
            return False
    return True
