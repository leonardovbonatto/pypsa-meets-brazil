<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-67 — T1 nodes and links (ADR-0022 1, 1b)

`build_t1_topology` writes `resources/t1/nodes.csv` and `links.csv`.

## The state -> subsystem map, measured

23 states sit wholly in one subsystem. Split states (registry capacity):
PR S 8.9 / SE 7.0 GW (Itaipu's Brazilian side reports under SE), PA N
19.8 / SE 2.5 GW, BA NE 22.3 / SE 0.26 GW. TO and AC appear in more than
one subsystem in `geracao_usina` but not in the registry. AC and DF have no
active registry capacity; shares use all rows so they still get main nodes.
ADR-0022 decision 1 was amended (still Proposed) after this measurement:
one node per (state, subsystem) pair, not per state.

## Result

30 nodes (27 main + BA_SE_CO, PA_SE_CO, PR_SE_CO). 48 links: 45 corridors
between main nodes (DLR, parallel rows merged, foreign ones dropped) and 3
dedicated links: PR_SE_CO -> SP 7,000 MW, PA_SE_CO -> MG 2,520 MW (DLR has
a PA-MG corridor, the Belo Monte HVDC), BA_SE_CO -> MG 261 MW.

RR has no corridor: an island, correct for 2024 (Roraima joined the SIN
later).

Capacity between subsystems, T1 (DLR heuristic) vs T0 (max observed flow):
S-SE_CO 25,373 (18,373 without Itaipu's dedicated link) vs 6,902; N-SE_CO
14,564 vs 10,492; NE-SE_CO 7,657 vs 8,311; N-NE 6,627 vs 6,019. The
roadmap's warning about DLR's heuristic capacities, quantified.

## Next PR needs

- `build_network_t1`: these buses and links, ONS subsystem load split by
  DLR's 2020 state shares, generation by state.
- Decide whether T1 corridors should be capped so the inter-subsystem sums
  do not exceed T0's observed limits (a scaling per subsystem pair).
