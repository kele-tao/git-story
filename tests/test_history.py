"""History parsing: metadata, numstat, renames, tags, since filters."""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import git
from gitstory import GitError, scan
from gitstory.gitio import GitRepo
from gitstory.history import parse_rename, since_to_date


def test_scans_commits_oldest_first(small_history):
    subjects = [c.subject for c in small_history]
    assert subjects == [
        "feat: bootstrap the app",
        "fix: off by one in main",
        "test: cover main",
        "refactor: move helpers",
    ]
    assert len(small_history) == 4


def test_authors_are_ranked_by_commit_count(small_history):
    assert small_history.authors == ["Ada", "Grace", "Lin"]


def test_commit_metadata_is_parsed(small_history):
    commit = small_history.commits[0]
    assert len(commit.sha) == 40
    assert commit.author == "Ada"
    assert commit.email == "ada@example.com"
    assert commit.timestamp > 0
    assert commit.subject == "feat: bootstrap the app"


def test_numstat_gives_line_level_churn(small_history):
    first = small_history.commits[0]
    assert first.files_touched == 4
    assert first.insertions > 0
    assert first.churn >= first.insertions


def test_rename_is_detected_and_attributed_to_new_path(small_history):
    rename_commit = small_history.commits[-1]
    change = next(f for f in rename_commit.files if f.path == "src/helpers.py")
    assert change.old_path == "src/util.py"
    assert change.insertions == 0 and change.deletions == 0


def test_parse_rename_brace_form():
    assert parse_rename("orbit/{utils.py => support/utils.py}") == (
        "orbit/support/utils.py",
        "orbit/utils.py",
    )
    assert parse_rename("a/{b => c}/d.py") == ("a/c/d.py", "a/b/d.py")
    assert parse_rename("plain.py") == ("plain.py", None)


def test_parse_rename_unbraced_form():
    assert parse_rename("old.py => new.py") == ("new.py", "old.py")


def test_tags_are_sorted_and_dated(small_history):
    assert [t.name for t in small_history.tags] == ["v0.1.0"]
    assert small_history.tags[0].annotated
    assert small_history.tags[0].timestamp > 0


def test_file_indexes_agree(small_history):
    commits = small_history.file_commits()
    churn = small_history.file_churn()
    assert commits["src/app.py"] == 2
    assert churn["src/app.py"][2] == 2
    # The historical src/util.py commit is folded into its new name.
    assert "src/util.py" not in commits
    assert commits["src/helpers.py"] == 2


def test_rename_history_is_canonicalised(small_history):
    assert small_history.path_map["src/util.py"] == "src/helpers.py"
    canonical = {
        f.path for c in small_history.commits for f in c.files if f.path.startswith("src/")
    }
    assert "src/util.py" not in canonical


def test_head_files_lists_tracked_paths(small_history):
    files = small_history.head_files()
    assert "src/helpers.py" in files
    assert "tests/test_app.py" in files


def test_merges_are_flagged(repo):
    repo.write("a.py", "x = 1\n")
    repo.commit("feat: base")
    git(repo.root, "checkout", "-b", "topic")
    repo.write("a.py", "x = 2\n")
    repo.commit("feat: topic change")
    git(repo.root, "checkout", "main")
    repo.write("b.py", "y = 1\n")
    repo.commit("feat: main side")
    git(repo.root, "merge", "--no-ff", "topic", "-m", "Merge branch 'topic'")
    history = scan(repo.root)
    merges = history.merges()
    assert len(merges) == 1
    assert merges[0].subject.startswith("Merge branch")


def test_merges_can_be_excluded(repo):
    repo.write("a.py", "x = 1\n")
    repo.commit("feat: base")
    git(repo.root, "checkout", "-b", "topic")
    repo.write("a.py", "x = 2\n")
    repo.commit("feat: topic")
    git(repo.root, "checkout", "main")
    repo.write("b.py", "y = 1\n")
    repo.commit("feat: main")
    git(repo.root, "merge", "--no-ff", "topic", "-m", "Merge branch 'topic'")
    assert len(scan(repo.root).merges()) == 1
    assert scan(repo.root, include_merges=False).merges() == []


def test_since_accepts_relative_units():
    now = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)
    assert since_to_date("1y", now) == dt.date(2023, 6, 2)
    assert since_to_date("30d", now) == dt.date(2024, 5, 2)
    assert since_to_date("2w", now) == dt.date(2024, 5, 18)


def test_since_accepts_iso_dates():
    assert since_to_date("2024-01-01") == dt.date(2024, 1, 1)
    assert since_to_date(None) is None


def test_since_rejects_garbage():
    with pytest.raises(GitError, match="cannot parse --since"):
        since_to_date("last tuesday")


def test_since_filters_history(small_history):
    now = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    recent = scan(small_history.repo.root, since="30d", now=now)
    assert len(recent) <= len(small_history)


def test_unicode_filenames_and_messages_survive(repo):
    repo.write("文档/说明.md", "# 你好\n")
    seed = repo.commit("feat: 添加中文文档 🚀", author="李雷")
    assert len(seed) == 40
    history = scan(repo.root)
    subjects = [c.subject for c in history]
    assert "feat: 添加中文文档 🚀" in subjects
    assert "文档/说明.md" in history.file_commits()


def test_empty_repository_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-b", "main")
    with pytest.raises(GitError, match="no commits"):
        scan(empty)


def test_non_repository_raises(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitError, match="not a git repository"):
        scan(plain)


def test_missing_path_raises(tmp_path):
    with pytest.raises(GitError, match="does not exist"):
        scan(tmp_path / "nope")


def test_repo_discovery_from_subdirectory(small_history):
    nested = small_history.repo.root / "src"
    found = GitRepo.discover(nested)
    assert found.root == small_history.repo.root


def test_show_file_returns_head_content(small_history):
    assert "helper" in (small_history.repo.show_file("HEAD:src/helpers.py") or "")
    assert small_history.repo.show_file("HEAD:does/not/exist.py") is None


def test_max_commits_caps_the_scan(repo):
    for i in range(6):
        repo.write("a.py", f"x = {i}\n")
        repo.commit(f"feat: change {i}")
    assert len(scan(repo.root, max_commits=3)) == 3


def test_binary_files_do_not_crash_numstat(repo):
    (repo.root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    repo.write("a.py", "x = 1\n")
    repo.commit("feat: add a binary and a module")
    history = scan(repo.root)
    binary = next(f for f in history.commits[0].files if f.path == "logo.png")
    assert binary.binary
    assert binary.churn == 0
