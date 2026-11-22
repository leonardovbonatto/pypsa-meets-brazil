<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-77 — T1 by clustering T3 (ADR-0026 decision 4)

`scripts/cluster_t3.py` (`rule cluster_t3_to_t1`) clusters T3 into
(state, subsystem) nodes; `solve_network_t1_clustered` solves a year;
`check_t1_clustered_gate` scores it with `check_t1_gate.py`, which now sums
AC lines as well as links across each boundary. Local only.

## What it took (each found by checking the output)

1. **HVDC islands.** Itaipu's 50 Hz side and the Madeira collector are AC
   islands reached only over HVDC. Keeping "the main AC island" dropped
   them and their HVDC. `build_network_t3.main_component` counts links;
   now all 12 inter-node HVDC remain (Itaipu 4 x 1,566 MW PR_SE_CO->SP,
   Belo Monte 4 x 2,000, Madeira 4 x 1,575 RO->SP). Also applied in T3's
   energy placement.
2. **Substations whole.** 116 unrated transformers joined buses of
   different nodes, making corridors unlimited; transformer-connected
   groups now take the node of their highest-voltage bus.
3. **Unrated lines** (1,149) get the median rating of their voltage class.
4. **Common voltage base.** x is referred to 500 kV for every bus before
   merging (merged buses took EPE's fictitious 999 kV).
5. **Parallel combination** for merged x and r: PyPSA's default rescales x
   by centre-to-centre distance over original length, meaningless without
   lengths. 3 non-positive equivalents floored at 0.01 pu.
6. Generators merged per T0 type (`thermal_b3`...), keeping ADR-0021's
   bands; `aggregate_generators_weighted=True`.

35 nodes (a few states span two subsystems), 63 lines, 12 HVDC links, 293
generators; capacity by carrier equals T0.

## 2024 result (post hoc; criteria as ADR-0022 / ADR-0020)

| boundary | ONS | clustered T1 | error / cap. | DLR-based T1 |
|---|---|---|---|---|
| N-NE | −1,467 | −1,208 | 4.3% pass | 1.0% |
| N-SE_CO | 3,150 | 3,348 | 1.9% pass | 4.6% |
| NE-SE_CO | 3,775 | 1,934 | 22.2% fail | 2.2% |
| SE_CO-S | 209 | −73 | 4.1% pass | 2.1% |

vs ONS: wind 0.928, solar 0.855, nuclear 0.997, thermal 1.414. Year solve:
4 min, 12.5 GB.

## Why NE cannot export

Merged lines with near-zero x and small ratings: MA-TO 54 MVA (x 0.03 ohm
at 500 kV, at limit 94% of hours), PE-PI 126 MVA (87%), BA-TO 239 MVA
(53%); PA-PA_SE_CO 127 MVA (97%). Low-voltage ties across state borders
act as short circuits with small fuses in a DC power flow and block the
HV corridors; PI curtails 2 GW, PA_SE_CO 0.9 GW.

## Next PR needs

- Inter-node connections from >= 230 kV lines only (PyPSA-Eur keeps >= 220
  kV); post hoc, chosen from this diagnostic.
