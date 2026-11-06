<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0022 — T1: a 27-state tier from DLR topology and ONS 2024 data

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** —
- **Superseded by:** —

## Context

The roadmap's Phase 2 is a 27-node (federal state) tier, built from and
benchmarked against DLR's open Brazilian dataset (`Brazilian-Grid-in-PyPSA.md`
§4). That dataset (Deng et al., Scientific Data 2023; Zenodo 7478165, v0.2,
CC BY 4.0) carries state geometry, an aggregated inter-state grid from EPE's
Webmap (51 corridors, heuristic capacities), hourly state load, and plant
capacity per state and type, all for 2012-2020. The roadmap says to use it
as Tier 1 and as a methodology reference, refreshed to current data.

ONS's per-plant datasets already used in T0 carry the state (`id_estado`):
`capacidade_geracao`, `geracao_usina`, `disponibilidade_usina`.

## Decision

1. **Nodes: one per (state, subsystem) pair** that holds at least 1% of the
   state's registry capacity (`capacidade_geracao`), named `{state}` for the
   state's main subsystem and `{state}_{subsystem}` otherwise. Measured
   (PR-67): 23 states sit wholly in one subsystem; PR splits S 8.9 GW / SE
   7.0 GW (Itaipu's Brazilian side reports under SE), PA N 19.8 / SE 2.5 GW,
   BA NE 22.3 / SE 0.26 GW. One bus per state would move Itaipu into S and
   break the equivalence with T0. A plant goes to the node of its own
   `id_subsistema`, so every subsystem's capacity equals T0's. Load sits at
   the state's main node.
1b. **Corridors** connect the two states' main nodes. A secondary node gets
   one dedicated link, sized at its own registry capacity, to the main node
   of its state's DLR neighbour in the same subsystem with the largest
   corridor (Itaipu: PR_SE -> SP), and no link inside its state. That
   matches plants such as Itaipu, which export over dedicated lines.
2. **Topology and transfer limits from DLR** (operating corridors), as
   Links with DLR's capacity and efficiency. Cross-border nodes become the
   PR-64 exports (no foreign buses).
3. **Load:** ONS's 2024 subsystem load (`curva_carga`) split across the
   subsystem's states by each state's hourly share in DLR's 2020 load.
   2024 levels from ONS, intra-subsystem shape from DLR.
4. **Generation from ONS 2024, by state**, with T0's methods: capacity of
   units operating each month (PR-59), measured wind and solar factors,
   backcasts for hydro, MMGD and small plants, nuclear availability, and
   thermal bands (ADR-0021) per state.
5. **Benchmark:** T1 aggregated to subsystems must reproduce T0 (same
   generation by source within 1%), and inter-subsystem flows are scored
   with ADR-0020's interchange criterion.
6. Raw DLR files stay out of git like all raw data; only provenance and
   data dictionaries are committed.

## Alternatives considered

- **DLR's 2020 plant capacities.** Six years stale; Brazil added most of
  its wind, solar and MMGD since (roadmap §4).
- **State load from consumption statistics directly.** DLR already did the
  disaggregation and publishes it hourly.

## Consequences

**Positive.** A state tier whose energy numbers are T0's, so differences
come from topology alone.

**Negative.** DLR's corridor capacities are heuristic, and 2020 load
shares ignore growth since. Both are named in T1's limitations.
