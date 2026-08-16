<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-21 — `meta.yml` now runs on push, not just pull_request

**Landed:** `.github/workflows/meta.yml` triggers on `push: branches:
[main]` as well as `pull_request`. `META_BASE_REF` is now computed
per-event: a PR's base branch for `pull_request`, `github.event.before`
(the commit before the push) for `push`.

## Why this was worth a PR

Flagged as an open item since PR-13's handoff and repeated in every state
summary since: `meta.yml` only ever triggered on `pull_request`, but this
project's whole history (PR-01 onward, ADR-0001's explicit choice for
solo work) pushes straight to `main`. The workflow existed, was correctly
written for the PR case, and had simply **never run once** — the
changelog/provenance/ADR-numbering checks it exists to enforce were only
ever checked locally, by hand, every session. A real CI gap, not a
hypothetical one.

## Key files

- `.github/workflows/meta.yml` — the only file changed besides the
  changelog and this handoff.
- `scripts/check_meta.py::check_changelog()` — unchanged, but worth
  reading to see what `META_BASE_REF` actually feeds: `git diff
  --name-only base...HEAD`, so it needs any valid commit-ish, not
  specifically a branch name. `github.event.before` (a raw SHA) works
  the same as `origin/<branch>` did for the PR case.

## Verified

Simulated the push-event path locally (not fully testable pre-merge,
since a `push` trigger needs an actual push to fire):
```bash
META_BASE_REF=$(git rev-parse HEAD~1) pixi run -e dev python scripts/check_meta.py
```
Returned `meta checks ok`, confirming a raw SHA base works identically to
the PR case's `origin/<branch>` ref. YAML parsed with `yaml.safe_load`
before committing.

**Real confirmation comes from the very next push after this one** — check
`gh run list` for a `meta` run against a `push` event, not just `lint`/`test`.

## Dead ends

None — this was a small, well-understood fix once the cause (event
mismatch, not a logic bug in `check_meta.py`) was identified.

## Next PR needs

Nothing blocks on this. Still open from PR-19/20:

- Roraima's Jan-2026 SIN connection (unverified in-repo; out of scope for
  the 2024 reference year regardless).
- The wind/solar capacity-factor coverage gap (PR-20) — a real fix (cap
  `p_nom` to tracked capacity, or a second CF source) is future work, not
  blocked on anything here.
- After consolidation: real water values (SDDP), the user's agreed step 2.

## Open questions

None new.
