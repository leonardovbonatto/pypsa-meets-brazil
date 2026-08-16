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
| 0002 | OpenStreetMap / ODbL boundary | Planned (PR-08) |
| 0003 | Transmission impedance source (T3, nodal) | Planned |
| 0004 | Bus-level load allocation method | Planned (PR-27) |
| 0005 | Inflow model formulation | Planned (PR-34) |
| [0006](ADR-0006-t0-transfer-representation.md) | T0 inter-subsystem transfer representation | Accepted |
| [0007](ADR-0007-hydro-backcast-interim.md) | Hydro constrained by observed generation (interim backcast) | Accepted |

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
