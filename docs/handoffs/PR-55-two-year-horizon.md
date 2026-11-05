<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-55 — A two-year SDDP horizon (tried, not adopted)

ADR-0017 tested whether the coupled 2024 run drains storage from June because
December's water has no value. It does not: the water value is zero all year,
with one year or two.

## What was built

- `SDDP_HORIZON_YEARS` in `rules/sddp.smk`. The regional graph gets 12 stages
  per year, each stage uses its calendar month (`mod1(stage, 12)`), and the
  Markov transitions come from multi-year PAR(1) simulations, so December ->
  January follows the fitted persistence.
- Scoring paths and training scenarios are unchanged (first simulated year),
  so costs stay comparable. With the setting at 1 the inputs are identical to
  before.
- `SDDP_REGIONAL_ITERATION_LIMIT = 300`, separate from the inflow-state
  model's 4000.

## Results (two years, against the one-year v2 run)

| | one year | two years |
|---|---|---|
| storage, Pearson ≥ 0.6 in ≥ 3 | 4 of 4 | 2 of 4 (N 0.54, NE 0.96, S 0.47, SE_CO 0.99) |
| SE_CO price rank (≥ 0.5) | 0.27 | −0.39 |
| SE_CO price | zero except October (R$500) | zero every month |
| SE_CO storage, Aug / Oct / Nov | 22% / 1% / 2% | 43% / 4% / 0% |

Storage now tracks ONS a little longer (43% against 56% in August) but still
empties by November, and the October spike disappears. Worse on the
pre-registered criteria, so the setting went back to 1.

## The real finding

- Training's simulated cost was **R$44,626m in every iteration**, for all
  3,146 iterations of the first run. Every sampled inflow path cost the same.
  That only happens if water never limits the system: hydro, net load and
  the thermal floor always cover demand, so the floor's cost is the whole
  cost and an extra MWh of stored water saves nothing.
- The regime check agrees: water value 0 in every subsystem, 2,482 of 2,484
  grid points tied.
- So the problem is upstream of the horizon: **SDDP's world has too much
  usable energy.** Candidates, in order:
  1. Gross inflow (`ena_bruta`) counts run-of-river energy as if it could
     be stored. Switch to storable inflow (`ena_armazenavel`) for the
     reservoirs and treat the rest as must-run.
  2. Hydro generation capacity or demand per subsystem out of line with
     2024 (check monthly hydro dispatch against ONS).
  3. Symmetric transmission limits (PR-53: SE->NE is 6,000 MW, not 8,311).

## Gotchas

- `SimulationStoppingRule` never fired on the two-year graph. The bound
  moved 0.03% between iterations 100 (R$44,627m) and 3,146 (R$44,641m),
  while iterations slowed to 9 s each: 4 hours for nothing. The raw log
  was overwritten by the rerun; these two numbers are the record.
- The cuts are written only after training finishes, so a run cannot be
  stopped early and kept.

## Next PR needs

- Storable inflow in SDDP and in the coupled run, scored on the same
  backtest. First check whether ONS publishes storable ENA per subsystem
  alongside `ena_bruta`.
