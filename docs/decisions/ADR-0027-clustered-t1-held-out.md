<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0027 — Held-out test of the clustered T1 on 2025 and 2023

- **Status:** Proposed
- **Date:** 2026-11-22
- **Supersedes:** —
- **Superseded by:** —

## Context

T1 is now T3 (EPE's nodal base) clustered to 35 (state, subsystem) nodes
(ADR-0026, PR-77, PR-78). Every choice in PR-77 and PR-78 was made by
looking at 2024, where it scores 5 of ADR-0020's eight checks, post hoc.
It has not been run on 2023 or 2025.

The benchmark is the DLR-based T1 on the same years, both held out when
it ran: 2025, 4 of 8 (ADR-0024); 2023, 5 of 8 (ADR-0025's baseline).
Leonardo's aim: do better than DLR, with 2025 as the main year.

This ADR is committed before the clustered T1 is run on either year.

## Decision

1. **Model frozen** at the commit that adds this ADR. Runs use
   `config/config.2025.yaml` and `config/config.2023.yaml` (snapshot year
   only; ADR-0025's switches stay off).
2. **Checks: ADR-0020's eight**, unchanged: national mean wind, utility
   solar, nuclear and thermal within ±5% of ONS for the year; each T0
   boundary's mean signed flow (summed over the clustered T1's crossing
   lines and links) within 5% of that boundary's capacity (`links_t0.csv`).
3. **Criterion.** Pass if both hold:
   - **2025 (decides):** more checks pass than the DLR T1's 4, i.e. at
     least 5 of 8;
   - **2023:** no fewer than the DLR T1's 5, i.e. at least 5 of 8.
4. Reported, deciding nothing: each check's error size, ADR-0022's
   "within 1% of T0" check, and T0's own scores.
5. **Allowed fixes:** only data-format or parsing problems in the year's
   files, each recorded with its effect. No modelling or parameter change.
6. Result reported as it comes. A fail does not bring back the DLR T1
   (T1 comes from clustering, Leonardo's decision); it marks PR-78's
   2024-chosen rules (low-voltage ties, fitted reactances) as suspect.

## Consequences

EPE's base is one network close to today's grid (its first dated changes
are in 2030) and gives no build dates for existing lines. Lines built in
2023-2025 are therefore in the 2023 run, which can make 2023's transfer
limits too generous. 2025 is the closer match, one more reason it decides.

## Outcome (PR-79): fails, 2025 4 of 8 (needed 5); 2023 5 of 8 (held)

Runs `t0-7a613a39` (2025) and `t0-b87309e0` (2023), model frozen at
`934beb4`, no data-format fixes needed. DLR-based T1 in brackets.

| check | 2025 | 2023 |
|---|---|---|
| wind | 1.160 fail (1.088 fail) | 0.990 pass (0.969 pass) |
| utility solar | 1.204 fail (1.052 fail) | 0.965 pass (0.954 pass) |
| nuclear | 0.990 pass (0.993 pass) | 0.995 pass (0.995 pass) |
| thermal | 1.013 pass (1.002 pass) | 1.127 fail (1.079 fail) |
| N-NE | 1.6% pass (7.3% fail) | 0.6% pass (11.1% fail) |
| N-SE_CO | 8.5% fail (9.0% fail) | 12.0% fail (8.2% fail) |
| NE-SE_CO | 8.6% fail (4.2% pass) | 13.8% fail (0.2% pass) |
| SE_CO-S | 0.5% pass (0.6% pass) | 0.7% pass (0.1% pass) |
| **passed** | **4 (4)** | **5 (5)** |

What changed against DLR: N-NE, which DLR failed in both held-out years,
now passes in both. NE-SE_CO, which DLR passed, now fails in both. N
sends too much to SE_CO in all three years (2024: 14.9%), the pattern
PR-78 traced to Belo Monte's HVDC running a pole backwards. In 2025 wind
and solar are further above ONS than DLR's: the clustered grid has more
transfer capacity, and ONS's curtailment for energy surplus is not
modelled.
