<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-39 — the SDDP convergence ceiling, measured (and a real unit error found)

**Landed:**

- `julia/sddp_first_policy.jl` — `iteration_limit` and `n_simulations` are
  now CLI args (7th/8th) instead of hardcoded, both recorded in
  `summary.json`; `KNOWN_LIMITATIONS` rewritten with the two findings below.
- `rules/sddp.smk` — `SDDP_ITERATION_LIMIT` / `SDDP_N_SIMULATIONS` module
  constants, shared by both policy rules as tracked Snakemake `params`
  (so changing either is a rerun trigger, and the two policies can never
  drift into being trained differently and compared anyway).

PR-38 ended with an explicit open question: *does CVaR's backwards-looking
P90 close if you train longer?* It could not be investigated at the time
because `iteration_limit` was hardcoded. This PR makes it configurable,
runs the sweep, and answers it.

## Finding 1: the question is unanswerable as posed — training breaks first

Swept `iteration_limit` ∈ {1000, 3000, 6000} × {expectation, cvar}, all at
`n_simulations = 1000`. Everything above 1000 **failed**, and the first
attempt hid why: the sweep script piped through `grep RESULT`, discarding
the errors (my own tooling mistake, not a model behaviour). Re-run
unfiltered, the real cause is unambiguous and identical in both cases:

```
Termination status : OPTIMAL
Primal status      : INFEASIBLE_POINT
```

HiGHS reports the LP as solved while handing back a primal-infeasible
point — classic ill-conditioning as Benders cuts accumulate. With
`log_every_iteration = true`, the exact crash points, seed 0:

| policy | crashes at iteration |
|---|---|
| expectation | **2277** |
| CVaR | **1569** |

Two things follow, both real:

1. **`iteration_limit = 1000` is not a converged policy** — it is just the
   largest round number safely below the breakdown. The bound was still
   climbing when training died:

   | iteration | bound (expectation) |
   |---|---|
   | 1000 | 7.292411e8 |
   | 1500 | 7.665815e8 |
   | 2000 | 7.819234e8 |
   | 2277 (crash) | 7.900844e8 |

   That is **+8.3%** still accruing between iteration 1000 and the crash.

2. **CVaR breaks 708 iterations *earlier* than expectation** — the policy
   that would most need the extra iterations to resolve its tail is the one
   that gets fewest. So "train CVaR longer" is not merely untested, it is
   unavailable.

This is PR-33's own warning ("numeric issues rose to 57 … a real,
unresolved signal that this model's LP conditioning may degrade as cuts
accumulate") turning into a hard failure, now that PR-38 doubled the state
space from 4 to 8. The chain is coherent: more states → more cuts needed →
worse conditioning → earlier breakdown.

**Not attempted here** (deliberately, one concern per PR): actually fixing
the conditioning — cut pruning via `cut_deletion_minimum`, or compressing
the LP's coefficient range (storage bounds run to ~200,000 MWmes against a
load-shed cost of 10,000, a wide span). That is the real prerequisite for
any larger cap, and it is the natural next PR.

## Finding 1b: CVaR-above-expectation is NOT sampling noise

PR-38 reported CVaR's P90 load shed *above* expectation's (backwards from
theory) at only 100 simulation realizations, and named the small sample as
a candidate explanation. Re-measured at 1000 realizations, it holds:

| | expectation | CVaR |
|---|---|---|
| mean load shed (MW-months) | 38,435 | 41,216 |
| P50 load shed | 39,271 | 42,853 |
| **P90 load shed** | **57,530** | **60,995** |

So the anomaly is real, and — per Finding 1 — cannot be chased by training
longer. `n_simulations` is raised 100 → 1000 permanently (cheap, and P90
figures are meaningfully steadier).

## Finding 2: reported costs are a RATE, not R$ — a real unit error, NOT fixed here

Found while answering a question about what the load-shed difference meant
in physical terms. The stage objective is:

```julia
thermal_marginal_cost[s] * thermal_generation[s] + LOAD_SHED_COST * load_shed[s]
```

`R$/MWh × MW = R$/h`. There is **no hours-in-month factor anywhere**, so
the reported `expected_total_cost_rs` is a rate summed over 12 monthly
stages, not an annual R$ total. Converting properly needs ~730 h/month.

Verified exactly rather than inferred — reconstructing the objective from
the simulated quantities reproduces the reported figure to a ratio of
**1.0000000000000018**:

```
UNITCHECK|reported=4.790341850855101e8|reconstructed=4.7903418508551097e8|ratio=1.0000000000000018
```

`LOAD_SHED_COST = 10_000` was correctly copied from `build_network.py` —
but **PyPSA multiplies by snapshot weightings automatically and SDDP.jl
does not**. Right constant, wrong unit context. The same class of trap as
ONS's MWmed/MWmes (PR-27/30), and it slipped past PR-31's own "units
worked through carefully" check because that check was about the *water
balance* (where MWmed/MWmes/MW genuinely are commensurable over a month) —
the objective was never in scope.

**Consequences:** every "expected annual cost in R$" this epic has reported
since PR-31 (R$241m, R$263m, R$500m …) is short by ~730×. Policy behaviour
and every load-shed statistic are essentially unaffected, since this is
near-uniform scaling — comparisons between runs remain valid; only the
absolute R$ labels are wrong. (Not *exactly* uniform: months are 28-31
days, so a correct version mildly reweights the stages relative to each
other.)

**Deliberately not fixed in this PR** — it is a separate conceptual concern
(ADR-0001's one-concern rule), it changes every reported number in the
epic, and it was raised with the user rather than folded in unilaterally.
Recorded in `KNOWN_LIMITATIONS` so nobody reads a wrong R$ figure without
the caveat attached.

## Gotchas

- **Don't pipe a long experimental run through `grep`** — the sweep's
  failures were invisible for an hour because only `^RESULT` lines were
  kept. Capture the full log, filter afterwards.
- **Crashing SDDP runs dump `model_infeasible_node_N.cuts.json` and
  `subproblem_N.mof.json` into the cwd**, which is the repo root for a
  normal invocation, and these are *not* gitignored (`reuse lint` catches
  them at commit time). Same family as PR-26's `SDDP.log` finding. Run
  experimental Julia from a scratch cwd, or clean up before staging.
- Results are exactly reproducible run to run (the Snakemake run
  reproduced the standalone sweep's numbers to every digit) — PR-33's
  seeding is doing its job.

## Next PR needs

**Fix the LP conditioning** — the single blocker that gates everything
else about this policy's credibility. Concrete candidates, in order of
cheapness: `cut_deletion_minimum` (SDDP.jl's own cut-pruning knob), then
rescaling the model's units so the coefficient range narrows (e.g. storage
and inflow in GWmes/GWmed rather than MWmes/MWmed). Success criterion is
concrete and measurable: training survives past 2277/1569 iterations and
the bound flattens instead of still climbing.

Then, still open from earlier PRs: the R$ unit fix (Finding 2 — awaiting a
decision), the REE-level policy (ADR-0008/PR-37), and the Phase 7 gate's
backtest against real ONS CMO/PLD/EAR trajectories.

## Open questions

- Is the CVaR-above-expectation result *purely* an under-convergence
  artifact, or is something else wrong (e.g. the risk measure interacting
  badly with the AR(1) state)? Unresolved — and unresolvable until the
  conditioning is fixed, since CVaR cannot currently be trained further.
- Would fixing the R$ units change the conditioning at all? Multiplying the
  objective by ~730 is near-uniform scaling and should not by itself, but
  it does move the objective's coefficient magnitudes, and the crash is a
  conditioning problem — worth checking rather than assuming.
