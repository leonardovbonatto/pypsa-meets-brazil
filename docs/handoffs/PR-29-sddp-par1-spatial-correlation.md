<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-29 — PAR(1) spatial correlation (ADR-0005 stage 1d)

**Landed:**

- `scripts/fit_inflow_par1.py`: `compute_residuals()`,
  `residual_correlation_matrix()`, `simulate_par1_correlated()`,
  `validate_spatial_correlation()`.
- `rules/sddp.smk::fit_inflow_par1` gains a third output,
  `resources/inflow_par1_correlation.csv`.
- 7 new tests (20 total in `test_fit_inflow_par1.py`), including two that
  construct data with a KNOWN cross-subsystem correlation and verify it's
  recovered - the same correctness-testing discipline as PR-28's known-phi
  tests.

Closes the gap PR-28 named explicitly in `KNOWN_LIMITATIONS`: PRIMER Sec
4.7's second required property (spatial correlation across subsystems),
alongside persistence (PR-28). Both of PAR(p)'s named requirements are now
addressed, with real remaining simplifications named honestly rather than
hidden (see below).

## What was found on the real data

The residual correlation matrix (pooled across all 12 calendar months):

| Pair | Correlation | Read |
|---|---|---|
| N-NE | +0.48 | Positive - both northern basins |
| N-S | **-0.25** | **Negative** - matches known Brazilian ENSO dynamics: wet North years tend to coincide with dry South years |
| N-SE_CO | +0.22 | Mild positive |
| NE-S | -0.26 | Negative, same pattern as N-S |
| NE-SE_CO | +0.39 | Positive |
| S-SE_CO | +0.20 | Mild positive |

The negative N/NE-vs-S correlation is a real, scientifically plausible
finding, not an artifact - it's the same large-scale climate pattern
(the South American Monsoon System's relationship to ENSO) that Brazilian
hydrologists have long used to justify NOT treating subsystems as
independent. Finding it fall out of just correlating the residuals
honestly, without having gone looking for it, is a good sign the fitting
procedure is sound.

**Validation**: simulated 200 correlated 26-year realizations, recomputed
each one's own residual correlation matrix (the same estimation procedure
used on the real data - not just checking the input survived), and
compared the mean simulated correlation against the historical value per
pair. Every pair recovered within 0.03 (e.g. N-NE: historical 0.482 vs.
simulated 0.473) - the fit -> Cholesky -> simulate -> re-estimate pipeline
is genuinely wired correctly end to end, not just plausible-looking.

## A real bug, found by running it rather than reading the code

`write_correlation_matrix()`'s first version raised
`ValueError: cannot insert subsystem, already exists` on the real data.
Cause: `residual_correlation_matrix()` builds its matrix via
`pivot_table(columns="subsystem")` then `.corr()`, which leaves BOTH the
index and columns named `"subsystem"` - `.stack().reset_index()` then
tries to produce two columns with the same name and fails. Fixed by
renaming both axes (`subsystem_a`/`subsystem_b`) before stacking. Now a
regression test (`test_correlation_matrix_round_trips_as_tidy_long_format`)
that deliberately builds a matrix with both axes named `"subsystem"`, the
exact shape that broke.

## Design choices worth knowing

- **One matrix pooled across all 12 months, not month-specific.** Only
  ~26 observations per specific calendar month makes a 4x4
  month-specific correlation matrix too noisy to trust - named explicitly
  in `KNOWN_LIMITATIONS`, since real cross-subsystem correlation plausibly
  varies by season (N and NE's wet seasons don't fully coincide).
- **Correlating residuals, not raw ENA.** Raw ENA series are correlated
  partly just because subsystems share a similar seasonal calendar (both
  wet in Feb, say) - that shared seasonality is already captured
  separately by each subsystem's own mu_m/sigma_m. Correlating the
  AR(1) residuals (what's left after removing each subsystem's own
  predictable persistence) isolates the genuinely separate question: do
  subsystems' *unexplained* month-to-month surprises move together.
- **`simulate_par1` (independent, PR-28) is kept alongside
  `simulate_par1_correlated` (new)**, not replaced - persistence
  validation is inherently a per-subsystem question and doesn't need
  cross-subsystem structure; reusing the correlated simulator there would
  add a dependency for no benefit.

## Gotchas

- Same `python -c`/inline-string quoting issue through
  `PowerShell → wsl.exe -lc` as every prior PR - every exploratory check
  used a scratch `.py` file.
- The stack/reset_index bug above was NOT caught by any unit test before
  running the real pipeline - the unit tests that existed at that point
  called `residual_correlation_matrix()` directly and never round-tripped
  through `write_correlation_matrix()`. Worth remembering: a function
  that "obviously can't fail" (a stack + reset_index) still needs a test
  that exercises it against realistic input shape, not just synthetic
  toy data built without the same column-naming quirks.

## Next PR needs

Both of PRIMER Sec 4.7's required properties are now addressed. Per
ADR-0005's staged order, the next step is **a first expectation-only SDDP
policy** trained on these parameters (`resources/inflow_par1_params.csv`
+ `resources/inflow_par1_correlation.csv`), using PR-26's now-proven
Julia coupling mechanism. CVaR risk aversion and individualized
reservoirs come after that, per the ADR.

## Open questions

- Whether pooling correlation across months (rather than per-season or
  per-month) materially understates or overstates system-wide drought
  risk once a real SDDP policy is trained on it - untested, deferred.
