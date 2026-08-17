<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-30 — EAR connector (ADR-0005 stage 1e)

**Landed:**

- `rules/fetch.smk::fetch_ons_ear_subsistema` + `config.default.yaml`'s
  `sources.ons.ear_subsistema` entry.
- `docs/data-dictionary/ons/ear_subsistema.yaml` - full 26-year,
  37,988-row volume.
- `rules/build.smk::build_reservoir` + `scripts/build_reservoir.py` -
  tidy (date, subsystem) history table, plus `latest_capacity()`.
- `scripts/_common.py::inflow_history_years()` generalized to take a
  `dataset` parameter, shared with `ena_subsistema` rather than
  duplicated.
- `test/test_build_reservoir.py` (11 tests),
  `test/fixtures/ons/ear_subsistema_sample.csv`.

## Why this PR, before the SDDP policy PR ADR-0005 named next

ADR-0005's staged order names "a first expectation-only SDDP policy" as
the step after PAR(p) fitting (PR-28/29). Building that policy needs a
real reservoir - and a reservoir needs a real **capacity** (how much it
can hold), not just the inflow (ENA) already connected. Fabricating a
placeholder capacity number to unblock the policy PR would have been
exactly the "plausible, confident, wrong" failure mode PRIMER Sec 7.1
warns about, one level removed from ADR-0007's already-rejected
"fabricated water value" alternative. Checked whether ONS publishes real
reservoir capacity before assuming it would need inventing - it does
(`ear_max_subsistema`), via the same S3-listing method PR-27 used
(`?list-type=2&prefix=dataset/ear`), no CKAN involved.

## What was found on the real data

- **Capacity genuinely grows over time**, not a static number:
  | Subsystem | 2000 | 2024/2025 |
  |---|---|---|
  | N | 12,311 | 15,302 |
  | NE | 49,967 | 51,691 |
  | S | 14,093 | 20,459 |
  | SE_CO | 157,701 | 204,615 |

  Real new reservoir capacity built over 25 years. `latest_capacity()`
  uses the most recent date's value, not an average - averaging would
  understate present-day capacity for a forward-looking policy.

- **A real, small, checked data quirk**: `build_tidy_reservoir()` first
  raised on real data - verified storage exceeded max capacity in 99 of
  37,988 rows (0.26%). Investigated rather than immediately handled:
  all 99 are subsystem N, 95 of 99 are in the year 2000, overage tops out
  at 3.66% (mean 1.6%). ONS's own dataset description says this data "is
  subject to a recurring consistency process and may be updated after
  publication" - a very old row's `ear_max_subsistema` almost certainly
  was never retroactively revised after a later recalibration. **Clipped,
  not rejected** - same precedent as `fator_capacidade`'s >1.0 rows
  (PR-14): failing a 26-year build over a small, explicable, early-record
  quirk would be worse than bounding it.

- **A cross-check on the earlier ENA unit-discrepancy finding (PR-27)**:
  EAR's dictionary and column name AGREE ("mwmes" both places), unlike
  ENA's disagreement ("mwmed" column, "MWmes" documented). This is
  informative: EAR is a stock, where MW-month is a coherent unit; ENA is
  a flow, where it isn't. Reinforces that ENA's dictionary really did
  have a documentation error, not that "MWmes" is secretly the right
  reading for both.

## Design choices worth knowing

- **Two outputs, not one**: `resources/reservoir_ear_history.csv` (full
  tidy series, for validating a simulated SDDP storage trajectory against
  real historical operation later) and `resources/reservoir_ear_capacity.csv`
  (just the latest-year capacity per subsystem, what the policy PR
  actually needs to build reservoir bounds). Kept separate rather than
  making every consumer re-derive the latest-year filter themselves.
- **`inflow_history_years()` generalized, not duplicated.** Same
  year-range semantics as `ena_subsistema`, a `dataset` parameter rather
  than a near-identical second function - both datasets keep independent
  `sources.ons.<dataset>.years` keys, so they remain separately
  changeable even though today they happen to match.

## Gotchas

- Same `python -c` inline-quoting issue as every prior PR through this
  `PowerShell → wsl.exe -lc` chain - every exploratory check used a
  scratch `.py` file, no exceptions.
- The overage bug was found by actually running `build_tidy_reservoir()`
  against the real 26-year volume, not by reading the schema or a
  fixture sample - the 5-day fixture used for unit tests has no overage
  rows at all. Worth remembering: full-volume checks keep finding things
  fixture-scale tests structurally cannot.

## Next PR needs

**The first expectation-only SDDP policy** (ADR-0005's next staged step,
now genuinely unblocked): a 4-subsystem hydro-thermal `SDDP.LinearPolicyGraph`
using `resources/inflow_par1_params.csv` + `resources/inflow_par1_correlation.csv`
(PR-28/29) for stochastic inflow, `resources/reservoir_ear_capacity.csv`
(this PR) for real reservoir bounds, and real T0 data already connected
(`resources/generators_t0.csv` for hydro/thermal capacity,
`resources/costs_t0.csv` for thermal marginal cost) for everything else -
using PR-26's now-proven Julia coupling mechanism. CVaR and individualized
reservoirs come after that, per the ADR.

## Open questions

- Whether `resources/reservoir_ear_history.csv`'s real trajectory should
  be used to validate the eventual SDDP policy's simulated storage path -
  a real opportunity, not yet acted on.
