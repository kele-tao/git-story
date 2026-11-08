"""Rebuild examples/demo_repo: a realistic 130+ commit repository.

The demo repository is *generated*, not copied, so anyone can reproduce the
README numbers with one command:

    python benchmarks/make_demo_repo.py

It is deterministic: fixed seed, fixed commit order, commit dates anchored to
today and walked backwards. Re-running it produces the same history shape
(6 authors, one refactor month, one hotspot file, tagged releases, merges with
and without Reviewed-by trailers).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "examples" / "demo_repo"
SEED = 20240607
DAYS_BACK = 430

AUTHORS = [
    ("Mia Chen", "mia@orbit.example"),
    ("Ravi Patel", "ravi@orbit.example"),
    ("Sofia Rossi", "sofia@orbit.example"),
    ("Tomas Novak", "tomas@orbit.example"),
    ("Aiko Tanaka", "aiko@orbit.example"),
    ("Ben Okafor", "ben@orbit.example"),
]
HOTSPOT_AUTHOR = AUTHORS[0]
REVIEWERS = ["Lena Ortiz <lena@orbit.example>", "Sam Wu <sam@orbit.example>"]

MODULES = {
    "orbit/config.py": '''"""Configuration loading for the orbit scheduler."""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    queue_name: str = "default"
    workers: int = 4
    retries: int = 3


def load_settings() -> Settings:
    name = os.environ.get("ORBIT_QUEUE", "default")
    return Settings(queue_name=name)
''',
    "orbit/models.py": '''"""Core data structures."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Job:
    name: str
    payload: dict = field(default_factory=dict)
    attempts: int = 0

    def retryable(self, limit: int) -> bool:
        return self.attempts < limit
''',
    "orbit/storage.py": '''"""A tiny in-memory job store."""
from __future__ import annotations
from .models import Job


class Store:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def put(self, job: Job) -> None:
        self._jobs[job.name] = job

    def get(self, name: str) -> Job | None:
        return self._jobs.get(name)

    def size(self) -> int:
        return len(self._jobs)
''',
    "orbit/utils.py": '''"""Small helpers shared across modules."""
from __future__ import annotations


def slug(text: str) -> str:
    return "-".join(text.lower().split())


def chunk(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]
''',
    "orbit/scheduler.py": '''"""The scheduling loop."""
from __future__ import annotations
from .config import Settings
from .models import Job
from .storage import Store


class Scheduler:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.started = 0

    def submit(self, job: Job) -> None:
        self.store.put(job)
        self.started += 1

    def run_once(self) -> int:
        processed = 0
        for name in list(self.store._jobs):
            job = self.store.get(name)
            if job is None:
                continue
            if job.retryable(self.settings.retries):
                job.attempts += 1
                processed += 1
        return processed
''',
    "orbit/worker.py": '''"""Worker process that drains the scheduler."""
from __future__ import annotations
from .scheduler import Scheduler


class Worker:
    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler
        self.done = 0

    def tick(self) -> int:
        batch = self.scheduler.run_once()
        self.done += batch
        return batch
''',
    "orbit/metrics.py": '''"""Counters exposed for monitoring."""
from __future__ import annotations
from .storage import Store


class Metrics:
    def __init__(self, store: Store) -> None:
        self.store = store

    def depth(self) -> int:
        return self.store.size()

    def snapshot(self) -> dict:
        return {"depth": self.depth()}
''',
    "orbit/http_api.py": '''"""A minimal JSON API surface."""
from __future__ import annotations
from .metrics import Metrics
from .models import Job
from .scheduler import Scheduler


class Api:
    def __init__(self, scheduler: Scheduler, metrics: Metrics) -> None:
        self.scheduler = scheduler
        self.metrics = metrics

    def submit(self, name: str) -> dict:
        self.scheduler.submit(Job(name=name))
        return {"queued": name}

    def status(self) -> dict:
        return self.metrics.snapshot()
''',
    "orbit/cli.py": '''"""Command line entry point."""
from __future__ import annotations
import json
from .config import load_settings
from .http_api import Api
from .metrics import Metrics
from .scheduler import Scheduler
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    store = Store()
    scheduler = Scheduler(store, settings)
    api = Api(scheduler, Metrics(store))
    print(json.dumps(api.status()))
    return 0
''',
    "orbit/__init__.py": '''"""orbit: a small distributed job scheduler."""
from __future__ import annotations

__version__ = "0.1.0"

from .config import Settings  # noqa: F401
from .scheduler import Scheduler  # noqa: F401
''',
}

TESTS = {
    "tests/test_scheduler.py": '''from orbit.config import Settings
