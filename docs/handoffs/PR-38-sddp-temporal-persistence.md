<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-38 — temporal persistence in the SDDP policy (state-augmented AR(1))

> ## ⚠️ CORRECTED BY PR-40 — read this first
>
> **This PR's headline claim is only half true.** The AR(1) recursion does
> make the sampled inflow **scenarios** autocorrelated month-to-month —
> that part is real and works. It does **not** make the **policy** aware of
> that autocorrelation, which is what the title and most of the text below
> imply.
>
> `z` is declared an `SDDP.State` but appears in **no `@constraint` and no
> objective term**. The recursion runs in plain Julia inside
> `parameterize`, and its result is `fix()`-ed as a constant. The LP never
> sees `z`, so its dual is identically zero and the cost-to-go function is
> **flat** in it. Measured, not theorised: **all 22,000 exported cut
> coefficients on `z[*]` are exactly `0.0`** across both policies.
>
> Consequences for the results reported below:
>
> - The ~2× cost/load-shed increase is **not** evidence that persistence is
>   now priced correctly. The likelier reading is that the simulated world
>   got harder while the policy stayed blind.
> - The CVaR-above-expectation anomaly has an obvious candidate cause: a
>   risk measure cannot hedge a state variable it cannot observe.
> - The "verified directly" smoke test below was genuine but tested the
>   wrong thing — it confirmed the recursion *computes* correctly and the
>   state *carries* across stages, never that the value function *depends*
>   on it. Checking the cut coefficients would have caught this immediately.
>
> The root cause is inherent to a **log-space** AR done in Julia
> arithmetic: `exp(mu + sigma*z)` is nonlinear, so it cannot be a linear
> constraint — which is exactly why the recursion sits outside the LP.
> Fixing it is a real modelling decision (Markovian policy graph, or a
> levels-space AR that can enter the balance constraint linearly), pending
> its own ADR. See `docs/handoffs/PR-40-sddp-persistence-correction.md`.

**Landed:**

- `julia/sddp_first_policy.jl` — a new per-subsystem `z` state (standardized
  log-inflow anomaly), AR(1) recursion + `exp(mu+sigma*z)` computed in
  plain Julia inside `SDDP.parameterize`, both `z.out` and `inflow` fixed
  to the result.
- `scripts/prepare_sddp_inputs.py` — `sample_month_scenarios` renamed
  `sample_month_shocks`, now emits raw correlated standardized shocks
  instead of pre-computed inflow levels; `par1_params.csv` passed through
  to a new `inflow_params.parquet` output.
- `rules/sddp.smk` — `prepare_sddp_inputs`'s outputs renamed/added
  (`shocks`, `inflow_params` replacing `scenarios`); `sddp_first_policy`/
  `sddp_cvar_policy`'s inputs updated to match.
- `test/test_prepare_sddp_inputs.py` — updated for the renamed function
  and new shock semantics.

This closes the gap PR-31 flagged at the very start of the SDDP epic and
PR-33 named as "the single most promising lever" once the capacity
hypothesis for S's load-shedding was ruled out: inflow scenarios were
drawn i.i.d. per month, so the policy could never see a drought coming
from several consecutive dry months, and PR-33 found expectation and CVaR
converged to nearly identical tail outcomes as a direct result.

## The investigation: why `add_objective_state` doesn't work here

Before writing any code, `SDDP.jl`'s real docstrings and bundled tutorial
(`.pixi/envs/sddp/.../docs/src/tutorial/objective_states.jl`) were read
directly - this is exactly the kind of "the literature's standard tool"
temptation this project's discipline says to verify, not assume, before
building on it (same pattern as PR-32's `EAVaR` lambda-convention check).

`SDDP.add_objective_state` is real and is SDDP.jl's own documented
mechanism for autocorrelated processes. It was rejected for a concrete,
checked reason, not a hunch: its own docs state plainly that "the price
cannot appear in any `@constraint`s" - it may only scale the objective. Our
`inflow` variable must enter the storage-balance constraint
(`storage.out == storage.in - hydro - spill + inflow`), not just the
objective, so this mechanism structurally does not apply.

## The alternative that does work, verified directly

A normal (non-objective) `SDDP.State`'s incoming value (`.in`) is fixed to
a concrete number by SDDP.jl before calling the subproblem's builder/
`parameterize` for every real training and simulation branch - the same
mechanism `storage[s].in` already relies on implicitly. `JuMP.fix_value(z.in)`
can read that number out as a plain Julia float inside `parameterize`,
letting the AR(1) recursion `z_out = phi*z_in + shock*sqrt(1-phi^2)` and
`inflow = exp(mu + sigma*z_out)` run as ordinary Julia arithmetic (not a
JuMP expression - no nonlinearity problem), then both `z.out` and `inflow`
are `fix()`-ed to the result. `z` never becomes a free decision variable;
it is a purely exogenous, deterministic-given-the-shock pass-through state,
which is a completely standard, valid SDDP.jl usage pattern.

Verified with a real standalone Julia script (not assumed to work from
reading the mechanism alone) - a tiny 1-reservoir, 4-stage model, trained
and simulated, checking two things directly per stage per realization: (1)
`inflow` exactly equals `exp(mu+sigma*z.out)` (the fix/computation is
wired correctly), and (2) each stage's `z.in` exactly equals the previous
stage's `z.out` (the state genuinely carries across stages, not just
within one). Both held for every stage of every realization checked.

## Two real bugs caught while verifying against real data, not shipped silently

