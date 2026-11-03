<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-45 — ADR-0009 implemented: a persistence-aware policy

**Landed:**

- `scripts/prepare_sddp_inputs.py` — `markov_bins`, `system_phi_by_month`,
  `transition_matrices`, `sample_markov_scenarios`; emits
  `transitions.parquet` + `scenarios.parquet` in place of
  `inflow_params.parquet` + `shocks.parquet`.
- `julia/sddp_first_policy.jl` — `SDDP.MarkovianPolicyGraph` replaces
  `LinearPolicyGraph`; the `z` state is **gone**; cuts export gains `stage`
  and `markov_state` columns.
- `scripts/check_sddp_regimes.py` — ADR-0009's acceptance test, on the
  exported cuts; rule `check_sddp_regimes` fails if the test fails.
- `rules/sddp.smk` — `SDDP_MARKOV_STATES = 3`, rewired inputs.
- `test/test_prepare_sddp_inputs.py` — 19 tests, replacing the shock-based
  ones; `test/test_check_sddp_regimes.py` — 9 tests.

## The result that matters

**ADR-0009's acceptance test FAILS at 4000 iterations, and PR-45 is not
done.** An earlier draft of this handoff said it passed. That came from a
200-iteration run comparing cost-to-go *levels*, which is not what ADR-0009
specified: it asks for the *marginal value of water*, the slope. Only the
slope reaches a dispatch decision, so a constant gap between regimes changes
nothing. Same error class as PR-38.

`scripts/check_sddp_regimes.py` now tests the slope from `cuts.parquet`, and
`test/test_check_sddp_regimes.py` asserts that a level gap with equal slopes
fails. The criterion was fixed before any 4000-iteration result existed: at
stage 6 and 50% storage, dry >= wet in every subsystem, strictly in at least
one. It has not been relaxed.

Water value, R$ million per MWmes, expectation policy (4000 iterations):

| subsystem | dry | normal | wet | |
|---|---|---|---|---|
| N | 0.1767 | 0.1768 | 0.1824 | inverted, small |
| NE | 0.4713 | 0.4698 | 0.5110 | inverted |
| S | 6.9287 | 5.7185 | 3.0570 | strong, correct |
| SE_CO | 0.0004 | 0.0008 | 0.0131 | inverted, near zero |

Across stages 1-11 and storage 25/50/75%: dry above wet in 92 comparisons,
tied in 14, wet above dry in 26. The CVaR policy also fails (82/17/33).

**S is the one clean result**: no inversions in either policy. N's value
sits on its thermal plateau (237.04 R$/MWh x 744 h = 0.17636), so part of the
inversion is probably month-length arithmetic rather than regime. That is
only a partial explanation: N also has one real inversion of -5,884 R$/MWh
(730 h basis) on the expectation grid, not investigated.

**The regime scenarios lose persistence.** Measured against a PAR(1)
simulation of the same fitted parameters (annual inflow, MWmed summed over 12
months; lag = mean month-to-month correlation of log inflow):

| | N lag / sd | NE lag / sd | S lag / sd | SE_CO lag / sd |
|---|---|---|---|---|
| PAR(1) target | 0.88 / 31,036 | 0.81 / 22,293 | 0.66 / 43,794 | 0.66 / 57,757 |
| K=3 (current) | 0.48 / 20,794 | 0.47 / 16,158 | 0.47 / 33,352 | 0.45 / 50,540 |
| K=5 | 0.57 / 22,408 | 0.58 / 17,472 | 0.58 / 37,345 | 0.58 / 53,597 |
| K=7 | 0.62 / 24,047 | 0.62 / 18,940 | 0.62 / 40,437 | 0.61 / 59,491 |

Means are preserved, but within-regime draws are independent month to month
and one national chain gives every subsystem the same persistence. So the
"marginal distribution unchanged" claim below holds month by month and **not**
across months. 50 scenarios per node instead of 10 changes nothing. **The fall
from PR-43's baseline (R$343bn to R$213bn, shedding 38,452 to 19,922
MW-months) must not be read as a better policy**: the simulated world has
milder droughts, and that is at least part of it.

What did work: 4000 iterations took 934 s (expectation) and 850 s (CVaR), with
2 and 4 numeric issues, and the bound rose only 0.33% from iteration ~1000 to
4000 (205,915 to 206,589). K is therefore cheap to raise.

## K=5, scored on PAR(1) paths

`SDDP_MARKOV_STATES` is now 5. Each run is also scored on 1000 PAR(1) paths
(`sample_par1_paths`) with their own seed, so the inflows are identical at any
K; `summary.json` records this as `par1_out_of_sample`. The tables above are
K=3; the K=3 runs below came from a scratch input set, not the rule.

The acceptance test **still fails**, on N alone. Expectation policy at K=5,
water value at stage 6 and 50% storage:

| subsystem | regime 1 (dry) | 2 | 3 | 4 | 5 (wet) | |
|---|---|---|---|---|---|---|
| N | 0.1765 | 0.1861 | 0.2267 | 0.2121 | 0.1944 | inverted, on the plateau |
| NE | 1.0874 | 0.3364 | 0.1635 | 0.0463 | 0.0469 | correct |
| S | 7.1303 | 6.4726 | 2.9894 | 0.5143 | 0.2318 | correct |
| SE_CO | 0.3547 | 0.2536 | 0.0757 | 0.0074 | 0.0051 | correct |

Grid (dry above wet / tied / wet above dry): 110/10/12 against K=3's 92/14/26.
CVaR is 98/14/20, against 82/17/33, and its N is flat at about 0.1764 in every
regime. N's dry value sits on the thermal plateau, the likely reason, but that
is not established.

Scored on the same PAR(1) paths, K barely changes the outcome:

