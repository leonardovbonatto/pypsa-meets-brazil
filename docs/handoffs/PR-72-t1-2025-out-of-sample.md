<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-72 — T1 on 2025, out of sample (ADR-0024): fails, 4 of 8

ADR-0024 (`2a39aa5`) froze the model and fixed the criterion before any
2025 file was fetched. Run: `snakemake --configfile config/config.2025.yaml`
-> `results/t0-75b5182c/`.

## Data-format fixes (ADR-0024 decision 4), none changes 2024

1. `fator_capacidade` 2025: 1,320 rows without installed capacity.
   `build_availability` drops them (their output would count without their
   capacity); the dictionary marks the column nullable.
2. `geracao_termica_despacho` 2025: `cod_usinaplanejamento` has nulls, so
   it reads as float. Dictionary: nullable, float64, `coerce: true`, a new
   option in `_inspect.to_pandera_schema`. The floor does not use it; the
   band bridge drops null codes.
3. `intercambio_internacional` 2025 lacks 312 hours (13 days). Those hours
   get zero exports; more than 5% missing still raises.
4. A month with no unit operating (SE_CO wind in early 2025) has no
   commissioning row; it now means share 0, not missing data.

## Result

See ADR-0024's Outcome. Wind 1.088 and solar 1.052 fail; nuclear and
thermal pass; NE-SE_CO and SE_CO-S pass; N-NE 7.3% and N-SE_CO 9.0% fail.
T0 on 2025 is worse on every differing check.

## Reading it

- On 2024, T1's wind and solar matched ONS within 1.5% (post hoc). On 2025
  it over-produces: it curtails less than ONS did. Hypothesis, not checked:
  ONS's 2025 curtailment includes reliability and energy-surplus reasons
  the model does not represent, while DLR's 2020 corridors are generous
  for the larger 2025 fleet. The 2025 detail files carry no reason codes.
- The two N boundaries were T1's weakest in 2024 too.

## Gotchas

- `resources/` now holds 2025 builds; any 2024 target rebuilds them.
- Next model change should be scored on both years.
