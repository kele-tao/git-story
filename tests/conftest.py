"""Shared fixtures: real git repositories, built once and cloned per test.

Building a repository from scratch costs ~0.5 s per git invocation on Windows.
Tests that only *read* a history therefore clone a session-scoped template
instead; tests that need to commit build their own repository.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    full = {**os.environ, **GIT_ENV}
    if env:
        full.update(env)
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=full,
    )
    if proc.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " failed: " + proc.stderr)
    return proc.stdout


def force_rmtree(path: Path) -> None:
    for root, _dirs, names in os.walk(path):
        for name in names:
            with contextlib.suppress(OSError):
                (Path(root) / name).chmod(0o777)
    shutil.rmtree(path, ignore_errors=True)


class RepoBuilder:
    """Writes files and commits them with deterministic identities and dates."""

    def __init__(self, root: Path, clock: int = 1_700_000_000, setup: bool = True) -> None:
        self.root = root
        self._clock = clock
        if setup:
            git(root, "init", "-b", "main")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str, author: str = "Ada", body: str = "",
               advance: int = 86_400) -> str:
        self._clock += advance
        stamp = f"{self._clock} +0000"
        email = author.lower().replace(" ", ".") + "@example.com"
        env = {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": stamp,
        }
        git(self.root, "add", "-A", env=env)
        args = ["commit", "-m", message]
        if body:
            args += ["-m", body]
        git(self.root, *args, env=env)
        return git(self.root, "rev-parse", "HEAD").strip()

    def tag(self, name: str) -> None:
        git(self.root, "tag", "-a", name, "-m", name)


def _build_template(root: Path) -> None:
    """Four commits, three authors, a rename and a tag."""
    repo = RepoBuilder(root)
    repo.write("src/app.py", "from .util import helper\n\n\ndef main():\n    return helper()\n")
    repo.write("src/util.py", "def helper():\n    return 1\n")
    repo.write("src/other.py", "from .app import main\n")
    repo.write("README.md", "# demo\n")
    repo.commit("feat: bootstrap the app", author="Ada")
    repo.write("src/app.py", "from .util import helper\n\n\ndef main():\n    return helper() + 1\n")
    repo.commit("fix: off by one in main", author="Grace")
    repo.tag("v0.1.0")
    repo.write("src/other.py", "from .app import main\nfrom .util import helper\n")
    repo.write(
        "tests/test_app.py",
        "from src.app import main\n\n\ndef test_main():\n    assert main()\n",
    )
    repo.commit("test: cover main", author="Ada")
    git(repo.root, "mv", "src/util.py", "src/helpers.py")
    repo.commit("refactor: move helpers", author="Lin")


@pytest.fixture(scope="session")
def template_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("template") / "sample"
    root.mkdir()
    _build_template(root)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> RepoBuilder:
    root = tmp_path / "sample"
    root.mkdir()
    return RepoBuilder(root)


@pytest.fixture
def cloned(template_repo: Path, tmp_path: Path) -> Path:
    """A private copy of the session template: read-only history tests."""
    dest = tmp_path / "sample"
    if dest.exists():
        force_rmtree(dest)
    shutil.copytree(template_repo, dest)
    return dest


@pytest.fixture
def small_history(cloned: Path):
    from gitstory import scan

    return scan(cloned)
