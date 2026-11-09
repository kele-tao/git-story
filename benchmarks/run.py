"""Benchmark git-story on repositories of increasing size.

    python benchmarks/run.py
    python benchmarks/run.py --commits 500 2000 5000

The benchmark builds a synthetic repository with a controlled number of
commits, then times the full pipeline: history mining, every analysis, the
terminal reports and the HTML page. Nothing here is estimated -- the numbers in
docs/benchmark.md come from this script on the machine that ran it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gitstory.classify import classify  # noqa: E402
from gitstory.history import scan  # noqa: E402
from gitstory.html import StoryOptions, render_story  # noqa: E402
from gitstory.imports import build_import_graph  # noqa: E402
from gitstory.metrics import (  # noqa: E402
    bus_factor,
    cochange,
    findings,
    hotspots,
    knowledge_concentration,
    monthly,
    refactor_ratio,
    size_distribution,
)
from gitstory.onboard import onboard, read_head_files  # noqa: E402
from gitstory.reports import chronicle, summary  # noqa: E402

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "bench",
    "GIT_AUTHOR_EMAIL": "bench@example.com",
    "GIT_COMMITTER_NAME": "bench",
    "GIT_COMMITTER_EMAIL": "bench@example.com",
}
MESSAGES = ["feat: add", "fix: correct", "refactor: split", "docs: explain"]
FENCE = chr(96) * 3


def git(cwd: Path, *args: str, env: dict | None = None) -> None:
    full = {**os.environ, **GIT_ENV}
    if env:
        full.update(env)
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, env=full)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))


def _blob(mark: int, content: str) -> bytes:
    payload = content.encode("utf-8")
    return (
        b"blob\nmark :" + str(mark).encode() + b"\ndata " + str(len(payload)).encode()
        + b"\n" + payload + b"\n"
    )


def build_repo(root: Path, commits: int, files: int = 60) -> None:
    """Create *commits* commits across *files* modules written by six authors.

    Commits are streamed through the git fast-import plumbing: thousands of
    individual git commit calls take minutes on Windows, while the stream takes
    well under a second and stays byte-deterministic.
    """
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "bench")
    git(root, "config", "user.email", "bench@example.com")

    contents: dict[str, str] = {}
    chunks: list[bytes] = []
    stamp = 1_600_000_000
    mark = 0
    for index in range(commits):
        stamp += 3600
        author = f"dev{index % 6}"
        target = f"pkg/mod_{index % files:03d}.py"
        contents[target] = contents.get(target, "") + (
            f"\n\ndef fn_{index}(x: int = 0) -> int:\n    return x + {index}\n"
        )
        touched = [target]
        if index % 7 == 0:
            neighbour = f"pkg/mod_{(index + 1) % files:03d}.py"
            contents[neighbour] = contents.get(neighbour, "") + f"\n# paired with {target}\n"
            touched.append(neighbour)

        files_block = b""
        for path in touched:
            mark += 1
            chunks.append(_blob(mark, contents[path]))
            files_block += b"M 100644 :" + str(mark).encode() + b" " + path.encode() + b"\n"

        identity = (
            author.encode() + b" <" + author.encode() + b"@example.com> "
            + str(stamp).encode() + b" +0000"
        )
        message = f"{MESSAGES[index % 4]} {target}".encode()
        mark += 1
        chunks.append(
            b"commit refs/heads/main\nmark :" + str(mark).encode() + b"\nauthor " + identity
            + b"\ncommitter " + identity + b"\ndata " + str(len(message)).encode() + b"\n"
            + message + b"\n" + files_block + b"\n"
        )
    stream = b"".join(chunks)
    proc = subprocess.run(
        ["git", "fast-import", "--quiet", "--done"],
        cwd=str(root),
        input=stream + b"done\n",
        capture_output=True,
        env={**os.environ, **GIT_ENV},
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    git(root, "reset", "--hard", "main")


def timed(fn) -> tuple[float, object]:
    start = time.perf_counter()
    value = fn()
    return round(time.perf_counter() - start, 4), value


def measure(repo: Path) -> dict:
    row: dict[str, float] = {}
    row["scan"], history = timed(lambda: scan(repo))
    row["read_head_files"], sources = timed(lambda: read_head_files(history))

    def analyses() -> dict:
        classified = [classify(c) for c in history.commits]
        return {
            "classified": len(classified),
            "budget": bus_factor(history),
            "spots": hotspots(history, sources=sources),
            "pairs": cochange(history),
            "months": monthly(history),
            "ratio": refactor_ratio(history),
            "sizes": size_distribution(history),
            "facts": findings(history),
            "concentration": knowledge_concentration(history),
            "graph": build_import_graph(sources),
            "guide": onboard(history, sources=sources),
        }

    row["analyses"], result = timed(analyses)
    row["import_edges"] = float(result["graph"].edge_count)
    row["summary_text"], text = timed(lambda: summary(history, color=False))
    row["chronicle_text"], chronicle_text = timed(lambda: chronicle(history, color=False))
    row["render_html"], html = timed(
        lambda: render_story(history, StoryOptions(title="benchmark"), sources=sources)
    )
    row["html_kb"] = round(len(html.encode("utf-8")) / 1024, 1)
    row["text_bytes"] = float(len(text) + len(chronicle_text))
    row["commits"] = float(len(history.commits))
    row["authors"] = float(len(history.authors))
    row["files_at_head"] = float(len(sources))
    return row


def render_markdown(payload: dict, command: str) -> str:
    rows = payload["rows"]
    lines = [
        "# Benchmark",
        "",
        "Generated by running the real pipeline on synthetic repositories:",
        "",
        FENCE + "bash",
        command,
        FENCE,
        "",
        f"Python {payload['python']} on {payload['platform']}.",
        "",
        "| commits | authors | files | scan | analyses | HTML | summary | total | HTML size |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        total = row["scan"] + row["analyses"] + row["render_html"] + row["summary_text"]
        lines.append(
            "| " + f"{int(row['commits']):,} | {int(row['authors'])} | "
            f"{int(row['files_at_head'])} | {row['scan'] * 1000:.0f} ms | "
            f"{row['analyses'] * 1000:.0f} ms | {row['render_html'] * 1000:.0f} ms | "
            f"{row['summary_text'] * 1000:.0f} ms | **{total:.2f} s** | "
            f"{row['html_kb']:.0f} KB |"
        )
    lines.extend(
        [
            "",
            "Raw numbers: benches/results.json next to this file.".replace("benches", "benchmarks"),
            "",
            "Notes:",
            "",
            "* " + chr(96) + "scan" + chr(96) + " is dominated by the " + chr(96) + "git log"
            + chr(96) + " subprocess, not by Python parsing.",
            "* " + chr(96) + "analyses" + chr(96) + " runs the classifier over every commit "
            "plus bus factor, hotspots, co-change, onboarding and the import graph.",
            "* The HTML page embeds every chart as inline SVG and makes no network requests.",
            "* Co-change is quadratic in files-per-commit, so it is capped at 30 files per "
            "commit: a release commit must not couple the whole repository to itself.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="benchmark git-story")
    parser.add_argument("--commits", type=int, nargs="+", default=[200, 1000, 3000])
    parser.add_argument("--files", type=int, default=60)
    parser.add_argument("--out", default=str(ROOT / "docs" / "benchmark.md"))
    parser.add_argument("--json", default=str(ROOT / "benchmarks" / "results.json"))
    args = parser.parse_args(argv)

    rows = []
    work = ROOT / "benchmarks" / ".work"
    for count in args.commits:
        repo = work / f"repo_{count}"
        print(f"building a {count}-commit repository ...", flush=True)
        build_repo(repo, count, args.files)
        print("measuring ...", flush=True)
        rows.append(measure(repo))
        shutil.rmtree(repo, ignore_errors=True)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "rows": rows,
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    command = "python benchmarks/run.py --commits " + " ".join(
        str(int(r["commits"])) for r in rows
    )
    markdown = render_markdown(payload, command)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
