<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-68 — The T1 (state) network, built and solved

`build_network_t1` splits the T0 network across T1's nodes (ADR-0022):
each T0 generator goes to the nodes of its subsystem by their share of the
subsystem's observed 2024 output of that carrier (`geracao_usina` has both
`id_estado` and `id_subsistema`), keeping T0's per-unit profiles and costs;
each subsystem's load goes to its main nodes by DLR's 2020 state shares
averaged by (month, hour); exports go to RS; links are T1's, as one-way
pairs with DLR efficiency and the PR-61 tie-break. Islands (RR) are left
out and their plants fold into their subsystem's largest node.
`solve_network_t1` reuses `solve_network.py`.

## Result (2024)

Solves with no load shedding; objective R$20.6bn. National generation
equals T0 except about 50 MW more thermal for DLR's link losses.

| boundary | ONS mean MW | T0 | T1 | error / capacity, T0 -> T1 |
|---|---|---|---|---|
| N-NE | −1,467 | −536 | −821 | 15.5% -> 10.7% |
| N-SE_CO | 3,150 | 2,165 | 2,337 | 9.4% -> 7.7% |
| NE-SE_CO | 3,775 | 4,185 | 3,814 | 4.9% -> 0.5% |
| SE_CO-S | 209 | 365 | 316 | 2.2% -> 1.5% |

State topology moves every boundary toward ONS, most where T0's transport
model routed NE's export directly. The two N boundaries are still outside
5%: more of NE's export should cross N.

## Gotchas

- Read loads with `get_switchable_as_dense("Load", "p_set")`: a static
  load is absent from `loads_t` (the test caught a silent zero).
- Error / capacity above uses T0's boundary capacity, to compare with
  ADR-0020's numbers; a T1 gate needs its own definition.

## Next PR needs

- A T1 gate (ADR-0022 decision 5): subsystem flows scored with ADR-0020's
  criterion and the generation-equals-T0 check, automated.
