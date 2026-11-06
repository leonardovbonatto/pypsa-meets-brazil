<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-63 — T0 thermal as cost bands (ADR-0021)

`build_thermal_bands` joins CVU (`cod_usinaplanejamento`) to plants (`ceg`)
through `geracao_termica_despacho`, takes hourly availability from
`disponibilidade_usina` (PR-62), and groups joined plants per subsystem
into CVU bands (edges 150/300/500/800, fixed in ADR-0021 before running).
Each band is a `thermal` generator with capacity-weighted cost, real
availability and its plants' share of the ADR-0016 floor. `{s} thermal`
becomes the residual: registry capacity not in bands, PR-10's average cost,
the rest of the floor.

## What was built (2024)

| | bands | joined p_nom | residual p_nom | residual floor |
|---|---|---|---|---|
| N | 5 (R$105-1,078) | 3.2 GW | 1.4 GW | 317 MW |
| NE | 5 (R$44-1,091) | 5.9 GW | 0.9 GW | 0 |
| S | 4 (R$101-1,016) | 2.8 GW | 0.8 GW | 0 |
| SE_CO | 5 (R$116-993) | 10.0 GW | 5.3 GW | 1,784 MW |

## Phase 1 gate (ADR-0020)

National thermal 1.056 -> 1.055 (fixed by the energy balance, as expected).
The split across subsystems is much closer:

| thermal ratio | PR-62 | PR-63 |
|---|---|---|
| N | 1.11 | 0.92 |
| NE | 0.43 | 0.74 |
| S | 1.29 | 0.94 |
| SE_CO | 1.07 | 1.19 |

Boundaries: SE_CO-S 3.9% -> 0.9%, N-NE 18.6% -> 15.0%, N-SE_CO 8.0% ->
9.6%, NE-SE_CO 3.8% -> 3.4%. Gate still fails (thermal, N-NE, N-SE_CO).

## Gotchas

- `attach_thermal_bands` must run after `attach_marginal_costs`, which
  resets every generator's cost.
- `solve_network_sddp.month_summary` now sums every thermal generator at a
  bus (bands and residual); SDDP itself still has one thermal per
  subsystem (paused).
- SE_CO's residual (5.3 GW at the R$549 average, 1.8 GW floor) is the
  largest unjoined block; it is why SE_CO now runs 19% high.

## Next PR needs

- Why national thermal stays 450 MW high: hydro under-runs its backcast
  ceiling by about the same amount (all of hydro, wind and solar cost zero).
