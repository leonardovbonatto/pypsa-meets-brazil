<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0009 — Making the SDDP policy persistence-aware (Markovian policy graph)

- **Status:** Accepted
- **Date:** 2026-08-21
- **Supersedes:** ADR-0005 (the mechanism by which inflow persistence
  reaches the policy only - ADR-0005's inflow data source, its PAR(p)
  choice, and its Julia/Parquet coupling decision all stand unchanged)
- **Superseded by:** —

## Context

PR-38 added a PAR(1) AR(1) recursion to the SDDP model and shipped under
the title "temporal persistence in the SDDP policy". PR-40 measured that
only half of it landed, and the measurement is unambiguous:

```
storage[NE] max|c|=10000   nonzero(>1e-9)=10875/11000
z[NE]       max|c|=0       nonzero(>1e-9)=    0/11000   ← all four z, both policies
```

**All 22,000 exported Benders-cut coefficients on `z[*]` are exactly
0.0.** The sampled inflow *scenarios* are genuinely autocorrelated, but
the *policy* is blind to that autocorrelation: the cost-to-go function is
flat in `z`, so it cannot express "water is worth more this month because
last month was dry."

**The root cause is structural, not a bug to patch.** A cut coefficient on
a state is the dual of that state's incoming-value fixing constraint. `z`
appears in no `@constraint` and no objective term, because the recursion
it belongs to is **nonlinear**: `inflow = exp(mu + sigma*z)`. An LP
subproblem cannot contain that, which is exactly why PR-38 computed it in
plain Julia and `fix()`-ed the result as a constant. The design that made
the code run is the design that made the policy blind. No amount of
tuning inside the current formulation fixes this.

**A measured check that decided the alternative** (rather than reasoning
about it). The obvious escape is to run the AR in *levels* rather than
logs, since `inflow_t = mu_m + phi_m*(inflow_{t-1} - mu_{m-1}) +
sigma_m*eps_t` is **linear** and could therefore enter the storage-balance
constraint directly and earn a nonzero dual. The known cost is that
Gaussian innovations in levels can drive inflow negative, which is
physically impossible for a river. That cost was quantified against the
real 2000-2025 series rather than assumed tolerable — fitting a
levels-space PAR(1) per subsystem and simulating 500 x 26-year
realizations:

| subsystem | mean phi | mu / residual sd (min) | **negative-inflow rate** |
|---|---|---|---|
| N | 0.90 | 1.96 | **19.30%** |
| NE | 0.80 | 2.08 | **14.68%** |
| S | 0.58 | 1.46 | **6.73%** |
| SE_CO | 0.62 | 3.47 | 0.016% |

Nearly **one month in five** for subsystem N would be a physically
impossible negative natural inflow. This is not a tail nuisance that a
clip quietly absorbs; clipping at zero at that frequency would
systematically distort the very drought behaviour the model exists to
represent. Brazilian practice uses log-space PAR(p) precisely because
monthly inflows are strongly right-skewed with a standard deviation
comparable to the mean (S's mean sits only 1.46 residual standard
deviations above zero). The levels-space route is therefore closed on
this data — a real finding, not a preference.

**What SDDP.jl actually supports**, checked against the installed
package's own API rather than assumed:

- `SDDP.add_objective_state` — already checked and rejected in PR-38, and
  the rejection remains correct: its own documentation states the state
  "cannot appear in any `@constraint`s". It is designed for uncertainty
  that *scales the objective* (fuel prices), not right-hand-side quantity
  uncertainty like inflow.
- `SDDP.MarkovianPolicyGraph(builder; transition_matrices, ...)` —
  `transition_matrices[t][i, j]` is the probability of moving from Markov
  state `i` in stage `t-1` to state `j` in stage `t`, with the first
  matrix shaped `(1, N)` from the root. The builder receives
  `(subproblem, node)` where `node` is `(stage, markov_state)`. SDDP.jl
  maintains a **separate value function per node**, which is exactly the
  mechanism by which a hydrological regime can change what water is worth.

## Decision

**Make the policy persistence-aware with a Markovian policy graph, using
a single system-wide hydrological state.**

1. **Discretise the standardised log-inflow anomaly `z` into K Markov
   states** (start at K=3: dry / normal / wet, as quantile bins of the
   standard normal, which `z` follows unconditionally by construction of
   the PAR(1) standardisation). K may rise to 5 if K=3 proves too coarse,
   subject to the cost in Consequences.
