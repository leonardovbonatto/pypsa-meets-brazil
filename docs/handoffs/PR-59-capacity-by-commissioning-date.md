<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-59 — Capacity from the units operating in each month

`capacidade_geracao` is a current snapshot (latest entry 2026-08-04).
`build_generators` used every unit without a deactivation date, so plants
that entered operation after 2024 counted as if they had run in it.

## What changed

- `monthly_operating_capacity`: capacity of units entered by each snapshot
  month's end and not yet deactivated. `p_nom` is the largest month
  (December 2024 for growing fleets); `generator_commissioning_t0.csv`
  holds each month's share of it.
- `build_network.attach_commissioning` multiplies p_max_pu by that share
  for wind, solar, thermal and nuclear. Hydro and MMGD availability is
  already observed output over p_nom, so it is left alone.
- The thermal floor's p_min_pu is capped at the scaled p_max_pu.

2024 mean operating capacity over the registry: solar 63.5%, wind 89%,
thermal 92%, hydro and nuclear 100%.

## Phase 1 gate (ADR-0020), before -> after

| national | before | after |
|---|---|---|
| wind | 1.060 | 0.941 |
| utility solar | 1.481 | 0.941 |
| nuclear | 1.111 | 1.111 |
| thermal | 1.038 | 1.372 |
| hydro (backcast) | 0.935 | 0.945 |

Still fails. Thermal got worse because the overstated renewables were
covering for a missing population: about 5 GW of small TIPO III plants
(hydro 2,693, thermal 1,734, wind 442, solar 97 MW) are in ONS's observed
generation but not in the capacity registry. The hydro shortfall equals the
small-hydro output almost exactly.

## Next PR needs

- Small TIPO III plants as a backcast, the same treatment as MMGD.