from orbit.models import Job
from orbit.scheduler import Scheduler
from orbit.storage import Store


def test_submit_counts():
    scheduler = Scheduler(Store(), Settings())
    scheduler.submit(Job("a"))
    assert scheduler.started == 1


def test_run_once_retries():
    scheduler = Scheduler(Store(), Settings(retries=2))
    scheduler.submit(Job("a"))
    assert scheduler.run_once() == 1
''',
    "tests/test_storage.py": '''from orbit.models import Job
from orbit.storage import Store


def test_put_get():
    store = Store()
    store.put(Job("a"))
    assert store.get("a") is not None
    assert store.size() == 1
''',
    "tests/test_http_api.py": '''from orbit.http_api import Api
from orbit.metrics import Metrics
from orbit.scheduler import Scheduler
from orbit.storage import Store
from orbit.config import Settings


def test_submit_returns_queued():
    store = Store()
    api = Api(Scheduler(store, Settings()), Metrics(store))
    assert api.submit("nightly") == {"queued": "nightly"}
''',
}

DOCS = {
    "README.md": "# orbit\n\nA small distributed job scheduler.\n",
    "docs/architecture.md": "# Architecture\n\nStore -> Scheduler -> Worker.\n",
    "pyproject.toml": '[project]\nname = "orbit"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n',
    "LICENSE": "MIT License\n\nCopyright (c) 2025 orbit contributors\n",
}


def force_rmtree(path: Path) -> None:
    """Remove a directory even when git marked objects read-only on Windows."""
    for root, _dirs, names in os.walk(path):
        for name in names:
            with contextlib.suppress(OSError):
                (Path(root) / name).chmod(0o777)
    shutil.rmtree(path)


def run(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env.update({"GIT_AUTHOR_NAME": "orbit", "GIT_AUTHOR_EMAIL": "dev@orbit.example"})
    if env:
        full_env.update(env)
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, env=full_env)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout.decode("utf-8", "replace"))
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise SystemExit("git " + " ".join(args) + " failed")
    return proc


def commit(repo: Path, message: str, author: tuple[str, str], when: datetime,
           body: str = "") -> None:
    stamp = f"{int(when.timestamp())} +0000"
    env = {
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_NAME": author[0],
        "GIT_COMMITTER_EMAIL": author[1],
        "GIT_COMMITTER_DATE": stamp,
    }
    run(["add", "-A"], repo, env)
    args = ["commit", "-m", message]
    if body:
        args += ["-m", body]
    run(args, repo, env)


def function_source(name: str, text: str) -> str:
    return f'''


def {name}(value: int = 0) -> int:
    """{text}."""
    total = value
    for step in range(3):
        total += step
    return total
