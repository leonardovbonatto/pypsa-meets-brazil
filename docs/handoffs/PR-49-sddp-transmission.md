<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-49 — Transmission in the SDDP subproblem (ADR-0012)

**Landed:** `add_transmission` and `flow_stats` in `julia/sddp_first_policy.jl`,
used by both SDDP models; `links.parquet` copied from `links_t0.csv` by
`prepare_sddp_inputs`; flow statistics in `summary.json`.

## Result (inflow-state model, serial, 4000 iterations, same 1000 PAR(1) paths)

| | isolated (PR-48) | with transmission |
|---|---|---|
| cost on PAR(1) paths | R$233.76bn | **R$55.97bn** |
| mean annual load shed | 22,520 MW-months | 21 |
| numeric issues | 2 | 37 |
| training time | 13 min | 10 min |

Boundaries sit at their limit in 28-48% of scored months (SE_CO-S 28%,
NE-SE_CO 48%), even though the limit is an hourly maximum applied to monthly
averages. S's shedding, about 80% of the total before, was isolation.

The regional (ADR-0010) run with transmission alone was stopped after 25
minutes to save 2.5 hours; the inflow-state model on the same paths measures
the same effect, and the regional model is trained with all of PR-49, PR-50
and PR-54 together.

## Gotchas

- Acceptance tests still tie at the reference point with transmission alone.
- Numeric issues rose; worth watching as more constraints arrive.

## Next PR needs

- Net load (PR-50). Directional limits (PR-53 found SE->NE at 6,000 MW).
