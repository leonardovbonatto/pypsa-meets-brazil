<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-51/52/54 — Cuts in PyPSA, the 2024 backtest, and the thermal floor

One handoff for three PRs that only make sense together: the thermal floor
(PR-54, ADR-0016) made SDDP's costs believable, the coupling (PR-51,
ADR-0014) used its cuts in PyPSA, and the backtest (PR-52, ADR-0015) judged
the result against criteria committed beforehand (`3457b80`).

## SDDP with transmission, net load and the floor (1000 PAR(1) paths)

| | regional (ADR-0010) | inflow state (ADR-0011) |
|---|---|---|
| cost | R$22.37bn | R$22.35bn |
| load shed | 0 | 0 |
| iterations / time | 200 (converged) / 55 s | 4000 / 13 min |
| numeric issues | 31 | 177 |
| acceptance test | **fails**: water value 0 at the reference point everywhere | passes (S 0.0134 dry vs 0.0006 wet) |

The floor takes SDDP's cost from R$0.47bn to R$22.4bn a year. The two designs
tie on cost again; the regional policy stays the coupling source (ADR-0014),
with the inflow-state model's passing test noted for later.

## The coupled 2024 run and the backtest (January-November)

| run | storage (≥0.6 in ≥3) | SE_CO price rank (≥0.5) | verdict |
|---|---|---|---|
| first, no spill cost | 1 of 4 | 0.48 | fail |
| with `SPILL_COST` (tie-break) | **4 of 4** (N 0.76, NE 0.91, S 0.71, SE_CO 0.95) | 0.27 | **fail** |

The first run was a degenerate solve, not economics: with zero water value,
SE_CO spilled 36.8 GW of inflow in January while running down storage. The
tie-break keeps the criterion unchanged and fixes the coupling.

SE_CO, model vs observed:

| month | 1 | 3 | 5 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|
| storage % | 58 / 61 | 62 / 70 | 59 / 71 | 39 / 63 | 22 / 56 | 4 / 47 | 1 / 40 | 2 / 43 |
| price R$/MWh | 0 / 3 | 0 / 1 | 0 / 1 | 0 / 78 | 0 / 111 | 0 / 366 | 500 / 516 | 0 / 152 |

Storage shape is right until May, then the model spends water far faster than
ONS did. Prices are zero in ten months, with the spike in the right month at
almost the right level. Pearson correlation of SE_CO price is 0.77; the rank
test fails on the ten tied zeros. **The water is valued too low**: the policy
treats it as nearly free until reservoirs are almost empty.

## Likely causes, in order of evidence

1. **December has no water value** (ADR-0014), so as the year runs out the
   cuts value stored water ever lower and both policies drain from June.
2. **Not risk aversion.** A CVaR sensitivity with PR-43's fixed λ=0.5,
   α=0.1 (chosen long before this backtest) drains at least as fast: storage
   4 of 4, SE_CO price rank 0.10, SE_CO 14% in August against 56% observed.
3. **Gross inflow.** SDDP and the coupled run use `ena_bruta`, including
   run-of-river energy that cannot be stored.
4. **Symmetric transmission limits** (PR-53: SE→NE is 6,000 MW, not 8,311).

## Gotchas

- Snakemake deletes a failed rule's outputs: the backtest table must be
  rebuilt from `backtest_2024.comparison_table` to inspect a failure.
- The regional policy converges in 200 iterations once the floor fixes most
  thermal; SimulationStoppingRule now actually triggers.

## Next PR needs

- A longer SDDP horizon so December's water has a value, then storable
  inflow, one at a time, each scored on this same pre-registered backtest.
