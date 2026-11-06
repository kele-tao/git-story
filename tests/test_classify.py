"""Classifier: message first, diff shape second, keywords last."""

from __future__ import annotations

import pytest

from gitstory.classify import (
    THEMES,
    classify,
    conventional_type,
    is_review_less,
    size_bucket,
)
from gitstory.history import Commit, FileChange


def make(subject: str, files=None, body: str = "", parents=("a",)) -> Commit:
    return Commit(
        sha="0" * 40,
        parents=tuple(parents),
        author="Ada",
        email="ada@example.com",
        timestamp=1_700_000_000,
        subject=subject,
        body=body,
        files=files or [],
    )


@pytest.mark.parametrize(
    ("subject", "theme"),
    [
        ("feat: add retries", "feature"),
        ("fix: crash on empty input", "fix"),
        ("refactor: split the parser", "refactor"),
        ("docs: explain the flags", "docs"),
        ("test: cover the cache", "test"),
        ("build: pin the toolchain", "build"),
        ("chore: bump deps", "chore"),
        ("perf: avoid the copy", "refactor"),
        ("revert: undo the rename", "fix"),
    ],
)
def test_conventional_types_map_to_themes(subject, theme):
    assert classify(make(subject)).theme == theme


def test_scope_is_preserved():
    info = classify(make("feat(api): expose version"))
    assert info.scope == "api"
    assert info.conventional == "feat"
    assert info.theme == "feature"


def test_conventional_type_helper_handles_plain_subjects():
    assert conventional_type("feat(api)!: break things") == ("feat", "api")
    assert conventional_type("just a message") == (None, None)


def test_merge_subject_is_chore():
    assert classify(make("Merge branch 'topic'")).theme == "chore"


def test_release_subject_is_detected():
    assert classify(make("release: v1.2.0")).theme == "release"


def test_all_rename_commit_is_a_refactor_even_without_a_prefix():
    files = [FileChange("src/b.py", "src/a.py", 0, 0)]
    assert classify(make("moved the module", files=files)).theme == "refactor"


def test_docs_only_commit_is_docs_by_shape():
    files = [FileChange("docs/guide.md", None, 4, 1)]
    assert classify(make("explain things", files=files)).theme == "docs"


def test_test_only_commit_is_test_by_shape():
    files = [FileChange("tests/test_x.py", None, 9, 0)]
    assert classify(make("checks for x", files=files)).theme == "test"


def test_keyword_fallback_when_shape_is_ambiguous():
    files = [FileChange("src/a.py", None, 1, 1)]
    assert classify(make("Fix the broken migration", files=files)).theme == "fix"


def test_unknown_message_falls_back_to_other():
    files = [FileChange("src/a.py", None, 1, 1)]
    assert classify(make("update", files=files)).theme == "other"


def test_every_theme_is_declared():
    assert set(THEMES) == {
        "feature", "fix", "refactor", "docs", "test", "build", "release", "chore", "other"
    }


@pytest.mark.parametrize(
    ("churn", "bucket"),
    [(0, "XS"), (9, "XS"), (10, "S"), (49, "S"), (50, "M"), (249, "M"),
     (250, "L"), (999, "L"), (1000, "XL"), (10**6, "XL")],
)
def test_size_buckets(churn, bucket):
    assert size_bucket(churn) == bucket


def test_review_less_requires_a_merge():
    assert not is_review_less(make("Merge branch 'x'", parents=("a",)))


def test_review_less_merge_without_trailer():
    commit = make("Merge branch 'x'", parents=("a", "b"))
    assert is_review_less(commit)


def test_reviewed_merge_is_not_review_less():
    commit = make("Merge branch 'x'", parents=("a", "b"), body="Reviewed-by: Kim <kim@x>")
    assert not is_review_less(commit)