2. **Derive the transition matrices from the already-fitted PAR(1)
   parameters**, not from a new fit and not by hand: for calendar month
   `m`, `P(z_t in bin_j | z_{t-1} in bin_i)` follows directly from
   `z_t = phi_m*z_{t-1} + eps`, `eps ~ N(0, 1 - phi_m^2)`. One transition
   matrix per stage, twelve in total. This reuses PR-28/29's real fitted
   `phi_m` unchanged — the persistence estimate is not re-litigated here,
   only the mechanism by which it reaches the policy.
3. **Use ONE shared, system-wide Markov state, not one per subsystem.**
   Four independent per-subsystem chains would mean `K^4` joint states
   (81 at K=3, 625 at K=5) multiplied by 12 stages — a combinatorial
   explosion for a model that already has a measured convergence ceiling
   (PR-39). Cross-subsystem structure is not lost: the spatial
   correlation from PR-29 continues to act on the within-state inflow
   noise, exactly as it does today.
4. **Drop the `z` `SDDP.State` entirely.** Its job is taken over by the
   Markov node index, returning the model to 4 continuous states
   (storage per subsystem) from PR-38's 8.
5. **Adopt an explicit acceptance test, automated, before this is
   declared done.** Note that it is *not* "cut coefficients on `z` are
   nonzero" — there is no `z` state any more. The correct test is that
   **the value function genuinely differs across Markov states at the
   same stage**: at identical storage, the marginal value of water in the
   dry state must exceed that in the wet state. That is the claim being
   made, so that is what gets tested — the direct lesson of PR-40.

## Alternatives considered

- **Levels-space AR(1) so the recursion can be a linear constraint.**
  Rejected on measured evidence, not principle: 19.3% (N), 14.7% (NE) and
  6.7% (S) of simulated months come out negative on the real fitted
  parameters (table above). Clipping at that rate would distort the
  drought distribution the model exists to represent. Would also require
  refitting PR-28/29/37's PAR(1) work in levels.
- **`SDDP.add_objective_state`.** Rejected again, same reason as PR-38 and
  still correct: its documentation forbids the state appearing in a
  constraint, and inflow must appear in the storage balance. It solves
  objective-coefficient uncertainty, which is a different problem.
- **Per-subsystem Markov chains (`K^4` joint states).** Rejected as
  above — combinatorially explosive against a model with an already-known
  convergence ceiling, for structure that the existing spatial
  correlation largely already captures.
- **Accept the status quo and reframe PR-38 as scenario-level stress
  testing only.** Rejected: it is honest but leaves the epic's headline
  results actively misleading. PR-38's ~2x cost increase currently reads
  as "persistence is now priced correctly" when the likelier reading is
  "the simulated world got harder while the policy stayed blind"
  (PR-40). PRIMER §4.7 names persistence as a required property of the
  inflow model precisely because a policy that cannot see droughts coming
  is too optimistic about storage.
- **Higher-order PAR(p), p > 1.** Not rejected on merit, simply out of
  scope: the mechanism problem must be fixed before the order of the
  process is worth revisiting. ADR-0005's PAR(1) simplification stands.

## Consequences

**Positive.** The policy gains a genuine hydrological regime state, so
CVaR finally has something to hedge against — the most plausible
explanation for PR-38/39's backwards CVaR result (a risk measure cannot
hedge a state it cannot observe) becomes testable. Continuous state count
drops from 8 back to 4, which may *help* the conditioning ceiling PR-39
measured. Transition matrices reuse real fitted parameters, so no new
estimation risk enters. The approach is standard in the SDDP literature
and natively supported by SDDP.jl, not invented here.

**Negative.** The policy graph grows from 12 nodes to `12 x K` (36 at
K=3), so training cost rises and cuts are spread across more nodes —
each node accumulating cuts more slowly per iteration. Against PR-39's
measured ceiling (training crashes at iteration 2277 for expectation and
1569 for CVaR), this is a real risk that the model becomes *harder* to
converge even as each subproblem gets simpler. Discretising a continuous
anomaly into 3 bins is itself a real approximation, and a coarse one.
`scripts/prepare_sddp_inputs.py` and `julia/sddp_first_policy.jl` both
need substantial rework, not a parameter change.

**Risk.** The most likely failure mode is that K=3 is too coarse to show
a meaningful difference in water value between regimes, while K=5 makes
the convergence ceiling worse — leaving no comfortable setting. If that
happens, the honest response is to report it as a real finding and fix
the LP conditioning first (PR-39's own named next step), not to tune K
until a number looks acceptable. **This ADR does not assume the
conditioning problem is solved**; it is sequenced deliberately, because
persistence-blindness makes the model's headline results misleading in a
way that a convergence ceiling does not.

**Ordering note.** Two other known defects are queued and independent of
this decision: the LP conditioning ceiling (PR-39) and the R$-per-hour
objective unit error (PR-39, authorised separately). Neither blocks this
ADR, and this ADR blocks neither.
