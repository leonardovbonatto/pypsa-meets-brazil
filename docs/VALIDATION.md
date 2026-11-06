<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Validation record

Every test the models have been scored on, what was fixed before the run,
and the result as it came. A test is **pre-registered** when its criterion
was committed before the data or run it judges; **post hoc** otherwise.
Read a post-hoc pass as a description, not as evidence.

## The tests

| test | model | year | criterion (where) | fixed before? | result |
|---|---|---|---|---|---|
| SDDP backtest | T0 + SDDP cuts | 2024 | storage Pearson ≥ 0.6 in ≥ 3 subsystems; SE_CO price rank ≥ 0.5 (ADR-0015) | yes (`3457b80`) | **fail**: price never passes; storage 2-4 of 4 depending on the variant, N and NE storage partly solver noise (PR-57) |
| Phase 1 gate | T0 | 2024 | wind, utility solar, nuclear, thermal within 5% of ONS; four boundaries within 5% of capacity (ADR-0020) | yes (`dd98b20`) | **fail**: generation passed after PR-65; after ADR-0023, wind 1.071 and 3 of 4 boundaries fail |
| T1 benchmark | T1 | 2024 | generation within 1% of T0; ADR-0020's interchange (ADR-0022) | yes (`d3aac17`) | **fail** on generation-equals-T0 (T1 curtails, T0 cannot); interchange 4 of 4 after ADR-0023 |
| T1 vs ONS | T1 | 2024 | ADR-0020's eight checks | **no** (PR-71) | 8 of 8 |
| Out of sample | T1 | 2025 | ADR-0020's eight checks (ADR-0024) | yes (`2a39aa5`, before fetching 2025) | **fail, 4 of 8**: wind 1.088, solar 1.052, N-NE 7.3%, N-SE_CO 9.0% |
| Reason-aware curtailment + hydro must-run | T1 | 2023 | changed passes more of the eight than baseline (ADR-0025) | yes (`0c44851`, before fetching 2023) | **not adopted**: changed T1 infeasible; baseline 5 of 8 |

## T1 against ADR-0020's eight checks, by year

| check | 2023 (held out) | 2024 (post hoc) | 2025 (held out) |
|---|---|---|---|
| wind | 0.969 pass | 1.014 pass | 1.088 fail |
| utility solar | 0.954 pass | 1.003 pass | 1.052 fail |
| nuclear | 0.995 pass | 0.998 pass | 0.993 pass |
| thermal | 1.079 fail | 0.987 pass | 1.002 pass |
| N-NE (error / capacity) | 11.1% fail | 1.0% pass | 7.3% fail |
| N-SE_CO | 8.2% fail | 4.6% pass | 9.0% fail |
| NE-SE_CO | 0.2% pass | 2.2% pass | 4.2% pass |
| SE_CO-S | 0.1% pass | 2.1% pass | 0.6% pass |
| **passed** | **5** | **8** | **4** |

2024 is the year the design was built against; the two held-out years are
the honest numbers. Patterns across them: nuclear and the S and NE-SE_CO
boundaries hold every year; the two N boundaries fail whenever the year is
held out; wind and solar move with how much ONS curtailed for energy
surplus (2025: 9.7% of wind potential, 15.7% of solar).

## What every result leans on

- **Backcasts.** Hydro (ADR-0007), MMGD (PR-19), small TIPO III plants
  (PR-60) and the thermal floor (ADR-0016, hourly since PR-65) are ONS's
  observed output. Thermal's checks are mostly a check of those inputs.
- **Data-format fixes** for 2023 and 2025 files, none changing 2024:
  listed in the PR-72 and PR-73 handoffs. The one that is an assumption:
  MMGD is taken as zero before ONS began reporting it (April 2023).
- **Variants scored on one backtest.** The SDDP backtest was scored on
  eleven variants (PR-57 handoff lists them); adopted changes each rest on
  evidence outside the backtest.

## Next held-out year

2022 has not been fetched for T0/T1. Any change chosen by looking at
2023-2025 should be pre-registered and tested there.
