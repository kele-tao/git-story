# Changelog

All notable changes to this project are documented here.

## 1.0.0 -- 2026-11-23

The first public release. Everything below is implemented, tested and covered
by the deterministic demo repository in `examples/demo_repo`.

### Added

* History mining through the real `git` binary: commits, authors, per-file
  inserted/deleted lines after rename detection, merge graph and tags.
* `chronicle` -- a month-by-month narrative with commits auto-classified into
  feature / fix / refactor / docs / test / build / release / chore themes.
* `story --format html` -- a self-contained page with inline SVG charts,
  findings, bus factor, hotspots, coupling and a full timeline.
* `bus-factor` -- per-directory knowledge concentration with a risk label.
* `hotspots` -- churn x complexity quadrants using a language-agnostic proxy.
* `coupling` -- co-change pairs ranked by confidence, support and lift.
* `onboard` -- the ten files a newcomer should read first, ranked from reverse
  imports (real `ast` parse), churn and co-change centrality.
* `refactor` -- refactor vs feature share per month.
* `--json` on every command, `--fail-on` quality gates and documented exit
  codes (0 ok, 1 gate failed, 2 usage error).
* `benchmarks/make_demo_repo.py` -- regenerates the 130+ commit demo repo.
* `benchmarks/run.py` -- generates `docs/benchmark.md` from real timings.
