<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-22 — `docs/STACK.md` refresh (consolidation)

**Landed:** no code change. `docs/STACK.md` updated to match the state
through PR-21 — it had been visibly stale since roughly PR-09, and every
state summary since noted it without anyone actually fixing it.

## What was wrong, specifically

Found by reading the whole document end to end, not by grepping for one
symptom:

- The top "read this twice" box still said hydro was **unconstrained and
  free** — true through PR-15, fixed by the PR-17/18 backcast. It didn't
  mention ADR-0007's circularity caveat or PR-20's wind/solar coverage
  finding at all.
- **"GitHub Actions — BUILT, but never yet executed"** / "the repository
  has no remote yet" — false since PR-03/04; every PR since has confirmed
  CI green via `gh run watch`. This was the most misleading line in the
  document, because it actively contradicts something a reader could
  verify in ten seconds.
- Test count said **49**, actual is **210**.
- The Layer 5 PyPSA section's "what exists today" and the third gotcha
  box both narrated the pre-PR-17 degenerate-model state as current.
- The pinned-dependency list (Layer 1) didn't list `pypsa` or `highspy`,
  both real dependencies since PR-06/11.
- The file map didn't name `build_links.py`, `build_availability.py`,
  `build_hydro_availability.py`, `build_mmgd.py`, `solve_network.py`, or
  `_ons.py` — half the pipeline's actual scripts.

## Approach

Fixed facts in place rather than restructuring — same sections, same
diagrams, same teaching voice, only the stale claims changed. Where a
paragraph told a debugging story that was true *at the time* (the "hydro
exceeds demand in all 8,784 hours" narrative), kept it and appended an
"Update, PR-17/18" / "Update, PR-20" paragraph rather than deleting
history that's genuinely useful for understanding how the finding was
made.

## Key files

- `docs/STACK.md` — the only substantive change.

## Gotchas

None technical. The main risk was scope creep — STACK.md is 800+ lines
and it would have been easy to turn a "fix what's wrong" pass into a
full rewrite. Stayed to verified-stale claims only.

## Next PR needs

Nothing blocks on this. Consolidation-phase candidates still open:
- A real fix for PR-20's wind/solar coverage gap (cap `p_nom`, or a
  second capacity-factor source) — a judgment call, not documentation.
- `docs/PRIMER.md` wasn't audited this PR; worth the same treatment if a
  future session notices drift there.
- After consolidation: real water values (SDDP), the user's agreed step 2.

## Open questions

None new.
