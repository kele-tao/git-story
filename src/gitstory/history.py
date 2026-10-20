"""Mine a git repository into an in-memory commit graph.

Parsing strategy
----------------
Everything comes from the git binary in a few passes:

* ``git log --pretty=format:<US>%H<US>...`` gives commit metadata. Fields are
  separated by ASCII 0x1F so commit bodies may contain anything.
* ``git log --numstat -M`` gives per-file insertions/deletions *after* rename
  detection, which is what makes churn honest when a file is moved.

The result is a plain graph: no git objects, no network, no shell quoting
surprises.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from .gitio import FIELD_SEP, RECORD_SEP, GitError, GitRepo

RENAME_RE = re.compile(r"^(.*)\{(.*?) => (.*?)\}(.*)$")
ARROW = " => "


@dataclass(frozen=True)
class FileChange:
    """One path touched by a commit, after rename detection."""

    path: str
    old_path: str | None
    insertions: int
    deletions: int
    binary: bool = False

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def is_rename(self) -> bool:
        return self.old_path is not None and self.old_path != self.path


@dataclass
class Commit:
    """A single commit with its file-level churn."""

    sha: str
    parents: tuple[str, ...]
    author: str
    email: str
    timestamp: int
    subject: str
    body: str
    files: list[FileChange] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def date(self) -> _dt.date:
        return _dt.datetime.fromtimestamp(self.timestamp, _dt.timezone.utc).date()

    @property
    def month(self) -> str:
        return _dt.datetime.fromtimestamp(self.timestamp, _dt.timezone.utc).strftime("%Y-%m")

    @property
    def insertions(self) -> int:
        return sum(f.insertions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def files_touched(self) -> int:
        return len(self.files)


@dataclass(frozen=True)
class Tag:
    """A release tag reachable from the current branch."""

    name: str
    timestamp: int
    annotated: bool

    @property
    def version_key(self) -> tuple[int, ...]:
        nums = re.findall(r"\d+", self.name)
        return tuple(int(n) for n in nums[:4]) or (0,)


def parse_rename(raw: str) -> tuple[str, str | None]:
    """Return (new_path, old_path) for a numstat path, handling brace compression."""
    if ARROW not in raw:
        return raw, None
    match = RENAME_RE.match(raw)
    if match:
        prefix, old_mid, new_mid, suffix = match.groups()
        return prefix + new_mid + suffix, prefix + old_mid + suffix
    old, _, new = raw.partition(ARROW)
    return new, old


def _int_or_zero(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0


def _parse_metadata(blob: str) -> list[Commit]:
    commits: list[Commit] = []
    for record in blob.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        fields = record.split(FIELD_SEP, 6)
        if len(fields) != 7:
            continue
        sha, parents, author, email, ts, subject, body = fields
        commits.append(
            Commit(
                sha=sha.splitlines()[0].strip() if sha.strip() else "",
                parents=tuple(p for p in parents.split() if p),
                author=author.strip() or "(unknown)",
                email=email.strip(),
                timestamp=_int_or_zero(ts.strip()),
                subject=subject.strip(),
                body=body.strip(),
            )
        )
    return commits


def _parse_numstat(blob: str) -> dict[str, list[FileChange]]:
    result: dict[str, list[FileChange]] = {}
    for record in blob.split(RECORD_SEP):
        lines = [ln for ln in record.split("\n") if ln.strip()]
        if not lines:
            continue
        sha = lines[0].strip()
        changes: list[FileChange] = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            ins, dels, raw_path = parts
            binary = ins == "-" or dels == "-"
            new_path, old_path = parse_rename(raw_path)
            changes.append(
                FileChange(
                    path=new_path,
                    old_path=old_path,
                    insertions=0 if binary else _int_or_zero(ins),
                    deletions=0 if binary else _int_or_zero(dels),
                    binary=binary,
                )
            )
        result[sha] = changes
    return result


SINCE_RE = re.compile(r"^(\d+(?:\.\d+)?)([ymwd])$")
SINCE_UNITS = {"y": 365, "m": 30, "w": 7, "d": 1}


def since_to_date(spec: str | None, now: _dt.datetime | None = None) -> _dt.date | None:
    """Turn ``1y`` / ``6m`` / ``2w`` / ``30d`` / ``2024-01-01`` into a date."""
    if not spec:
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    match = SINCE_RE.match(spec.strip().lower())
    if match:
        amount, unit = match.groups()
        days = float(amount) * SINCE_UNITS[unit]
        return (now - _dt.timedelta(days=days)).date()
    try:
        return _dt.date.fromisoformat(spec.strip())
    except ValueError as exc:
        raise GitError(
            f"cannot parse --since {spec!r}: use 1y, 6m, 2w, 30d or an ISO date (2024-01-01)"
        ) from exc


def parse_tags(repo: GitRepo) -> list[Tag]:
    """Tags keyed by the *commit* date, not the tagger date.

    An annotated tag records when it was created, which on a freshly cloned or
    freshly generated repository is "now" for every tag and would make release
    cadence nonsense. The dereferenced commit date is the honest number.
    """
    out = repo.run_text(
        "for-each-ref",
        "--format=%(refname:short)"
        + FIELD_SEP
        + "%(objecttype)"
        + FIELD_SEP
        + "%(creatordate:unix)"
        + FIELD_SEP
        + "%(*creatordate:unix)",
        "refs/tags",
    )
    tags: list[Tag] = []
    for line in out.splitlines():
        parts = line.split(FIELD_SEP)
        if len(parts) != 4 or not parts[0]:
            continue
        annotated = parts[1] == "tag"
        raw = parts[3] if annotated and parts[3].strip() else parts[2]
        tags.append(Tag(name=parts[0], timestamp=_int_or_zero(raw), annotated=annotated))
    tags.sort(key=lambda t: (t.timestamp, t.version_key))
    return tags


class History:
    """The parsed repository: commits (oldest first), tags and derived indexes."""

    def __init__(self, repo: GitRepo, commits: list[Commit], tags: list[Tag]):
        commits.sort(key=lambda c: (c.timestamp, c.sha))
        self.repo = repo
        self.commits = commits
        self.tags = tags
        self.by_sha = {c.sha: c for c in commits}
        self.path_map = canonical_paths(commits)
        self._apply_canonical_paths()

    # ------------------------------------------------------------------ facts
    @property
    def name(self) -> str:
        return self.repo.name

    def __iter__(self):
        return iter(self.commits)

    def __getitem__(self, index):
        return self.commits[index]

    def _apply_canonical_paths(self) -> None:
        """Rewrite historical paths to the file's newest name.

        Without this, a directory that was renamed away keeps haunting every
        analysis: moving orbit/utils.py into orbit/support/ would otherwise
        leave a phantom "orbit/{...}" directory in the bus-factor table.
        """
        if not self.path_map:
            return
        for commit in self.commits:
            rewritten: list[FileChange] = []
            for change in commit.files:
                canonical = self.path_map.get(change.path, change.path)
                if canonical == change.path:
                    rewritten.append(change)
                else:
                    rewritten.append(
                        FileChange(
                            path=canonical,
                            old_path=change.old_path,
                            insertions=change.insertions,
                            deletions=change.deletions,
                            binary=change.binary,
                        )
                    )
            commit.files = rewritten

    @property
    def first_commit(self) -> Commit | None:
        return self.commits[0] if self.commits else None

    @property
    def last_commit(self) -> Commit | None:
        return self.commits[-1] if self.commits else None

    @property
    def authors(self) -> list[str]:
        seen: dict[str, int] = {}
        for c in self.commits:
            seen[c.author] = seen.get(c.author, 0) + 1
        return sorted(seen, key=lambda a: (-seen[a], a))

    @property
    def span(self) -> tuple[_dt.date, _dt.date] | None:
        if not self.commits:
            return None
        return self.commits[0].date, self.commits[-1].date

    def path_changes(self) -> dict[str, list[tuple[Commit, FileChange]]]:
        """All (commit, change) pairs keyed by the *current* path."""
        index: dict[str, list[tuple[Commit, FileChange]]] = {}
        for commit in self.commits:
            for change in commit.files:
                index.setdefault(change.path, []).append((commit, change))
        return index

    def file_commits(self) -> dict[str, int]:
        return {path: len(hits) for path, hits in self.path_changes().items()}

    def file_authors(self) -> dict[str, dict[str, int]]:
        authors: dict[str, dict[str, int]] = {}
        for path, hits in self.path_changes().items():
            bucket = authors.setdefault(path, {})
            for commit, _ in hits:
                bucket[commit.author] = bucket.get(commit.author, 0) + 1
        return authors

    def file_churn(self) -> dict[str, tuple[int, int, int]]:
        """path -> (insertions, deletions, commits)."""
        churn: dict[str, tuple[int, int, int]] = {}
        for path, hits in self.path_changes().items():
            ins = sum(ch.insertions for _, ch in hits)
            dels = sum(ch.deletions for _, ch in hits)
            churn[path] = (ins, dels, len(hits))
        return churn

    def merges(self) -> list[Commit]:
        return [c for c in self.commits if c.is_merge]

    def head_files(self) -> list[str]:
        return repo_ls(self.repo)

    def __len__(self) -> int:
        return len(self.commits)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<History {self.name} commits={len(self.commits)} authors={len(self.authors)}>"


def canonical_paths(commits: list[Commit]) -> dict[str, str]:
    """Follow every detected rename so an old path resolves to the newest name."""
    direct: dict[str, str] = {}
    for commit in commits:
        for change in commit.files:
            if change.old_path and change.old_path != change.path:
                direct[change.old_path] = change.path
    canonical: dict[str, str] = {}
    for old in direct:
        seen = {old}
        current = direct[old]
        while current in direct and current not in seen:
            seen.add(current)
            current = direct[current]
        canonical[old] = current
    return canonical


def repo_ls(repo: GitRepo) -> list[str]:
    """Files tracked at HEAD, as slash-separated paths."""
    return repo.run_text("ls-tree", "-r", "--name-only", "HEAD").splitlines()


def scan(
    path: str | Path = ".",
    since: str | None = None,
    until: str | None = None,
    include_merges: bool = True,
    max_commits: int = 20_000,
    now: _dt.datetime | None = None,
) -> History:
    """Read a repository's history into memory.

    >>> hist = scan(".")                       # doctest: +SKIP
    >>> hist.commits[-1].subject               # doctest: +SKIP
    'feat: initial import'
    """
    repo = GitRepo.discover(path)
    if not repo.has_commits():
        raise GitError(f"repository has no commits yet: {repo.root}")

    fmt = RECORD_SEP + FIELD_SEP.join(["%H", "%P", "%an", "%ae", "%at", "%s", "%b"])
    log_args = ["log", "--reverse", f"--pretty=format:{fmt}", f"--max-count={max_commits}"]
    numstat_args = [
        "log",
        "--reverse",
        "--numstat",
        "-M",
        f"--pretty=format:{RECORD_SEP}%H",
        f"--max-count={max_commits}",
    ]
    since_date = since_to_date(since, now)
    if since_date is not None:
        iso = _dt.datetime.combine(since_date, _dt.time.min, _dt.timezone.utc).isoformat()
        log_args.append(f"--since={iso}")
        numstat_args.append(f"--since={iso}")
    if until:
        until_date = since_to_date(until, now) or _dt.date.today()
        iso = _dt.datetime.combine(until_date, _dt.time.max, _dt.timezone.utc).isoformat()
        log_args.append(f"--until={iso}")
        numstat_args.append(f"--until={iso}")
    if not include_merges:
        log_args.append("--no-merges")
        numstat_args.append("--no-merges")

    commits = _parse_metadata(repo.run_text(*log_args))
    changes = _parse_numstat(repo.run_text(*numstat_args))
    for commit in commits:
        commit.files = changes.get(commit.sha, [])
    return History(repo, commits, parse_tags(repo))