| | mean cost | mean shed | P90 shed | S shed | numeric issues | time |
|---|---|---|---|---|---|---|
| K=3 expectation | R$239.9bn | 23,097 | 46,340 | 17,983 | 2 | 642 s |
| K=5 expectation | R$238.9bn | 22,966 | 46,530 | 18,087 | 1 | 1519 s |
| K=3 CVaR | R$246.0bn | 24,399 | 46,653 | 19,828 | 4 | 659 s |
| K=5 CVaR | R$249.0bn | 24,782 | 46,851 | 20,111 | 34 | 1136 s |

Times are not comparable: the runs overlapped. The milder scenarios are visible
directly, K=3 expectation being R$213.4bn in sample and R$239.9bn here. S is
about 79% of shedding in every run, which fits SDDP having no transmission and
no renewables. PR-43's R$343bn is not a controlled comparison: different paths,
and every year started from `z = 0`.

## How persistence actually reaches the policy now

Each node is `(stage, regime)` and SDDP.jl maintains a **separate value
function per node**. Nothing nonlinear happens inside the LP:

1. **Regimes** are equal-probability quantile bins of the standardized
   anomaly (`markov_bins`). `z` is standard normal unconditionally by
   construction of PR-28/29's standardization, so the bins follow from the
   distribution itself and need no data. Verified by the law of total
   variance recovering exactly 1.0.
2. **Transition matrices** are derived **analytically** from the fitted
   `phi_m` — no new estimation. Given `z_t = phi*z_{t-1} + eps`, the
   probability of moving between bins is a numerical integral over the
   truncated normal. Rows are renormalized because the +-6 clipping and
   quadrature leave a small residual and SDDP.jl requires exact rows.
3. **Inflows** are conditioned on the regime: `z = regime_mean +
   regime_sd * u`, with `u` Cholesky-correlated across subsystems exactly
   as before (PR-29). Constructed this way the marginal inflow
   distribution is unchanged from PR-31's — only its *conditioning on an
   observable regime* is new.

`phi` is a **single national figure**, an inflow-weighted mean across
subsystems (weighted by `exp(mu + sigma^2/2)`) so SE_CO dominates as it
does in reality. One shared chain, not four: `K^4` joint states was
rejected in ADR-0009.

## Checks that caught real things

- **Law of total variance = 1.0** on the bins. If the regime decomposition
  drifts, it silently changes the marginal inflow distribution — this
  catches that.
- **phi = 0 gives regime-independent transitions** (every entry exactly
  1/K). A known-answer test on the numerical integration.
- **phi = 0.95 is stickier than phi = 0.05.** The transition matrix's
  entire purpose, asserted rather than eyeballed.
- **Dry regimes really are drier** — mean inflow monotone across regimes
  for every subsystem, on real fitted parameters.

## Gotchas

- **Cut nodes serialize as the STRING `"(12, 3)"`**, not a JSON array. The
  first `parse_cut_node` assumed an array and failed loudly on real
  output — which is why it `error`s on an unrecognised shape instead of
  guessing. Worth knowing for anything else that reads the cut export.
- **The terminal stage carries no cuts.** Cut count is
  `iterations x (stages - 1) x K`, not `iterations x stages x K` — 6,600
  at 200 iterations, not 7,200. Not a bug: the last stage has no
  cost-to-go to approximate.
- **Editing the Julia file mid-run makes the two policies inconsistent.**
  Snakemake runs them sequentially, so the second picks up edits the first
  never saw. A run was stopped and restarted for this reason; do source
  edits before launching, docs during.
- **`pkill -f sddp_first_policy` kills your own shell**, because the shell's
  own command line contains that string. Cost a confusing `exit 15`.
- **A killed Snakemake leaves a directory lock.** The next run dies with
  `LockException` and needs `snakemake --unlock`. Worse, it is easy to miss:
  a trailing `; rm -f ...` cleanup in the same shell command **masked the
  failure as exit code 0**, and the stale results looked plausible until a
  missing `n_markov_states` key gave it away. Do not append cleanup after a
  command whose exit status matters.
- At 30 iterations the wet regime's cost-to-go came out *negative* — an
  artifact of an unconverged lower bound, not a defect. It is positive by
  200 iterations. Do not read regime values off a short run.
- **`check_sddp_regimes` failing deletes its JSON** (Snakemake removes a failed
  job's output). The numbers remain in `logs/check_sddp_regimes/{policy}.log`.

## Next PR needs

- **Regional regimes, a new ADR replacing ADR-0009's single national regime.**
  Direction agreed with the project owner on 2026-11-02: N+NE, SE_CO and S at
  K=3, so 27 joint states and 324 nodes. S is negatively correlated with N and
  NE (-0.25, -0.26) and only weakly with SE_CO (+0.20); N-NE is +0.48. Time it
  serially, then with `SDDP.Threaded()`, and check same-seed repeatability. If
  too slow, fall back to S / the rest (108 nodes). Gurobi is parked: installed
  in WSL, but the academic licence needs the university network.
- **Revisit the CVaR comparison** in light of PR-43: the policy now has a
  regime to hedge against, but the comparison metric is still non-nested,
  so a fair comparison needs a nested-consistent statistic or discounting.
  PR-43's finding stands independently of this PR.
- Still open and untouched: REE-level policy (ADR-0008/PR-37), and the
  Phase 7 gate's backtest against real ONS CMO/PLD/EAR trajectories.

## Open questions

- Is K=3 enough to matter operationally, or does the coarseness show up as
  a policy that hedges in only three crude steps? K=5 is one constant away
  but multiplies nodes.
- Does the single national regime hide the real N-vs-S divergence
  (negatively correlated at -0.25, PR-29)? A scenario where N is dry while
  S is wet is currently representable only as within-regime variation.
