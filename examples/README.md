# examples/

## demo_repo

A real git repository with 130+ commits, six authors, four tags, a merge
workflow, a dedicated refactor month and one obvious hotspot file.

It is **generated**, not copied, so anyone can reproduce every number in the
README:

```bash
python benchmarks/make_demo_repo.py
python -m gitstory summary examples/demo_repo
```

The generator (`benchmarks/make_demo_repo.py`) is seeded (seed 20240607) and
anchors its commit dates to the day you run it, so the *shape* of the history is
stable while the absolute dates move. That is why the README quotes shape-level
numbers (commit count, author count, the hotspot file) and the exact numbers in
`docs/` are always accompanied by the command that regenerates them.

Commit identities are fixed to the six demo authors on purpose: the demo shows
what a real small team's history looks like, not what one machine's `git config`
happened to be.
