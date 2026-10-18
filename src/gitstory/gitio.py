"""A small, deterministic wrapper around the real git binary.

git-story never re-implements git. It shells out to the binary, parses machine
formats (pretty=format with ASCII unit separators), and turns failures into
actionable errors. Every call is read-only, so the tool is safe to run against
a repository you are actively working in.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Unit / record separators keep parsing immune to commas, tabs and newlines
# inside commit messages and author names.
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


class GitError(RuntimeError):
    """Raised when git is missing, the path is not a repository, or a call fails."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_PAGER"] = "cat"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    # Keep paths raw so CJK and emoji filenames survive the round trip.
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "core.quotepath"
    env["GIT_CONFIG_VALUE_0"] = "false"
    return env


@dataclass(frozen=True)
class GitRepo:
    """A discovered, verified working tree."""

    root: Path

    @classmethod
    def discover(cls, path: str | Path = ".") -> GitRepo:
        """Resolve *path* to the top level of a git working tree."""
        candidate = Path(path).expanduser()
        if not candidate.exists():
            raise GitError(f"path does not exist: {candidate}")
        if candidate.is_file():
            candidate = candidate.parent
        if shutil.which("git") is None:
            raise GitError("git executable not found on PATH; install git 2.20+")
        proc = _run(candidate, ["rev-parse", "--show-toplevel"])
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            if "not a git repository" in detail.lower():
                raise GitError(
                    f"not a git repository: {candidate}\n"
                    "hint: pass -C <repo> or run git init first"
                )
            raise GitError(f"git rev-parse failed: {detail or '(no output)'}")
        root = Path(proc.stdout.decode("utf-8", "replace").strip()).resolve()
        return cls(root=root)

    def run(self, *args: str, check: bool = True) -> bytes:
        """Run a read-only git command inside this repository."""
        proc = _run(self.root, list(args))
        if check and proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise GitError(f"git {' '.join(args)} failed: {detail or '(no output)'}")
        return proc.stdout

    def run_text(self, *args: str, check: bool = True) -> str:
        return self.run(*args, check=check).decode("utf-8", "replace")

    @property
    def name(self) -> str:
        return self.root.name

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").decode().strip()

    def has_commits(self) -> bool:
        return _run(self.root, ["rev-parse", "--verify", "HEAD"]).returncode == 0

    def show_file(self, spec: str, limit: int = 400_000) -> str | None:
        """Return a blob at HEAD, or None when it is missing or too large."""
        proc = _run(self.root, ["show", spec])
        if proc.returncode != 0 or len(proc.stdout) > limit:
            return None
        return proc.stdout.decode("utf-8", "replace")

    def rev_list(self, *args: str) -> list[str]:
        out = self.run_text("rev-list", *args)
        return [line.strip() for line in out.splitlines() if line.strip()]


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            env=_env(),
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on host
        raise GitError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after 180s") from exc
