<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-23 — `docs/PRIMER.md` and rule docstring refresh (consolidation)

**Landed:** no logic change. Continuation of PR-22's staleness sweep,
this time on `docs/PRIMER.md` and the docstrings inside `rules/build.smk`
itself.

## What was wrong

`docs/PRIMER.md` is mostly stable domain content (physics doesn't drift),
so this was a narrower fix than PR-22's STACK.md pass:

- Two forward-references to *specific future PR numbers* that were
  written early (PRIMER.md dates to PR-01) and never reconciled with how
  numbering actually turned out: `(PR-19)` on head-dependent hydro
  productivity, `(PR-23)` on ERA5 bias correction. Real PR-19 became
  MMGD; there was no PR-23 until this one. Citing a specific unbuilt
  item's future PR number is inherently fragile - this repo's numbering
  is assigned as work starts, never reserved in advance. Replaced both
  with plain "still PLANNED" notes pointing at `docs/STACK.md` instead.
- The illustrative Snakemake rule in Sec 5.3 (`carga_verificada.parquet`,
  `resources/demand_{tier}.nc`) matched nothing real - not the file
  format, not the rule name, not a wildcard that exists. Replaced with
  the actual `build_demand_t0` rule, and reworded the wildcard teaching
  point to cite `{year}` (real, built) rather than implying `{tier}`
  already works.

Then, checking the actual rule file while fixing the illustration above
surfaced two more, in real code rather than prose:

- `build_generators_t0`'s docstring said "no cost, no availability
  profile yet" - false since PR-09/10 (cost) and PR-14/15/17/18
  (availability). Reworded to say cost/availability are separate rules
  combined downstream, not that the project lacks them.
- `build_network_t0`'s docstring didn't mention hydro or MMGD
  availability at all, despite both being real inputs since PR-18/19.
  Expanded the summary; also clarified that "no real transmission
  physics" is a **permanent** ADR-0006 design choice for T0, not a
  stopgap the way the old wording implied.

## Key files

- `docs/PRIMER.md`
- `rules/build.smk` (docstrings only - `input`/`output`/`script` blocks
  untouched)

## Gotchas

None. Small, mechanical fixes once found - the actual work was reading
carefully enough to find them, not the edits themselves.

## Next PR needs

Nothing blocks on this. This closes PR-22's own "PRIMER.md wasn't
audited this PR" note. Consolidation-phase candidates still open:
- A real fix for PR-20's wind/solar coverage gap - a judgment call, not
  documentation.
- After consolidation: real water values (SDDP), the user's agreed step 2.

## Open questions

None new.
