<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-66 — DLR open dataset connector; T1 design (ADR-0022)

Phase 2 (27-state tier) starts. `fetch_dlr_open_brazil_energy_data` pulls
DLR's dataset from Zenodo record 7478165 (v0.2, the latest; CC BY 4.0; the
older 6951435 is v0.1). `fetch_dataset.py` now takes a `format` param so a
zip records `row_count: null`. `extract_dlr` copies three tables to stable
paths under `resources/dlr/`; dictionaries in `docs/data-dictionary/dlr/`,
credited to DLR in REUSE.toml.

## What is in the zip (111 entries)

State geometry (shapefile, EPSG:4087); inter-state grid, operating and
operating+planned; VRE potentials; biomass potential; state hydro inflows;
plants per state per type (2012-2020); hourly state load (by consumer and
by consumption, 2012-2020); demand scenarios; RS-Uruguay/Argentina flows.

Extracted: `grid_operation.csv` (51 corridors among 27 states and ARG, PRY,
URY, VEN; capacity 76-23,832 MW, heuristic), `load_2020.csv` (27 states x
8,784 h), `plants_2020.csv` (2020 operating: hydro 101.9 GW, wind 18.4,
solar 3.3, gas 15.6, biomass 15.7, oil 9.5, coal 3.6, nuclear 2.0).

## ADR-0022 in one line

27 state buses on DLR topology; 2024 energy from ONS by `id_estado` with
T0's methods; ONS subsystem load split by DLR's 2020 state shares; T1
aggregated to subsystems must match T0 within 1%.

## Next PR needs

- The state -> subsystem map from `capacidade_geracao`, measured.
- `build_network_t1`: buses, DLR links, state load.
