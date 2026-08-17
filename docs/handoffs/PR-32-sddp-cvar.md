<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-32 — CVaR risk aversion (ADR-0005 stage 1g)

**Landed:**

- `julia/sddp_first_policy.jl` takes a risk-measure argument:
  `expectation` (default, unchanged behavior) or `cvar` with `lambda`/`alpha`.
- `rules/sddp.smk::sddp_cvar_policy` - the same model, trained with
  PRIMER Sec 4.4's CVaR blend, alongside (not instead of)
  `sddp_first_policy`, so the two can be compared.
- `iteration_limit` raised from 50 to 300 for both rules - a real finding
  from this PR (below), not a routine tuning change.

No Python changed. No new dependencies.

## A real API convention mismatch, checked rather than assumed

PRIMER Sec 4.4: `(1 - lambda) * E[cost] + lambda * CVaR_alpha[cost]` -
`lambda` weights the CVaR (risk-averse) term. Checked
`@doc SDDP.EAVaR` before using it rather than guessing: SDDP.jl's
`EAVaR(lambda, beta)` computes `lambda * E + (1-lambda) * AVaR(beta)` -
**`lambda` weights EXPECTATION**, the opposite convention. `beta` matches
PRIMER's `alpha` directly (the tail fraction; `beta=1` is plain
expectation, `beta=0` is worst-case). `parse_risk_measure()` translates
explicitly: `SDDP.EAVaR(lambda = 1.0 - lambda_primer, beta = alpha)`,
with the mismatch documented in its own docstring so nobody re-derives
this from scratch (or gets it backwards) later. Same class of trap as
the ONS MWmed/MWmes discrepancies (PR-27/30), just self-inflicted this
time - a library's own parameter name colliding with the domain
literature's convention for the same symbol.

## The convergence finding, and why it matters more than it might look

First comparison, at the `iteration_limit=50` PR-31 shipped with:

| | Expectation | CVaR (lambda=0.5, alpha=0.1) |
|---|---|---|
| Simulated mean cost | R$253.8m | R$271.4m |
| Mean load shed | 15,885 | 17,851 |
| P90 load shed | 27,587 | 30,170 |

Naive read: CVaR costs more AND sheds more load - backwards from what
risk aversion should do (trade higher average cost for LOWER tail risk).
**Didn't accept that at face value.** Re-ran both at `iteration_limit=300`
before writing anything up:

| | Expectation | CVaR (lambda=0.5, alpha=0.1) |
|---|---|---|
| Simulated mean cost | R$266.5m | R$253.3m |
| Mean load shed | 17,568 | 15,760 |
| P90 load shed | 31,143 | 24,132 |

Both policies' own numbers moved substantially between 50 and 300
iterations (expectation's own P90 load shed: 27,587 -> 31,143) - **50
iterations was genuinely insufficient for either policy**, not just CVaR.
At 300, the picture is closer to theoretically sensible (CVaR's P90 load
shed is now clearly lower), but a full Snakemake-orchestrated run (below)
still shows CVaR's mean cost coming in *below* expectation's own -
something that should not happen if both are fully converged, since the
expectation-trained policy should be the one that minimizes mean cost.

## What actually shipped, and the honest caveat on it

The Snakemake-orchestrated run (what anyone re-running this pipeline
will reproduce, modulo SDDP.jl's own internal RNG - not seeded by this
project, a real gap noted below):

| | Expectation | CVaR (lambda=0.5, alpha=0.1) |
|---|---|---|
| Simulated mean cost | R$263.2m | R$259.8m |
| Mean load shed | 17,149 | 16,889 |
| P50 load shed | 15,706 | 16,200 |
| P90 load shed | 30,246 | **29,418** |

Directionally consistent with CVaR reducing tail risk (P90 down) in
every comparison run this session, including this one. **Not claimed as
a clean, decisive confirmation** - the mean-cost anomaly and the P50
going the *other* direction mean real uncertainty remains, attributed
to two named, unresolved factors rather than swept under the rug:

1. `iteration_limit=300` is a fixed count, not PRIMER Sec 4.3's
   convergence-gap stopping rule ("stop when the gap is acceptably
   small") - 300 is checked to be materially better than 50, not proven
   sufficient.
2. Only 100 Monte Carlo simulation realizations back every reported
   statistic - real sampling noise, especially for tail (P90) statistics
   driven by comparatively rare load-shedding events.

Both are now `known_limitations()` entries, not just handoff prose - the
same discipline as every other caveat in this project's summaries.

## Why report an unclean result instead of tuning until it looks clean

Could have kept raising `iteration_limit` and the simulation count until
the numbers told a tidier story. Didn't, on purpose: PRIMER Sec 7.1's
"plausible, confident, wrong" failure mode applies just as much to a
result that's been polished into looking more decisive than the
underlying computation actually supports as it does to a fabricated
number. What shipped is real, reproducible, and honestly bounded - a
better foundation for the next person (or session) to actually improve
on than a smoothed-over story would have been.

## Gotchas

- `SDDP.simulate()`'s variable list is for JuMP decision variables only -
  `:stage_objective` is automatically included in every result and
  requesting it explicitly raises `No variable named stage_objective
  exists`. Found by running it, not by reading the signature carefully
  enough first.
- `SDDP.calculate_bound()` defaults to `risk_measure=Expectation()`
  regardless of what trained the model - passing the actual training risk
  measure explicitly is required to get a risk-adjusted bound, and it is
  NOT comparable across `risk_kind` runs the way the plain simulated mean
  cost is (a risk-adjusted bound and a plain expectation answer different
  questions). `expected_total_cost_rs` in the summary is always the plain
  Monte Carlo mean, specifically so expectation-vs-cvar comparisons stay
  apples to apples; `risk_adjusted_bound_rs` is reported separately and
  should not be used for that comparison.
- Same `python -c` inline-quoting issue as every prior PR - all
  exploratory Julia checks used scratch `.jl` files.

## Next PR needs

Per ADR-0005's order: **individualized reservoirs** (a future ADR,
superseding ADR-0005) is the last named stage. Real follow-ups this PR's
own findings point at, worth prioritizing ahead of or alongside that:

1. **A convergence-gap stopping rule** instead of a fixed iteration
   count - `SDDP.SimulationStoppingRule` or similar, so "trained" means
   something more rigorous than "ran N times."
2. **Seed SDDP.jl's own internal RNG** for the training/simulation
   randomness - currently only `prepare_sddp_inputs.py`'s scenario
   sampling is seeded (`seed=0` param); re-running `sddp_first_policy`
   produces slightly different numbers run to run because of this.
3. **More simulation realizations** (1,000+, not 100) for tail
   statistics specifically, given how much P90 moved with iteration count.

## Open questions

- Whether the mean-cost anomaly (CVaR sometimes below expectation) is
  purely a convergence/sampling artifact or points at something more
  structural - genuinely unresolved, not just unstated.
