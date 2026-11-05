<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Architecture Decision Records

An ADR records a consequential choice, the alternatives rejected, and the reasoning —
at the moment it was made, while the reasoning is still fresh.

**ADRs are immutable once accepted.** If a decision changes, write a new ADR that
supersedes the old one and update both `Status` fields. Never edit history: the point
is to be able to reconstruct what was known and believed at the time.

## Write an ADR when

- The choice constrains later work (a data source, a modelling formulation, a licence boundary).
- A reviewer or reader would reasonably ask "why this and not the obvious alternative?"
- The choice is a defensible-in-a-paper assumption rather than a fact — bus-level load
  allocation, impedance synthesis, bias-correction method.

Do **not** write one for routine implementation choices with an obvious default.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](ADR-0001-repository-conventions.md) | Repository conventions | Accepted |
| 0002 | OpenStreetMap / ODbL boundary | Planned |
| 0003 | Transmission impedance source (T3, nodal) | Planned |
| 0004 | Bus-level load allocation method | Planned |
| [0005](ADR-0005-inflow-model-formulation.md) | Inflow model formulation (SDDP epic, stage 1) | Accepted (individualization stage superseded by 0008) |
| [0006](ADR-0006-t0-transfer-representation.md) | T0 inter-subsystem transfer representation | Accepted |
| [0007](ADR-0007-hydro-backcast-interim.md) | Hydro constrained by observed generation (interim backcast) | Accepted |
| [0008](ADR-0008-ree-level-individualization.md) | REE-level individualization (SDDP epic, stage 2) | Accepted |
| [0009](ADR-0009-persistence-aware-policy.md) | Making the SDDP policy persistence-aware (Markovian policy graph) | Accepted (national regime superseded by 0010) |
| [0010](ADR-0010-regional-hydrological-regimes.md) | Regional hydrological regimes in the SDDP policy graph | Accepted |
| [0011](ADR-0011-inflow-memory-state.md) | Last month's inflow as an SDDP state (levels PAR(1)) | Accepted; built, not adopted (PR-48) |
| [0012](ADR-0012-sddp-transmission.md) | Inter-subsystem transmission in the SDDP subproblem | Proposed |
| [0013](ADR-0013-sddp-net-load.md) | Net load in the SDDP subproblem | Proposed |
| [0014](ADR-0014-sddp-cuts-in-pypsa.md) | SDDP water values in the PyPSA T0 model | Proposed |
| [0015](ADR-0015-backtest-2024.md) | The 2024 backtest and its pass criterion | Proposed |
| [0016](ADR-0016-thermal-floor.md) | A thermal floor from ONS dispatch reasons | Proposed |

## Template

```markdown
# ADR-NNNN — Title

- **Status:** Proposed | Accepted | Superseded
- **Date:** YYYY-MM-DD
- **Supersedes:** — | ADR-XXXX
- **Superseded by:** — | ADR-XXXX

## Context
What forces are at play? What did we find out? Cite sources and measurements.

## Decision
What we are doing, stated plainly.

## Alternatives considered
What else was on the table, and the specific reason each was rejected.

## Consequences
Positive, negative, and what risk this leaves open.
```
