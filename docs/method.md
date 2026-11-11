# Method notes: what each metric actually computes

This page exists so nobody has to trust a black box. Every formula below is the
one in the code, and every known weakness is stated.

## Bus factor

For each top-level directory, count commits per author (a commit counts once per
directory it touches). Sort the counts descending and take the smallest prefix
that covers at least 50% of the commits (configurable with `--threshold`).

* Bus factor 1 and fewer than 5 commits is reported as `low` risk, not
  `critical`: one commit by one person is not evidence of anything yet.
* Weakness: commit count measures activity, not understanding. A reviewer who
  reads every commit but writes none is invisible to this metric.

## Knowledge concentration (HHI)

Split the history into ten equal buckets of *commits* (not calendar time), then
compute the Herfindahl-Hirschman index of author shares per bucket:
`HHI = sum(share_i^2)`. 1.0 means one author wrote everything in that bucket.

* Equal-commit buckets stop a quiet month from dominating the curve.
* Weakness: HHI reacts to headcount, not to code volume.

## Hotspots (churn x complexity)

* churn = inserted + deleted lines over the whole history of the file.
* complexity = a proxy: lines containing branching keywords plus the maximum
  indentation depth (4 spaces per level), floor 1.
* Each axis is converted to a **percentile rank** within the repository, and a
  file is "high" on an axis when it sits in the top third (rank >= 2/3). The
  four quadrants are danger (high/high), churny (high churn only), fragile
  (high complexity only) and stable.

Percentile ranks matter: churn spans orders of magnitude (one file with 340
lines changed next to files with 20), so normalising by the maximum put every
file but the worst one at the origin and labelled them all "stable". A rank is
scale-free: it answers "is this file unusually hot *for this repository*",
which is the question a maintainer actually has.

The proxy is language-agnostic on purpose: git-story must work on a Python repo
and a Rust repo without shipping one parser per language. It ranks files for a
human to look at; it is not a cyclomatic complexity measurement and is not
comparable across repositories.

## Co-change coupling

For every commit, take the set of changed files (renames excluded, commits with
more than 30 files skipped) and count every unordered pair. Then:

* `together` = commits containing both files
* `confidence` = max(together / commits(A), together / commits(B))
* `support` = together / total commits
* `lift` = together^2 / (commits(A) * commits(B))

High confidence with low support is the interesting case: a private contract
between two files that the rest of the repository never sees. The 30-file cap
exists because a release commit would otherwise couple every file to every
other file and drown the signal.

## Commit size

`XS < 10`, `S < 50`, `M < 250`, `L < 1000`, `XL >= 1000` changed lines
(insertions + deletions, after rename detection).

## Review-less merges

Git does not record pull-request approvals. git-story only looks for
machine-readable trailers in the merge commit message: `Reviewed-by:`,
`Approved-by:`, `Co-authored-by:`, `Signed-off-by:`. A merge without one is
counted as review-less, so **the number is an upper bound**, and the README and
the HTML page say so where the number appears.

## Onboarding ranking

`score = 3 * importers/max_importers + 1.5 * commits/max_commits +
1 * co_change_partners/max_partners`, plus 2 for entry-point filenames
(`__main__.py`, `cli.py`, `main.py`, `index.ts`, ...) and 0.5 when three or
more authors touched the file. Importers come from a real `ast` parse of every
Python file at HEAD; JavaScript and TypeScript use a conservative regex for
relative ES-module and `require` specifiers. Unresolved imports are counted, not
invented.

Ranking is a suggestion, not a verdict: the table prints the evidence
(importers, commits, co-change partners) next to each row so a reader can
disagree with it.
