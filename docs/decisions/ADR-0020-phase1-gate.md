<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0020 — The Phase 1 gate: T0 energy balance and interchange

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes:** —
- **Superseded by:** —

## Context

The roadmap's Phase 1 gate (`Brazilian-Grid-in-PyPSA.md` §8) is: the T0
model "reproduces ONS energy balance & interchange within ~5%". PR-18 made a
ballpark check; nothing has scored the gate. This ADR fixes how, before the
scoring code runs.

The model scored is `solve_network_t0` for 2024 (`results/<run>/
network_t0_solved.nc`), the deterministic T0 model, not the SDDP-coupled run
(paused). Two of its inputs are backcasts of observed generation, hydro
(ADR-0007) and rooftop solar (MMGD, PR-19); comparing them with the same
observations would be circular.

Disclosure: national wind and solar availability for 2024 was seen during
PR-56 (from the coupled run's network: wind about 6% and solar about 18%
above ONS), before this criterion was written.

## Decision

Observed data: ONS `geracao_usina` 2024 (generation per plant, hourly) and
`intercambio_nacional` 2024 (hourly interchange per boundary), both already
connected. Subsystem `PY` is dropped as everywhere else.

1. **Energy balance.** For each of **wind, utility solar (excluding the
   `Pequenas Usinas (MMGD)` modality), nuclear and thermal**, the model's
   2024 national mean generation is within **±5%** of ONS's.
2. **Interchange.** For each of the four T0 boundaries, the model's 2024
   mean signed flow is within **5% of the boundary's capacity**
   (`links_t0.csv` p_nom) of ONS's mean signed flow. Capacity, not the mean
   flow, scales the error, because a boundary's mean flow can be near zero.
3. **The gate passes if every check in 1 and 2 passes.**
4. Reported, deciding nothing: per-subsystem generation, hydro and MMGD
   (backcasts), the hourly correlation of each boundary's flow, and mean
   absolute flow.

## Alternatives considered

- **Hourly or monthly errors.** Stricter than the roadmap's wording; reported
  for interchange as correlation, not scored.
- **Total generation.** Equal to demand by construction; says nothing.

## Consequences

The gate is a pass/fail on the T0 tier's inputs and dispatch, separate from
the stochastic-hydro backtest (ADR-0015). A failure names which source or
boundary is off and by how much.
