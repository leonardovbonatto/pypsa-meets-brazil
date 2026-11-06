<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-57 — Minimum operating storage (tried, not adopted)

ADR-0019 adds VminOp, NEWAVE's penalised minimum storage, at CPAMP's 2024
values. The design and the penalty (1.1 x the dearest thermal cost) were
committed before any run (`b6769aa`).

## Results

| run | storage ≥ 0.6 in ≥ 3 | price | SDDP cost |
|---|---|---|---|
| storable, no VminOp (kept) | 3 of 4 | ~0 | R$22.63bn |
| + VminOp, one year | 2 of 4 | ~0 | R$25.0bn (with penalties) |
| + VminOp, two years | 1 of 4 | ~0 | R$25.15bn (with penalties) |

SE_CO storage fits best with VminOp over one year (Pearson 0.97, mean error
10 points), and the regime check shows real regional water values for the
first time. But they are tiny, NE and S storage get worse, and prices stay
at zero.

## Every variant scored on the 2024 backtest

So nobody reads the adopted model as picked from one lucky try: since the
criterion was committed (`3457b80`), these were scored, in order: no spill
cost; spill cost; CVaR; two years (gross, degenerate dispatch); dispatch
tie-break; storable + run-of-river; storable; CVaR again; two years again;
VminOp one year; VminOp two years. Adopted: spill cost, dispatch tie-break,
storable. Each adopted change is backed by evidence outside the backtest
(a degenerate solve, or the 2024 energy balance).

## The storage score is partly noise while water is worthless

With the penalty factor at 0 the model is economically the same as PR-56's
storable run (SDDP cost R$22.63bn in both), but training stopped
differently (stopping rule at 27,027 cuts against the cap at 89,100), and
the backtest moved:

| storage Pearson | PR-56 storable | same model, re-trained |
|---|---|---|
| N | 0.44 | 0.05 |
| NE | 0.64 | 0.38 |
| S | 0.66 | 0.66 |
| SE_CO | 0.90 | 0.86 |

When water is worth about zero, where it is stored between subsystems is
a tie the solver breaks arbitrarily, so N and NE storage is not set by
economics. S and SE_CO are stable across every run today (SE_CO 0.86-0.97).
The criterion's "3 of 4" therefore flips on noise, and some of today's
adopt-or-not calls rested on N and NE. They should be re-read with only
S and SE_CO as signal; storable inflow and the dispatch tie-break still
stand on their own evidence (energy balance, degenerate dispatch).

## What the backtest is telling us

The model sees no risk in the rest of 2024 from where storage was. ONS's
CMO in September-October 2024 (R$366-516) reflects things this model does
not have: NEWAVE's five-year horizon with CVaR built into the cuts (its
2024 parameters, kept by CPAMP, are not checked here), inflow forecasts for the coming weeks, and a 12% discount rate. A
price match probably needs the horizon to be long enough to reach the next
year's dry season with these risk measures together, which is a larger
change than one PR.

## Gotchas

- `SDDP_VMINOP_PENALTY_FACTOR = 0` leaves a free slack in every stage;
  harmless, but the variable is still there.
- 2024 PMO parameters for reference: deficit cost R$7,810.62/MWh, discount
  12%/year (ONS PMO, January 2024).

## Next PR needs

- A decision on the price criterion's ambition (see the final message of
  this session): either a NEWAVE-like setup (five years, CVaR, discount)
  or accept storage-shape fidelity for now and move to the next phase.
