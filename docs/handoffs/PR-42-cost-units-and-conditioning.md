<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-42 — real R$ costs, and the conditioning ceiling removed

**Landed:** `julia/sddp_first_policy.jl` (`HOURS_PER_MONTH`, `MONEY_SCALE`,
stage objective, reporting conversions, `KNOWN_LIMITATIONS`),
`rules/sddp.smk` (`SDDP_ITERATION_LIMIT` 1000 → 4000).

Two defects were queued as independent: PR-39's R$-per-hour unit error and
PR-39's LP conditioning ceiling. **They are not independent**, and finding
that out is this PR's main result.

## Fix 1: the objective was a rate, not a cost

The stage objective was `marginal_cost [R$/MWh] * generation [MW]`, which
is **R$/hour**. No hours-in-month factor existed anywhere, so every
"expected annual cost" reported from PR-31 to PR-41 was short by ~730x.
`LOAD_SHED_COST = 10_000` was correctly copied from `build_network.py`,
but PyPSA applies snapshot weightings automatically and SDDP.jl does not —
right constant, wrong unit context.

Fixed with `HOURS_PER_MONTH` (real month lengths, non-leap, summing to
exactly 8760 h/year) applied per stage. Real month lengths rather than a
flat 730 because a month's energy is its mean MW times *its own* hours;
this mildly reweights stages against each other, so the policy shifts
slightly — correct, not a side effect to suppress.

## Fix 2: which immediately broke training — and revealed the real cause

Applying Fix 1 **alone** made things dramatically worse, measured not
predicted:

| | before Fix 1 | after Fix 1 alone |
|---|---|---|
| objective magnitude | ~7e8 | ~5e11 |
| training crashes at | iteration 2277 | **iteration ~600** |
| HiGHS status | `OPTIMAL` + `INFEASIBLE_POINT` | **`OTHER_ERROR`** |

Correct units are simply not trainable at raw R$ scale: objective
magnitudes around 5e11 against constraint-matrix coefficients of 1 is an
~11-order spread, and the solver stopped merely returning bad points and
began failing outright.

The fix is `MONEY_SCALE = 1e6` — solve in **millions of R$**, convert back
to R$ at every reporting point. A uniform positive scaling of a
minimisation objective cannot change its argmin, so the policy is
unaffected; only the numbers the solver handles change.

**This also removed PR-39's ceiling entirely**, which is the finding worth
carrying forward:

| | PR-39 (before) | PR-42 (after) |
|---|---|---|
| expectation | crash at 2277, **51** numeric issues | **4000 iterations, 0** numeric issues |
| CVaR | crash at 1569, **40** numeric issues | **4000 iterations, 2** numeric issues |

So PR-39's diagnosis — "the LP degrades as *cuts accumulate*" — was
**wrong about the mechanism**. The cut count was never the problem; the
objective's raw magnitude was. PR-39's *measurements* were sound and
reproducible, but the causal story attached to them was not, and it took
deliberately making the problem worse (Fix 1) to expose it.

`SDDP_ITERATION_LIMIT` accordingly rises 1000 → 4000.

## Real results (4000 iterations, 1000 simulations, seed 0)

| | expectation | CVaR |
|---|---|---|
| simulated mean cost | **R$ 342.9 bn** | **R$ 378.9 bn** |
| risk-adjusted bound | R$ 566.4 bn | R$ 711.2 bn |
| mean load shed | 38,452 MW-months | 43,066 MW-months |
| P90 load shed | 56,818 MW-months | 61,417 MW-months |
| numeric issues | 0 | 2 |

The cost figures are now real R$ and land where a sanity check says they
should: ~38,000 MW-months shed × ~730 h × R$10,000/MWh ≈ R$280 bn of
load-shedding cost alone, plus thermal. They are enormous because this
reduced model has no inter-subsystem transmission and subsystem S
structurally cannot serve its own demand — a known artifact since PR-11,
not a new problem.

## What did NOT get fixed, stated plainly

**The CVaR anomaly survives.** At 4000 iterations CVaR's P90 load shed
(61,417) is still *above* expectation's (56,818) — backwards from theory.
It is also unstable in iteration count: at 1000 iterations post-fix the two
were nearly identical (58,480 vs 58,078, CVaR marginally *better*), and at
4000 the gap reopens in the wrong direction.

So the conditioning fix did **not** explain it, which leaves ADR-0009's
hypothesis as the leading candidate: the policy is blind to temporal
persistence (PR-40), and **a risk measure cannot hedge a state variable it
cannot observe**. That remains untestable until ADR-0009's Markovian
policy graph is implemented.

**Still not converged.** 4000 is a measured-*safe* value, not a converged
one — the bound was still climbing at iteration 4000 (+7.7% from 1000).
Where it actually flattens is unmeasured.

## Gotchas

- **`cuts.parquet` is in MILLIONS of R$ per MWmes**, not R$. The eventual
  PyPSA/linopy coupling must multiply by `MONEY_SCALE` before adding cuts
  to a PyPSA objective expressed in R$. `summary.json` now carries
  `cuts_money_scale` and `cuts_units` so this is discoverable from the
  artifact rather than only from this file.
- Mild unit tension worth knowing: the MWmes storage convention treats
  every month as one normalized "month" unit, while the cost conversion
  uses each month's real hours. That inconsistency is inherent to Brazil's
  own NEWAVE convention, not introduced here, but it means a MWmes carried
  into February buys slightly fewer real MWh than one carried into January
  and the model does not represent that.
- A 4000-iteration run of both policies takes ~8.5 minutes through
  Snakemake, up from ~2 at 1000.

## Next PR needs

**Implement ADR-0009** (Markovian policy graph) — now the highest-value
remaining item, since it is the only outstanding candidate explanation for
the CVaR anomaly and the epic's headline results stay misleading until the
policy can actually see hydrological regime. ADR-0009's acceptance test is
already specified: water must be worth more in the dry state than the wet
state at identical storage.

Then: find where the bound actually flattens now that training is not
capped by a crash; the REE-level policy (ADR-0008/PR-37); and the Phase 7
gate's backtest against real ONS CMO/PLD/EAR trajectories — which is now
meaningfully closer, since comparing against published CMO requires cost
figures in real R$, which did not exist before this PR.

## Open questions

- Would an even smaller `MONEY_SCALE` (billions) buy more headroom, or is
  4000 iterations already past the point of diminishing returns? Untested.
- PR-39's handoff attributes the ceiling to cut accumulation. That
  explanation is now known to be wrong but is left in place as written,
  per the project's practice of correcting forward rather than rewriting
  history — this file is the correction.
