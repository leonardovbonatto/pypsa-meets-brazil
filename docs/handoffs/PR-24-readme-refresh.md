<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-24 — `README.md` refresh (consolidation)

**Landed:** no logic change. Third and (for now) final stop in the
PR-22/23 documentation-staleness sweep: the repo's most visible file.

## What was wrong

Checked against actual repo state rather than assumed:

- The status banner read **"pre-alpha. Scaffolding only. Nothing here
  solves a network yet."** False since PR-11 (first successful
  `n.optimize()`), and the single most misleading line found in this
  whole sweep - it's the first thing anyone reads, including a reviewer
  deciding whether the project is worth their time. Replaced with an
  honest one: T0 solves end-to-end against real 2024 data, hydro is a
  backcast (ADR-0007) not real water-value physics, T1-T3 not started.
- The `Layout` section listed `data/` and `julia/` as existing top-level
  directories. Checked with `ls` — neither exists. Split them into a
  clearly-marked "planned, not yet created" group rather than mixing them
  in with the real ones.

Checked and left alone: the tier table (T0-T3) and the SDDP.jl decoupling
diagram are explicitly describing the *target* architecture, consistently
labelled as such by the surrounding prose ("this project builds one, in
four tiers") - not a "current state" claim the way the status banner was,
so not in scope for this kind of fix. The `Getting started` commands were
verified to still work exactly as written (`pixi run snakemake -n`).

## Key files

- `README.md` — the only file changed besides the changelog and this
  handoff.

## Gotchas

None. Same pattern as PR-22/23: the fix is finding the stale claim, not
writing it.

## Next PR needs

Nothing blocks on this. This is likely the last pure-documentation
consolidation PR unless a future session notices drift elsewhere
(`CONTRIBUTING.md` and `Brazilian-Grid-in-PyPSA.md` weren't audited).
Real remaining consolidation-phase work:
- A real fix for PR-20's wind/solar coverage gap - a judgment call, not
  documentation.
- After consolidation: real water values (SDDP), the user's agreed step 2.

## Open questions

None new.
