<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-28 — PAR(1) inflow model, persistence (ADR-0005 stage 1c)

**Landed:**

- `scripts/fit_inflow_par1.py` + `rules/sddp.smk::fit_inflow_par1`.
- `test/test_fit_inflow_par1.py` - 13 tests, including two that recover a
  *known* phi/mu/sigma from synthetic ground-truth data (not just
  "runs without error").
- `resources/inflow_par1_params.csv` (mu/sigma/phi per subsystem/month)
  and `results/inflow_par1_validation.json` (persistence diagnostic +
  `known_limitations`) - both gitignored, regenerable.

## Scope decision: split persistence from spatial correlation

PRIMER Sec 4.7 names TWO properties PAR(p) must preserve "or the whole
exercise is compromised": persistence and spatial correlation across
subsystems. Splitting them into two PRs, the same staged discipline
ADR-0005 already used for "coupling mechanism" (PR-26) vs. "data source"
(PR-27). This PR is persistence only. **Spatial correlation is not yet
preserved - each subsystem's PAR(1) is fit and simulated completely
independently.** This is a real, load-bearing gap: independent sampling
understates true system-wide drought risk (real basins are correlated),
and it's named explicitly in `KNOWN_LIMITATIONS`, not silently deferred.

## What the fit actually found, on real data

| Subsystem | phi range (by month) | Read |
|---|---|---|
| N | 0.80 - 0.98 | Strong persistence - matches the Amazon basin's predictable wet/dry seasonality |
| NE | 0.45 - 0.97 | Moderate to strong |
| S | 0.34 - 0.81 | Weakest - matches southern Brazil's less ENSO-correlated rainfall |
| SE_CO | 0.51 - 0.72 | Moderate, fairly stable across months |

All real values, not assumed - a real modelling insight that fell out of
just fitting the data honestly, consistent with prior findings in this
project (PR-18's Conjunto de Usinas bug, PR-20's coverage gap) coming from
looking at actual numbers rather than trusting an a-priori expectation.

**Persistence validation** (200 simulated 26-year realizations per
subsystem, historical drought-run length's percentile within that
distribution):

| Subsystem | Historical max drought run (months) | Simulated median | Historical percentile |
|---|---|---|---|
| N | 11 | 16.0 | 0.16 |
| NE | 11 | 13.0 | 0.365 |
| S | 12 | 10.0 | 0.81 |
| SE_CO | 9 | 9.0 | 0.55 |

All four comfortably inside the model's own simulated range (none near
the >0.97 danger zone that would mean the model badly understates real
persistence - PRIMER's named failure mode). N's 0.16 is worth noting
honestly rather than only reporting the reassuring numbers: if anything
the model's simulated droughts run slightly *longer* than the single
real historical realization for N, the opposite direction of the failure
mode - plausible given only one 26-year record to compare against, not
necessarily a problem, but worth re-checking once more data or a longer
record is available.

## Design choices worth knowing

- **Fit on gross `ena_bruta_mwmed`, not storable `ena_armazenavel_mwmed`.**
  Storable already nets out historical spill - an operational choice made
  under the past system's actual policy, not part of the exogenous
  stochastic process PAR(p) is supposed to represent. Full reasoning in
  the module docstring.
- **PAR(1), not a higher order.** No AIC/PACF order selection - the
  simplest defensible first cut, matching this project's established
  "smallest real step first" pattern. A future PR could test higher
  orders if PAR(1) proves insufficient once spatial correlation and a
  real SDDP policy are in the loop.
- **The persistence check compares against a FIXED historical threshold**,
  not each series' own quantile - otherwise both historical and simulated
  series would trivially show ~30% of months "dry" by construction,
  making the comparison meaningless. Both are judged against the same bar.
- **`validate_persistence` reports a percentile, not a pass/fail.** One
  26-year historical record is a small sample; treating it as ground
  truth to match exactly would be a different, less honest kind of
  overconfidence than the one PRIMER Sec 7 warns about.

## Gotchas

- `fit_par1_by_month`'s December -> January wrap needed real care:
  `((month - 2) % 12) + 1` gives the correct previous calendar month
  including the year boundary. Got this right on the first real run
  (verified against the actual Jan/Dec pair count: 25, matching 25 real
  year-transitions across 26 years of data) - but it's exactly the kind
  of off-by-one that would have silently dropped real data if wrong.
- `python -c "..."` and inline multi-line strings through
  `PowerShell → wsl.exe -lc` keep breaking the same way (recorded in
  `wsl-windows-tooling` memory already, and in PR-26's handoff) - every
  exploratory check this PR used a scratch `.py` file instead, no
  exceptions this time.

## Next PR needs

**Spatial correlation across subsystems** (PRIMER Sec 4.7's second
property, and this PR's most important named gap): compute the 4x4
cross-subsystem correlation matrix of same-month standardized residuals
(the `z_t - phi_m * z_{t-1}` shocks each subsystem's independent fit
already produces internally, not yet returned or used), then sample
`simulate_par1`'s shocks jointly via Cholesky decomposition of that
matrix instead of independently per subsystem. Validate the same way
this PR validated persistence: does simulated cross-subsystem
correlation match the historical record's, within a reasonable range.

Only after both properties are preserved does ADR-0005's next stage - a
first expectation-only SDDP policy trained on these parameters, using
PR-26's now-proven coupling mechanism - become defensible to build.

## Open questions

- Whether PAR(1) remains adequate once spatial correlation is added, or
  whether the added structure changes which order fits best - untested,
  deferred to whenever this gets revisited.
