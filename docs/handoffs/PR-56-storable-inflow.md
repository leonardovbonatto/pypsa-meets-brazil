<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-56 — Dispatch tie-break and storable inflow

Two changes, found one after the other while checking the coupled 2024 run
against ONS's generation by source.

## 1. A second degenerate tie (`RESERVOIR_DISPATCH_COST`)

The network's demand (79 GW) and renewables match ONS, but the coupled run
produced about 70 GW of hydro a month against ONS's 40-60 GW. Wind, solar
and reservoir output all cost zero, so with water valued at zero the solver
ran stored water and curtailed free renewables. That drained the
reservoirs, and it produced v2's storage pass (PR-52).

R$0.005/MWh on reservoir output (half of `SPILL_COST`) gives the order
renewables, then reservoirs, then spill. National hydro then tracks ONS
within a few GW (Jan 52.9 vs 56.2, Aug 40.4 vs 40.5). The backtest fell to
storage 2 of 4 and price rank 0.07; kept because it removes a degenerate
solve, not because it scores better.

## 2. Storable inflow (ADR-0018)

| 2024 mean, GW | |
|---|---|
| gross ENA, less storage change | 55.7 |
| storable ENA, less storage change | 50.5 |
| hydro generated (ONS) | 48.8 |

Three modes scored on the pre-registered backtest:

| mode | storage ≥ 0.6 | SE_CO price rank | SDDP cost |
|---|---|---|---|
| gross | 2 of 4 | 0.07 | R$22.37bn |
| storable + run-of-river | 2 of 4 | −0.13 | R$22.35bn |
| **storable (adopted)** | **3 of 4** (N 0.44, NE 0.64, S 0.66, SE_CO 0.90) | −0.24 | R$22.63bn |

SE_CO storage, model / observed: May 96 / 71, Aug 82 / 56, Oct 56 / 40,
Nov 54 / 43. The shape is right; the level is 15-25 points too high from
April.

## What is still wrong

- **Prices are about zero all year** (the tie-break costs). The cuts value
  water near zero: the regime check has 4 of 1,188 points with dry above
  wet, the rest tied. SDDP's own cost (R$22.6bn) is almost all the thermal
  floor: in SDDP's world, flexible thermal is almost never needed.
- The model keeps reservoirs fuller than ONS did yet never needs thermal.
  ONS ran 10-14 GW of thermal in September-October 2024 with storage at
  40-47%. Something makes ONS value water well above zero at those levels
  and our SDDP does not. Candidates:
  1. The SDDP starting storage is the latest observed date (end 2025), not
     the coupled run's 2023-12-31; check what the cuts are trained around.
  2. One-year PAR(1) droughts are too mild to empty reservoirs this large
     (SE_CO EAR max 205 GWmonth); ONS's risk comes from multi-year droughts
     and its CVaR plus SAR/VminOp storage targets, which this model lacks.
  3. Minimum storage targets: ONS keeps SE_CO above a security curve; with
     none, the model can plan to run reservoirs to zero.
- 296 numeric issues at the 300-iteration cap (31 with gross).

## CVaR, re-tested without the degenerate dispatch

`SDDP_COUPLING_POLICY` picks which policy's cuts the coupled run uses. With
PR-43's fixed λ=0.5, α=0.1 and storable inflow: storage 2 of 4 (N 0.53,
NE −0.32, S 0.92, SE_CO 0.92), price still about zero. Not adopted.

The reason is in the cuts: **the month-end future cost is the same in every
run** (gross, storable, expectation, CVaR: R$18.48bn at the end of February,
R$7.89bn at the end of August). SDDP's cost-to-go does not depend on inflow
or storage at all; it is the thermal floor's cost for the remaining months.
No risk measure can change a cost that has no spread. So the question is not
how SDDP weighs bad years but why it has no bad years.

## Gotchas

- Tested three inflow modes on one backtest: the choice rests on the energy
  balance, which does not use the backtest.
- The inflow-state model (ADR-0011) still uses gross inflow.

## Next PR needs

- Find why no SDDP scenario needs thermal above the floor. Not the start
  storage: training starts at end-2025 (SE_CO 42%), below the backtest's
  61%. First measure, on the 1000 PAR(1) paths, how often thermal rises
  above the floor and how low storage gets; then compare the PAR(1)'s
  driest years with 2014-2015 and 2021. If droughts are too mild, that is
  the fix; if they are not, a minimum-storage (security curve) constraint
  is next.