'''


def build(out: Path) -> Path:
    rng = random.Random(SEED)
    if out.exists():
        force_rmtree(out)
    out.mkdir(parents=True)
    run(["init", "-b", "main"], out)
    run(["config", "user.name", "orbit"], out)
    run(["config", "user.email", "dev@orbit.example"], out)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cursor = now - timedelta(days=DAYS_BACK)
    files: dict[str, str] = {}
    counter = 0

    def write(path: str, content: str) -> None:
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        files[path] = content

    def advance(days: float) -> datetime:
        nonlocal cursor
        cursor = cursor + timedelta(days=days, hours=3)
        return cursor

    def touched(path: str) -> str:
        return files[path]

    def mutate(path: str, old: str, new: str, fallback: str = "") -> None:
        """Replace *old* in a tracked file; append a marker when it is absent."""
        content = touched(path)
        updated = content.replace(old, new, 1)
        if updated == content:
            updated = content + "\n" + (fallback or new) + "\n"
        write(path, updated)

    # ---- milestone 1: bootstrap ------------------------------------------
    for path, content in {**MODULES, **TESTS, **DOCS}.items():
        write(path, content)
    commit(out, "feat: bootstrap the orbit scheduler", AUTHORS[0], advance(0))

    for _ in range(18):
        day = advance(rng.uniform(1.0, 2.4))
        author = AUTHORS[1] if rng.random() < 0.4 else AUTHORS[2]
        target = rng.choice(["orbit/scheduler.py", "orbit/storage.py", "orbit/models.py"])
        counter += 1
        source = function_source(f"feature_{counter}", f"milestone feature {counter}")
        write(target, touched(target) + source)
        commit(out, f"feat: feature {counter} for the scheduler", author, day)

    write("orbit/__init__.py", touched("orbit/__init__.py").replace('"0.1.0"', '"0.2.0"'))
    commit(out, "release: v0.2.0", AUTHORS[0], advance(1))
    run(["tag", "-a", "v0.2.0", "-m", "v0.2.0"], out)

    # ---- milestone 2: the hotspot era ------------------------------------
    for i in range(30):
        day = advance(rng.uniform(0.6, 2.0))
        author = HOTSPOT_AUTHOR if rng.random() < 0.55 else rng.choice(AUTHORS[1:])
        kind = rng.random()
        if kind < 0.5:
            counter += 1
            write(
                "orbit/scheduler.py",
                touched("orbit/scheduler.py")
                + function_source(f"hot_path_{counter}", "scheduler hot path"),
            )
            commit(out, f"feat: scheduler hot path {counter}", author, day)
        elif kind < 0.8:
            mutate(
                "orbit/scheduler.py",
                "processed += 1",
                f"processed += {rng.choice([1, 2])}  # tuned",
                fallback=f"# retry tuning pass {i}",
            )
            commit(out, f"fix: off-by-one when draining retries ({i})", author, day)
        else:
            write(
                "tests/test_scheduler.py",
                touched("tests/test_scheduler.py")
                + f"\n\ndef test_hot_path_{counter}():\n    assert True\n",
            )
            commit(out, "test: cover scheduler hot path", AUTHORS[3], day)

    # ---- the hidden coupling: models.py and its test always move together
    for i in range(7):
        day = advance(rng.uniform(2.0, 4.0))
        mutate("orbit/models.py", "    payload: dict", f"    payload: dict  # schema {i}",
               fallback=f"# schema revision {i}")
        write(
            "tests/test_models.py",
            "from orbit.models import Job\n\n\n"
            f"def test_schema_{i}():\n    assert Job('a').payload == {{}}\n",
        )
        commit(out, f"feat(models): add schema field {i} with its test", AUTHORS[1], day)

    # ---- a genuinely hidden coupling: worker and metrics move together ---
    for i in range(5):
        day = advance(rng.uniform(3.0, 5.0))
        mutate("orbit/worker.py", "        self.done = 0", f"        self.done = 0  # counters {i}",
               fallback=f"# worker counters {i}")
        mutate("orbit/metrics.py", "        return {\"depth\": self.depth()}",
               f"        return {{\"depth\": self.depth(), \"pass\": {i}}}",
               fallback=f"# metrics pass {i}")
        commit(out, f"feat: instrument worker pass {i}", AUTHORS[4], day)

    # ---- milestone 3: branch + merge workflow ----------------------------
    for m in range(6):
        day = advance(2.0)
        run(["checkout", "-b", f"feature/queue-{m}"], out)
        worker = function_source(f"worker_step_{m}", f"worker iteration {m}")
        write("orbit/worker.py", touched("orbit/worker.py") + worker)
        commit(out, f"feat: worker iteration {m}", AUTHORS[4], day)
        counter += 1
        write(
            "tests/test_worker.py",
            "from orbit.worker import Worker\nfrom orbit.scheduler import Scheduler\n"
            "from orbit.storage import Store\nfrom orbit.config import Settings\n\n\n"
            f"def test_tick_{m}():\n    w = Worker(Scheduler(Store(), Settings()))\n"
            "    assert w.tick() >= 0\n",
        )
        commit(out, f"test: worker iteration {m}", AUTHORS[4], day + timedelta(hours=2))
        run(["checkout", "main"], out)
        metric = function_source(f"metric_{m}", f"metric counter {m}")
        write("orbit/metrics.py", touched("orbit/metrics.py") + metric)
        commit(out, f"chore: refresh metrics after queue {m}", AUTHORS[1], day + timedelta(hours=3))
        merge_day = day + timedelta(days=1)
        body = f"Reviewed-by: {REVIEWERS[m % 2]}" if m % 2 == 0 else ""
        stamp = f"{int(merge_day.timestamp())} +0000"
        env = {
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_AUTHOR_NAME": AUTHORS[0][0],
            "GIT_AUTHOR_EMAIL": AUTHORS[0][1],
            "GIT_COMMITTER_NAME": "orbit",
            "GIT_COMMITTER_EMAIL": "dev@orbit.example",
        }
        args = ["merge", "--no-ff", f"feature/queue-{m}", "-m", f"Merge branch 'feature/queue-{m}'"]
        if body:
            args += ["-m", body]
        run(args, out, env)
        cursor = merge_day

    # ---- the refactor month ----------------------------------------------
    for step in range(14):
        day = advance(rng.uniform(0.8, 1.6))
        if step == 0:
            (out / "orbit" / "support").mkdir(parents=True, exist_ok=True)
            init = out / "orbit" / "support" / "__init__.py"
            init.write_text('"""Shared helpers."""\n', encoding="utf-8")
            run(["mv", "orbit/utils.py", "orbit/support/utils.py"], out)
            files.pop("orbit/utils.py", None)
            files["orbit/support/utils.py"] = (out / "orbit" / "support" / "utils.py").read_text(
                encoding="utf-8"
            )
            write(
                "orbit/http_api.py",
                touched("orbit/http_api.py").replace(
                    "from .metrics import Metrics",
                    "from .metrics import Metrics\nfrom .support.utils import slug",
                ),
            )
            commit(out, "refactor: move helpers into the support package", AUTHORS[2], day)
        else:
            target = rng.choice(["orbit/scheduler.py", "orbit/storage.py", "orbit/models.py"])
            mutate(
                target,
                "    total = value",
                "    total = int(value)",
                fallback="# typed accessor cleanup",
            )
            commit(out, "refactor: tighten type handling in the hot path", AUTHORS[2], day)

    write("orbit/__init__.py", touched("orbit/__init__.py").replace('"0.2.0"', '"0.3.0"'))
    commit(out, "release: v0.3.0", AUTHORS[0], advance(1))
    run(["tag", "-a", "v0.3.0", "-m", "v0.3.0"], out)

    # ---- milestone 4: hardening, docs, fixes -----------------------------
    for i in range(34):
        day = advance(rng.uniform(0.4, 1.7))
        kind = rng.random()
        author = HOTSPOT_AUTHOR if rng.random() < 0.45 else rng.choice(AUTHORS[1:])
        if kind < 0.45:
            counter += 1
            target = rng.choice(
                ["orbit/scheduler.py", "orbit/scheduler.py", "orbit/http_api.py", "orbit/worker.py"]
            )
            source = function_source(f"hardening_{counter}", "hardening pass")
            write(target, touched(target) + source)
            commit(out, f"feat: hardening pass {counter}", author, day)
        elif kind < 0.65:
            mutate(
                "orbit/scheduler.py",
                "        return processed",
                f"        return processed  # pass {i}",
                fallback=f"# stale count regression pass {i}",
            )
            commit(out, f"fix: scheduler returned stale count on pass {i}", author, day)
        elif kind < 0.72:
            write(
                "README.md",
                touched("README.md")
                + f"\n## Usage {i}\n\nStart a worker and watch the queue drain.\n",
            )
            commit(out, f"docs: usage section {i}", AUTHORS[3], day)
        elif kind < 0.8:
            mutate(
                "orbit/http_api.py",
                "        return self.metrics.snapshot()",
                f"        return {{**self.metrics.snapshot(), 'rev': {i}}}",
                fallback=f"# api revision {i}",
            )
            commit(out, f"feat: expose API revision {i}", author, day)
        elif kind < 0.9:
            write("pyproject.toml", touched("pyproject.toml") + f"# build {i}\n")
            commit(out, f"build: refresh packaging metadata {i}", AUTHORS[5], day)
        else:
            mutate(
                "orbit/cli.py",
                "    print(json.dumps(api.status()))",
                f"    print(json.dumps({{**api.status(), 'rev': {i}}}))",
                fallback=f"# status revision {i}",
            )
            commit(out, f"feat(cli): expose revision {i} in status", AUTHORS[5], day)

    # ---- final release ---------------------------------------------------
    write("orbit/__init__.py", touched("orbit/__init__.py").replace('"0.3.0"', '"1.0.0"'))
    write("README.md", touched("README.md") + "\n## License\n\nMIT\n")
    commit(out, "release: v1.0.0", AUTHORS[0], advance(1.5))
    run(["tag", "-a", "v1.0.0", "-m", "v1.0.0"], out)

    support = out / "orbit" / "support" / "utils.py"
    marker = support.read_text(encoding="utf-8") + '\n\nVERSION = "1.0.1"\n'
    support.write_text(marker, encoding="utf-8")
    commit(out, "fix: ship the version marker", AUTHORS[5], advance(2))
    run(["tag", "-a", "v1.0.1", "-m", "v1.0.1"], out)

    commits = int(run(["rev-list", "--count", "HEAD"], out).stdout.strip() or b"0")
    print(f"built {out} with {commits} commits")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rebuild the demo repository")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    build(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
