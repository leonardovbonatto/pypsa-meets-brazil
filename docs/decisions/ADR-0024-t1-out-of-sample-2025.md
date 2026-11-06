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

## Outcome (PR-72): fails, 4 of 8

Run `t0-75b5182c` (config.2025.yaml), model frozen at `2a39aa5` plus four
data-format fixes (handoff PR-72), none of which changes 2024.

| check | T1 2025 | ONS 2025 | result |
|---|---|---|---|
| wind | 14,342 MW | 13,184 MW | 1.088 fail |
| utility solar | 3,917 | 3,722 | 1.052 fail |
| nuclear | 1,792 | 1,805 | 0.993 pass |
| thermal | 8,511 | 8,493 | 1.002 pass |
| N-NE flow | −1,591 | −2,054 | 7.3% of capacity, fail |
| N-SE_CO flow | 3,273 | 4,223 | 9.0%, fail |
| NE-SE_CO flow | 4,550 | 4,210 | 4.2%, pass |
| SE_CO-S flow | 2,855 | 2,793 | 0.6%, pass (hourly corr. 0.998) |

T1 still beats T0 on every check that differs between them (T0 2025: wind
1.157, solar 0.944, thermal 0.934, three boundaries failing). The 2024
match (PR-71) does not carry over: T1 now over-produces wind and solar, so
it curtails less than ONS did in 2025.
