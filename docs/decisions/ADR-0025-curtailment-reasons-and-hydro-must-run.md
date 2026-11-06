<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0025 — Curtailment by reason and hydro must-run, tested on 2023

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** — (would refine ADR-0023 and ADR-0007)
- **Superseded by:** —

## Context

T1 failed its out-of-sample 2025 test (ADR-0024: 4 of 8), over-producing
wind (1.088) and solar (1.052). ONS's reason-coded constrained-off data
(`restricao_coff_*_tm`, GNRa per plant and half hour with reason REL, ENE,
CNF or PAR) shows what grew in 2025, as % of potential output:

| | 2024 | 2025 |
|---|---|---|
| wind ENE (energy surplus) | 2.5 | 9.7 |
| wind CNF (reliability) | 5.2 | 7.0 |
| wind REL (transmission) | 0.8 | 2.5 |
| solar ENE | 6.4 | 15.7 |
| solar CNF | 5.7 | 6.7 |
| solar REL | 1.3 | 3.4 |

Two gaps follow. CNF (and PAR) curtailment has no counterpart in the model,
yet ADR-0023 gives it back as availability. And ENE curtailment happens in
the model only if surplus cannot be absorbed elsewhere, but T0/T1 hydro is
a backcast ceiling that can fall to zero at zero cost, so the model cuts
hydro where ONS cut wind and solar (hydro has minimum outflows it lacks).

These changes were chosen by looking at 2024 and 2025, so neither year can
test them. 2023's generation, interchange and curtailment files have not
been fetched for T0/T1 (checked 2026-11-06). This ADR is committed before
they are.

## Decision (the change under test)

1. **(a) Reason-aware availability:** the uncurtailment factor adds back
   only GNRa with reason REL or ENE, from `restricao_coff_*_tm`; CNF and
   PAR curtailment stay out of availability. Solar has no reason-coded data
   before April 2024: factor 1 there, in both variants.
2. **(b) Hydro must-run:** T0/T1 hydro runs exactly as observed
   (p_min_pu = p_max_pu), as small plants already do.

## Test (fixed here)

- Two runs on 2023 (`config/config.2023.yaml`): the model at the commit
  adding this ADR ("baseline"), and the same plus (a) and (b) ("changed").
- Score each with ADR-0020's eight checks applied to T1 (four national
  sources within 5% of ONS 2023; four boundaries within 5% of capacity).
- **Adopt (a)+(b) only if "changed" passes more of the eight checks than
  "baseline".** Equal or fewer: not adopted, kept behind switches.
- 2024 and 2025 are reported for both and decide nothing.
- Allowed fixes: data-format only, as ADR-0024, applied to both runs.

## Consequences

If adopted, curtailment the model reproduces is the kind it can represent;
hydro becomes a full backcast in T0/T1, so hydro decides nothing there
(SDDP's coupled run is where hydro is a decision).
