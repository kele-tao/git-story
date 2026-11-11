# Roadmap

Anything that is not shipped is listed here rather than promised in the README.
Each item says what is missing today and why it is not in 1.0.

## 1. Review data from hosted forges

**Today:** "review-less merges" counts merge commits that lack a
`Reviewed-by:`/`Approved-by:` trailer, which is an upper bound because git
has no approval record.

**Next:** an optional `--github` mode that reads pull-request reviews through a
token and stores nothing by default. Deliberately out of 1.0: it would add a
network dependency and a credential to a tool whose selling point is that it is
offline and pure-stdlib.

## 2. Real complexity per language

**Today:** hotspots use a language-agnostic proxy (branchy lines + maximum
indentation), which ranks files for a human but is not a cyclomatic complexity
number.

**Next:** optional adapters for `rope`/tree-sitter when installed, falling back
to the proxy. Out of 1.0 because shipping one parser per language would break
the "works on any repo, no dependencies" promise.

## 3. Author identities across mailmaps

**Today:** authors are keyed by the `Author` name as git reports it. A person
who commits from two machines with two names counts as two authors, which
inflates headcount and can flatter the bus factor.

**Next:** honour `.mailmap` (git already supports it) and surface a warning when
distinct names share an email domain. Needs care: merging identities can also
hide ownership.

## 4. Ownership by code volume, not commit count

**Today:** bus factor is computed from commit counts per directory.

**Next:** a second view weighted by surviving lines (blame), which needs
`git blame` runs that are too slow for a CLI default on large repositories.
Would appear behind `--blame`.

## 5. Interactive HTML

**Today:** the page is fully static: no scripts, no filters, no drill-down.

**Next:** an optional `--interactive` flag that adds a filter box for
directory/author. Kept out of the default because a self-contained page that
renders identically everywhere is worth more than filters nobody asked for.

## 6. Faster co-change on huge histories

**Today:** co-change is capped at 30 files per commit and is quadratic in files
per commit, which is fine at the 3000-commit / 60-file scale measured in
`docs/benchmark.md`.

**Next:** an inverted index over commit ids to avoid re-scanning pair lists for
repositories with very wide commits (generated code, vendored dependencies).
