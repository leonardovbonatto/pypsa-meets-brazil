<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-65 — Hourly thermal floor in T0

PR-64 left hydro curtailed only in hours when every thermal generator sat
at its floor: a floor held flat over each month oversupplies hours when the
real inflexible output was lower. `build_thermal_bands` now takes
`floor_resolution` ("hourly", the T0 default, or "monthly"): the same
ADR-0016 quantity (verified minus merit order above inflexibility), per
plant and per hour for bands, and per subsystem and hour for the residual.
`build_network._floor_by_snapshot` reads either shape. SDDP keeps its
monthly floor (`thermal_floor_t0.csv`, unchanged).

## Phase 1 gate (ADR-0020), run t0-c4c153ed

| national | monthly floor (PR-64) | hourly floor |
|---|---|---|
| wind | 0.977 | 0.977 pass |
| utility solar | 0.971 | 0.971 pass |
| nuclear | 0.998 | 0.998 pass |
| thermal | 1.058 | 1.048 pass |
| hydro (backcast) | 0.994 | 0.995 |

**Generation passes; the gate still fails on two boundaries**: N-NE 15.5%
and N-SE_CO 9.4% of capacity (NE-SE_CO 4.9%, SE_CO-S 2.2% pass; hourly
correlations 0.83-0.99).

## Read with care

Thermal's pass rests mostly on backcasts: the hourly floor is ONS's own
non-merit thermal output, and small plants run as observed. What the model
decides is merit-order thermal and where it runs; per subsystem that is
N 0.93, NE 0.67, S 0.96, SE_CO 1.17.

## Next PR needs

- The two N boundaries: ONS routes part of NE's export through N. A
  transport model cannot split flow by impedance; candidates are EPE's
  directional limits (local only) or the T3 nodal tier.
