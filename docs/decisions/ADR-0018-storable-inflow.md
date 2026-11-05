<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0018 — Only storable inflow reaches the reservoirs

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes:** — (refines ADR-0014's reservoirs and ADR-0005's inflow use)
- **Superseded by:** —

## Context

SDDP and the coupled run put all of gross ENA (`ena_bruta`) into one
reservoir per subsystem. ONS also publishes storable ENA (`ena_armazenavel`),
gross minus the inflow that was spilled. Over 2000-2025 the gap is 26% of
gross in N, 21% in S, 8% in SE_CO and 3% in NE.

The 2024 energy balance says which one is real energy. ONS generated 48.8 GW
of hydro on average:

| | 2024 mean, GW |
|---|---|
| gross ENA, less the storage change | 55.7 |
| storable ENA, less the storage change | 50.5 |
| hydro generated (ONS `geracao_usina`) | 48.8 |

Storable closes the balance within 3% nationally; gross overstates it by 14%.
The coupled run had the extra energy: with the dispatch tie-break (PR-56) in
place, its reservoirs stayed too full (SE_CO 72% in October against 40%).

## Decision

1. **`SDDP_INFLOW_MODE = "storable"`.** SDDP sends `share * inflow` to the
   reservoir, where `share` is total storable over total gross ENA per
   (month, subsystem) over all history; the rest is lost. The coupled run's
   reservoirs receive observed 2024 storable ENA.
2. **The PAR(1) stays fitted on gross inflow**, as fit_inflow_par1 argues:
   gross is the exogenous quantity. The split is applied after sampling, and
   the coupled run's regimes are still read from gross.
3. **Two other modes stay available**: `"gross"` (the earlier model) and
   `"storable_plus_run_of_river"` (the gap offered as same-month energy,
   sharing the turbines).
4. The inflow-state model (ADR-0011) keeps gross inflow; it is not the
   coupling source.

## Alternatives considered

- **`storable_plus_run_of_river`.** Built and scored (below). It gives the
  model back almost all of gross, which the energy balance says is too much.
- **Fit the PAR(1) on storable inflow.** Storable nets out spill, partly an
  outcome of ONS's past dispatch, not part of the random process.

## Outcome (PR-56)

Pre-registered backtest (ADR-0015), all runs with the dispatch tie-break:

| mode | storage, Pearson ≥ 0.6 in ≥ 3 | SE_CO price rank | SDDP cost |
|---|---|---|---|
| gross | 2 of 4 (N 0.87, NE 0.11, S 0.62, SE_CO 0.56) | 0.07 | R$22.37bn |
| storable + run-of-river | 2 of 4 (0.42, 0.06, 0.75, 0.69) | −0.13 | R$22.35bn |
| **storable** | **3 of 4** (0.44, 0.64, 0.66, 0.90) | −0.24 | R$22.63bn |

Storable is adopted on storage. Price still fails: prices stay at about zero
all year, because the cuts still value water near zero (the regime check
shows the first 4 of 1,188 points with dry above wet, the rest tied).

Three variants were scored on the same backtest; the choice is backed by the
energy balance above, which does not use the backtest.

## Consequences

**Positive.** Reservoirs only hold energy that can be stored; storage shape
passes in three subsystems with a non-degenerate dispatch.

**Negative.** A fixed monthly share ignores that the storable share is lower
in very wet months than in dry ones. The run hit the 300-iteration cap with
296 numeric issues, against 31 for gross; the bound had settled, but the
count is a warning.
