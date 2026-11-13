# Contributing

Thanks for taking git-story seriously. Two rules matter more than style here:
**every number must be reproducible**, and **the tool must work on any
repository**, including ones with thousands of commits and years of history.

## Development setup

```bash
git clone https://github.com/kele-tao/git-story
cd git-story
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

Python 3.10+ and git 2.20+ are required. There are no runtime dependencies.

## Try it against something real

```bash
python benchmarks/make_demo_repo.py
python -m gitstory summary examples/demo_repo
python -m gitstory story examples/demo_repo --format html --out /tmp/story.html
```

Point it at your own repository as well. Weird histories (squashed imports,
svn bridges, capitalization-only renames, CRLF churn) are exactly what the test
fixtures should grow to cover.

## What a good change looks like

1. **A failing test first.** `tests/` builds real repositories with
   `conftest.RepoBuilder`; no mocking of gitstory's own modules.
2. **A deterministic result.** If your change involves randomness or a clock,
   thread a seed or a `now` argument through so tests stay stable.
3. **An honest report of the limit.** If a heuristic can be wrong, say so in
   the docstring, the CLI output and the README. Silent guessing is the one
   thing this project will not ship.
4. **Performance in mind.** Co-change and hotspot analysis must stay linear in
   commits; the 3000-commit benchmark in `docs/benchmark.md` is the reference.

## Commit messages

The project analyses commit messages, so it would be embarrassing not to follow
the convention it parses. Use `feat:`, `fix:`, `refactor:`, `docs:`,
`test:`, `build:` or `chore:` prefixes with an optional scope.

## Adding a new analysis

* Put pure functions in `src/gitstory/metrics.py` (data in, dataclass out).
* Render it in `src/gitstory/reports.py` (terminal) and optionally in
  `src/gitstory/html.py`.
* Expose it as a subcommand in `src/gitstory/cli.py` and add it to the
  `--json` payload.
* Document the formula in the README's "How it works" section and add it to
  the tests.

## Reporting bugs

Include `git-story --version`, your Python and git versions, the exact command
and the output. If a number looks wrong, say what you expected and why -- a
counterexample is worth more than a paragraph.
