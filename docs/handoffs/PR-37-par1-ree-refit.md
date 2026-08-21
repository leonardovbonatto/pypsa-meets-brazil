<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-37 — PAR(1) refit at REE level (ADR-0008 stage 2)

**Landed:**

- `scripts/fit_inflow_par1_ree.py` — PAR(1) persistence + 12x12 spatial
  correlation fit per REE, keyed on `ree` instead of `subsystem`, same
  overall shape as `fit_inflow_par1.py` (PR-28/29).
- `rules/sddp.smk::fit_inflow_par1_ree`, reading `resources/inflow_ena_ree.csv`
  (PR-36), writing `resources/inflow_par1_params_ree.csv`,
  `resources/inflow_par1_correlation_ree.csv`,
  `results/inflow_par1_validation_ree.json`.
- `test/test_fit_inflow_par1_ree.py` (16 tests).

This is ADR-0008's next named step: PR-36 built the real REE-level ENA
series, this PR fits the stochastic model on it.

## The real finding this PR exists to report

Fitting directly on the full volume crashed: `simulate_par1_correlated`'s
own re-estimated correlation matrix was missing TELES PIRES as a column
entirely. Traced to the actual cause rather than patched around the
symptom - TELES PIRES reports `ena_bruta_mwmed == 0.0` for its first 213
days (2016-01-01 to 2016-07-31; `ena_bruta_pct_mlt` is 0.0 across the same
window too), then real nonzero values from 2016-08-01 onward. Zero natural
inflow for 213 straight days is not physically plausible for a river - this
is a "not yet tracked as its own REE" placeholder, the same underlying
phenomenon PR-36 found for 3 REEs starting only from 2017-12-30, just
represented as explicit zero rows here instead of missing ones. Confirmed
via the raw data directly (not assumed): no other REE has a single zero
`ena_bruta_mwmed` row anywhere in the 2016-2025 record.

PAR(1) fits in log space, where a zero is `-inf` - this corrupted TELES
PIRES's Jan-Jul mu to `-inf` and (via the standardized-residual chain) its
phi for every month to `NaN`, which silently propagated through
`simulate_par1_correlated`'s AR(1) recursion until the whole simulated
series was `NaN` and the resulting column dropped out of the re-estimated
correlation matrix - several steps removed from the actual cause, which is
exactly why this was traced rather than guessed at.

**Fix:** `drop_pre_tracking_zeros()`, called once at the top of `main()`
before any monthly aggregation. A general rule keyed on `value == 0.0`
(not a `TELES-PIRES`-specific name list like `REPORTING_GAPS` in
`build_reservoir_ree.py`), so a future REE with the same startup pattern is
handled automatically. Prints which REE(s) and how many rows were dropped,
so this stays visible rather than silent.

## Design choices worth knowing

- **Each REE fit on whatever years it actually has** - no uniform-history
  requirement, same principle `build_inflow_ree.py` already established at
  the tidy-series level (PR-36).
- **`validate_persistence` restructured to use each REE's OWN `n_years`**,
  not one shared constant - the subsystem-level version could get away
  with a single shared `n_years` because all 4 subsystems share an
  identical 26-year window; at REE level, 3 REEs have 9 years and the rest
  have 10, so simulating a shorter-history REE over a longer REE's year
  count would bias its own drought-run comparison.
- **`residual_correlation_matrix` relies on pandas `.corr()`'s
  pairwise-complete-observations default** to stay well-defined across
  REEs with different coverage windows - no explicit handling needed once
  the `-inf`/`NaN` contamination above was fixed; a regression test
  (`TestResidualCorrelationMatrix::test_handles_rees_with_different_coverage_windows`)
  covers this directly with synthetic ragged data.

## Real results (12 REEs, real 2016-2025 data, after the zero-fix)

- **Persistence held up despite the much shorter record**: no REE's
  historical drought run landed above the 90.5th percentile of its own
  200-realization simulated distribution (PARANAPANEMA, the highest) -
  comfortably under the `>0.97` warning threshold inherited from the
  subsystem-level fit. Zero warnings fired.
- **Spatial correlation reproduced tightly**: the Cholesky-correlated
  simulator's own re-estimated correlation, across all 66 REE pairs,
  landed within 0.06 of the historical value (mean gap 0.014, worst pair
  IGUACU-ITAIPU at 0.058) - comfortably under the `>0.15` warning
  threshold. Zero warnings fired.
- **Phi (persistence) ranges from 0.65 (IGUACU) to 0.97 (BELO MONTE)** -
  BELO MONTE's is close to the subsystem-level fit's own highest (N's
  0.80-0.98, PR-28), a real, plausible finding given BELO MONTE's role as
  a run-of-river plant on the heavily seasonal Xingu, not investigated
  further here.
- **Correlation signs and magnitudes are geographically sensible**, cross-
  checked against basin adjacency rather than accepted blind: ITAIPU-
  PARANAPANEMA 0.75 and IGUACU-SUL 0.64 (adjacent Parana-basin REEs);
  NORTE-TELES PIRES 0.52 (both Amazon-basin); MADEIRA-NORDESTE -0.24 and
  MANAUS-AMAPA-SUDESTE -0.22 the most negative pairs, not investigated
  further.

## Gotchas

- Same `python -c`/inline-quoting issue as every prior PR - every
  exploratory check (including the TELES PIRES crash investigation) used
  scratch `.py` files.
- `resources/inflow_ena_ree.csv` was not present on disk at session start
  despite PR-36 having built and verified it - `resources/`/`results/` are
  gitignored working outputs, not committed. Rebuilt via
  `snakemake -j1 build_inflow_ree` before this PR's fit could be tested
  against real data at all.

## Next PR needs

Per ADR-0008/the roadmap's Phase 7 gate: a REE-level SDDP policy, with an
explicit REE-to-subsystem allocation seam for the demand balance (demand
and thermal stay at subsystem level per T0; hydro moves to REE level using
this PR's params/correlation plus `resources/reservoir_ear_capacity_ree.csv`-
style REE capacity, which itself still needs assembling analogous to
`prepare_sddp_inputs.py`, PR-31). Independently, temporal persistence
inside the policy itself (state-augmented AR inflow, flagged since PR-33)
remains the single most-implicated lever on tail risk and can land before
or after REE individualization.

## Open questions

- Why BELO MONTE's phi (0.97) is so much stronger than every other REE's -
  plausible (heavy Xingu seasonality) but not directly investigated against
  a hydrological reference.
- Whether TELES PIRES's 213-day zero-reporting window has a documented
  ONS explanation (REE creation date, commissioning milestone) - inferred
  from the data's own shape, not confirmed against an ONS announcement.
