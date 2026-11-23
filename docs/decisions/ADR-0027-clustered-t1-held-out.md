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
