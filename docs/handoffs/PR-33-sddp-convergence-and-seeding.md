<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-33 — Convergence rigor and RNG seeding

**Landed:**

- `julia/sddp_first_policy.jl`: `SDDP.SimulationStoppingRule()` replaces
  the fixed `iteration_limit=300` PR-32 shipped with; `Random.seed!(seed)`
  (new 6th CLI arg, default 0) fixes SDDP.jl's own internal RNG.
- `rules/sddp.smk`: both policy rules now pass an explicit seed.

Not part of ADR-0005's named stages - a direct response to PR-32's own
"Next PR needs" section, which flagged both gaps as undermining
confidence in its own expectation-vs-CVaR comparison. Chose this over
starting individualized reservoirs (ADR-0005's actual last named stage,
which needs its own superseding ADR and is a much larger undertaking) -
shoring up what's already built before starting something bigger.

## Reproducibility: verified, not just added

Ran the same seeded command twice and diffed the outputs:
`summary.json` was **byte-identical** both times. This is the first PR in
the SDDP epic where re-running produces the same numbers - PR-31 and
PR-32's own handoffs both note run-to-run variation as a real, unresolved
gap; it's resolved now.

## The stopping rule: wired in correctly, but doesn't do what you'd hope

`SDDP.SimulationStoppingRule()` is SDDP.jl's own recommended default -
checks both bound stabilization and agreement between consecutive
out-of-sample simulations, matching PRIMER Sec 4.3's "stop when the gap
is acceptably small" far better than a guessed fixed count. **Checked
directly whether it actually triggers, rather than assuming wiring it in
was sufficient**: it does not, within a 1000-iteration safety cap (raised
from 300). `status: iteration_limit` both times, for both risk measures.

Two concrete signals worth carrying forward, not just the non-convergence
itself:

- **The bound was still slowly rising** at iteration 1000 (2.53bn to
  2.56bn between iterations 250 and 1000) - real, if slow, ongoing
  improvement, not a plateau the rule failed to notice.
- **Numeric issues rose with iteration count**: 0 at 50 iterations
  (PR-31), low single digits at 300 (PR-32), **57 at 1000**. This is a
  real, escalating signal - as cuts accumulate (11,000 at 1000 iterations
  vs. 3,300 at 300), the subproblems' LP conditioning may be genuinely
  degrading, not just taking longer to converge. Worth investigating
  directly (e.g. `SDDP.numerical_stability_report`, cut selection/deletion
  settings) rather than raising the iteration cap indefinitely, which
  would likely just push the same problem further out.

Both are named explicitly in `known_limitations()`, replacing PR-32's
more hedged "not independently tuned" language now that there's a
concrete, checked answer.

## The result this made possible: a coherent synthesis, not just a bigger number

With the seed fixed and 1000 iterations (vs. 50/300 before), expectation
and CVaR now converge to **nearly identical tail outcomes**:

| | Expectation | CVaR (lambda=0.5, alpha=0.1) |
|---|---|---|
| Simulated mean cost | R$266.2m | R$266.6m |
| P90 load shed | 30,090.5 | **30,090.5** (identical) |
| S's mean load shed | 17,356 | 17,365 |

At 50/300 iterations (PR-31/32), the two policies looked meaningfully
different, and it wasn't clear whether that reflected real risk-averse
behavior or just noise. At better convergence, they converge to
**essentially the same tail outcome**.

**First hypothesis tried, and refuted by checking rather than left
standing**: is S's shortfall simply a capacity problem no amount of
reservoir management could fix regardless of water? Checked directly -
S's `hydro_mw` (15,505.5) + `thermal_mw` (3,635.2) = **19,140.7 MW total
capacity, comfortably above S's own peak monthly demand (15,666.3 MW)**,
a 3,474 MW margin. So no - this is genuinely a **water availability**
problem (hydro is bounded by storage-plus-inflow, not nameplate), not a
capacity one. That refutes the first, simpler explanation - worth
recording that it was tried and ruled out, not just the one that survived.

**The better-supported explanation, tied directly to PR-31's own most
significant named limitation**: inflow scenarios are drawn i.i.d. per
month (PAR(1)'s real fitted persistence, phi up to 0.81 for S, is not yet
wired into SDDP's state). A risk-averse policy can only hedge against
what it can see coming from the *current* reservoir state - it has no
signal, within this model, that a run of dry months is more likely to
follow another dry month, even though the real underlying process
genuinely has that structure. S's own reservoir is also comparatively
small relative to its demand (`ear_max_mwmes` = 20,459, roughly 1.5
months of average demand) and its inflow scenarios span a wide range
(median 6,246 MWmed, minimum 710 MWmed - more than 8x apart). A policy
that cannot anticipate an oncoming multi-month dry stretch has much less
room to build the reserve that would matter, which is a plausible reason
CVaR's tail benefit shows up only weakly here. **This is temporal
persistence's absence showing up concretely in the results**, not an
abstract caveat - a real, useful sharpening of PR-31's open question,
not a resolution of it.

## Gotchas

- Regenerating `resources/sddp_inputs/*.parquet` was needed before any of
  this session's direct Julia runs - they're gitignored intermediate
  artifacts, cleaned up at the end of PR-32, same as every prior PR's
  gitignored outputs.
- Same `python -c`/Julia-equivalent inline-quoting caution as every prior
  PR - all exploratory checks (`@doc SDDP.SimulationStoppingRule`, `@doc
  SDDP.BoundStalling`) used scratch `.jl` files.

## Next PR needs

1. **Temporal persistence inside the policy** (PR-31's still-open
   finding, now the most directly implicated by this PR's own result) -
   state-augmented AR inflow, so the policy can actually see an oncoming
   dry stretch coming from consecutive low-inflow months, the way the
   real fitted PAR(1) process does. The single most promising next step
   for actually moving S's tail risk, given the capacity hypothesis is
   now ruled out.
2. **Investigate the rising numeric-issues count** - directly, not by
   raising the iteration cap further.
3. Per ADR-0005's actual last named stage: **individualized reservoirs**
   - needs its own ADR, superseding ADR-0005, given the scale of the
   undertaking (150+ reservoirs vs. today's 4 subsystem-aggregated ones).

## Open questions

- Whether adding temporal persistence to the policy (next PR needs #1)
  actually narrows the CVaR/expectation gap in the direction theory
  predicts, or whether S's small reservoir-to-demand ratio dominates
  regardless - a real, testable question the next PR should report on
  either way, not just implement toward.
