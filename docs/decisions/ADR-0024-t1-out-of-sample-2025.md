<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0024 — Out-of-sample test of T1 on 2025

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** —
- **Superseded by:** —

## Context

Every T1 result so far is on 2024, the year its design choices were made
against (PR-58..71). T1 met ADR-0020's criterion on 2024 only post hoc
(PR-71). ONS publishes every dataset T0 and T1 use for 2025 (checked
2026-11-06: December 2025 files exist for all sixteen ONS sources). A year
the model was not built on is the honest test.

This ADR is committed before any 2025 data is fetched.

## Decision

1. **Model frozen** at the commit that adds this ADR: code, rules and
   `config.default.yaml`. The run uses `config/config.2025.yaml`, which
   changes only the snapshot year.
2. **Criterion: ADR-0020's, applied to T1 on 2025**, nothing else:
   national mean wind, utility solar, nuclear and thermal generation
   within ±5% of ONS 2025; each of the four T0 boundaries' 2025 mean
   signed flow (summed over T1's crossing links) within 5% of that
   boundary's capacity (2025 `links_t0.csv`) of ONS's. Pass if all eight
   pass.
3. T0 on 2025 is scored with ADR-0020 too and reported; it decides nothing.
4. **Allowed fixes**: only data-format or parsing problems in 2025 files
   (renamed columns, new codes), each recorded in the handoff with its
   effect. No modelling change, no parameter change.
5. Result reported as it comes, pass or fail.

## Consequences

The first test of T1 on data it was not built on. DLR's 2020 load shares
and corridor capacities are one more year further from the test year.