1. **`numerical_stability_report` crash.** SDDP.jl's pre-training
   diagnostic report calls `parameterize` to inspect the model WITHOUT
   going through the real state-fixing sequence that training/simulation
   branches use - so `JuMP.fix_value(z[s].in)` raised `Variable z[N]_in
   does not have fixed bounds`. Confirmed this is that specific report by
   reproducing it, then fixed by passing `run_numerical_stability_report =
   false` to `SDDP.train`, with an inline comment explaining exactly why -
   this loses only a static, purely informational coefficient-range
   report; the per-iteration numeric-issue count PR-33's own findings
   depend on is tracked separately, during real solves, and is unaffected.

2. **Missing shock-variance scaling.** The first real training run (after
   fixing #1) produced startling numbers - mean cost ~R$524m, P90 load
   shed ~64,900 MW-months, roughly double PR-33's baseline. Rather than
   write these up as "temporal persistence roughly doubles risk" without
   checking, the code was re-read against `fit_inflow_par1.py`'s own
   Python simulator (`simulate_par1_correlated`), which multiplies its
   shock by `sqrt(1 - phi^2)` before adding it to `phi * z_prev` - this
   scaling was missing from the Julia recursion entirely (`z_out =
   par.phi * z_in + omega[s]`, no `shock_sd`). Without it, z's stationary
   variance is `1/(1-phi^2)` instead of `1` - for S's phi up to 0.81
   (PR-28), nearly 3x too wide. Fixed; the numbers dropped only modestly
   (~524m -> ~501m), meaning the bug was real but was NOT the dominant
   cause of the large increase - see below.

## The real, remaining result (after both fixes) - honestly reported

| | Expectation | CVaR (lambda=0.5, alpha=0.1) |
|---|---|---|
| Simulated mean cost (R$) | 500.9m | 526.9m |
| P50 annual load shed (MW-months) | 42,778 | 43,773 |
| P90 annual load shed (MW-months) | 58,090 | 63,415 |

Compare to PR-33's i.i.d.-inflow baseline (same seed=0, same
iteration_limit=1000): mean cost ~R$263m for both policies, P90 load shed
30,090.5 for both - i.e. **expectation and CVaR are no longer
near-identical**, which was the entire point of this PR and directly
resolves PR-33's headline finding. But two things are NOT clean:

- **The absolute level roughly doubled** for both policies, not just the
  tail. This is plausible, not obviously wrong: consecutive-dry-month
  years are now representable for the first time (they structurally
  could not be under i.i.d. sampling), and S cannot meet its own peak
  demand without inter-subsystem transmission (established since PR-11,
  outside this reduced subproblem) - a run of several bad months for S in
  the SAME year is a real, physically meaningful scenario this model
  could not previously produce at all. This is NOT independently
  confirmed beyond the direct Julia-level correctness checks above -
  flagged honestly as plausible, not proven.
- **CVaR's P90 load shed came out HIGHER than expectation's** - backwards
  from what CVaR risk aversion should do. This is the SAME direction (not
  a new failure mode) PR-32 originally found at `iteration_limit=50`,
  which PR-33 partly - not fully - resolved by raising to 1000 iterations
  and adding `SimulationStoppingRule`. The now-doubled state-variable
  count (4 -> 8: `z` per subsystem alongside `storage` per subsystem) is a
  well-known SDDP.jl scaling pressure (more state dimensions generally
  need more cuts/iterations for comparable value-function accuracy) and a
  plausible reason this PR's convergence looks similar to PR-32's
  not-yet-1000-iteration state, not PR-33's better-converged one - not
  confirmed by actually raising the iteration cap here.

Both are recorded in `KNOWN_LIMITATIONS` (both files), not smoothed over.

## Design choices worth knowing

- **z's root-node initial value is 0.0 for every subsystem** - the
  unconditional mean anomaly (average conditions), not a real observed
  prior December. SDDP.jl requires one deterministic root; a deployment
  wanting to start from a genuinely known dry/wet state would need a
  different, scenario-conditioned root, not attempted here.
- **The discrete shock set (n_scenarios=10/month) is unchanged from
  PR-31** - the same finite-scenario discretization, just carrying raw
  shocks through the AR(1) recursion instead of being transformed to
  levels immediately. A single extreme shock combination sampled early in
  the year now has lingering effect on every later month (via phi),
  unlike before, where its effect was confined to that one month - this
  is the real mechanism, not a bug, behind the tail getting materially
  fatter.

## Gotchas

- `resources/inflow_par1_params.csv`/`_correlation.csv` were already on
  disk from earlier work in this session (PR-37); `resources/sddp_inputs/`
  and `results/sddp_first_policy|cvar_policy/` had to be rebuilt via
  `snakemake -j1 prepare_sddp_inputs sddp_first_policy sddp_cvar_policy`
  before any of this could be verified against real data - same
  gitignored-outputs reminder as PR-37's own handoff.
- Full end-to-end verification (both policies, 1000 iterations each) took
  about 2 minutes total via `snakemake -j1` - cheap enough to always run
  before shipping a change to this file.

## Next PR needs

1. **Investigate the CVaR-backwards-from-theory finding directly** - does
   raising `iteration_limit` (as PR-32 -> PR-33 did) close the gap now
   that the state space is 8-dimensional instead of 4? A real,
   well-scoped, single-concern follow-up.
2. **REE-level SDDP policy** (per ADR-0008/PR-37's own next-steps) - still
   needs a REE-level `prepare_sddp_inputs` equivalent and an explicit
   REE-to-subsystem allocation seam for demand. Independent of item 1.
3. Per the roadmap's Phase 7 gate: backtest against real ONS CMO/PLD and
   EAR trajectories - not attempted by any PR so far.

## Open questions

- Whether the ~2x jump in mean cost/load shed (not just the tail) is the
  "right" magnitude for this system's real phi values, or partly an
  artifact of only 10 discrete shocks/month compounding through a
  12-month persistent chain - a real, unresolved question, not decided
  here either way.
