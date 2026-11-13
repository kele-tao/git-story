# Security policy

## Scope

git-story is a read-only analysis tool. It shells out to `git` with an explicit
argument list, never through a shell, and it never executes repository content.

* It runs only read-only git plumbing and porcelain commands
  (`rev-parse`, `log`, `ls-tree`, `show`, `for-each-ref`).
* It sets `GIT_TERMINAL_PROMPT=0` and `GIT_OPTIONAL_LOCKS=0` so a run can never
  block on credentials or take a lock.
* It does not fetch, push, checkout or modify the repository.
* The generated HTML is fully self-contained: no scripts, no external fonts, no
  network requests. Every value interpolated into the page is HTML-escaped,
  including commit subjects and file names.
* Import parsing uses `ast.parse` on Python sources: it never imports or
  executes the analysed code.

## Reporting a vulnerability

Open a private security advisory on
https://github.com/kele-tao/git-story/security/advisories/new or email the
maintainer listed on the GitHub profile. Please include a reproduction; we aim
to respond within seven days.

## Supported versions

Only the latest release receives fixes. git-story has no runtime dependencies,
so there is no dependency CVE surface beyond Python and git themselves.
