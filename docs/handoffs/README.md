<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Session handoff notes

One file per pull request: `PR-NN-short-slug.md`. Written at the end of the session
that produced the PR, committed with it.

This is not documentation for users — it is a note to the *next session*, which
starts with no memory of this one. Twenty to forty lines. The cost is a minute; the
saving is a session spent rediscovering what you already learned.

**Record the things that are not in the diff:** dead ends, upstream quirks, why an
obvious approach was rejected, what surprised you.

## Template

```markdown
# PR-NN — Title

**Landed:** what actually merged, in three or four bullets.

**Key files:** the two or three a follow-up session must read first.

**Data dictionaries added/changed:** paths under `docs/data-dictionary/`.

**Gotchas:** upstream quirks, encoding traps, silent unit changes, undocumented
nulls, anything that cost more than ten minutes to figure out.

**Dead ends:** what was tried and abandoned, and why — so nobody retries it.

**Next PR needs:** the specific state, files or decisions the follow-up depends on.

**Open questions:** anything deferred, with the issue number if one was opened.
```

## Why this matters here

Brazilian sector data is full of traps that cost real time and are invisible in a
diff: semicolon-delimited CSVs with period decimals from ONS but comma decimals in
the XLSX twins, mixed encodings, plant names that differ between ANEEL SIGA and ONS
registries, reservoir volumes quoted sometimes as percentage of useful volume and
sometimes absolute, and deck files in fixed-width Fortran layouts.

Each of those, written down once, is a session saved.
