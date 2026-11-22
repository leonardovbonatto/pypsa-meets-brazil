<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-76 — Loads and plants on T3 (ADR-0026)

T3 gets T0's 2024 energy: EPE says where, ONS 2024 says how much. Local
only; nothing EPE-derived is committed.

- `scripts/epe_plants.py` (`rule epe_plant_weights`): per-bus weights from
  EPE's plant files (`chidro*` hydro, `ctermi*` thermal, `cgnd*` typed by
  `TechTyp`: 1 wind, 2 solar, 3 biomass/small thermal, 4 small hydro; Angra
  marks nuclear) through `busconnection.dat`, and base load from
  `dload.dat` + `loadp_b004m.dat` (date 1900/01/01, mean over 4 blocks).
  The plant files are fixed-width with blank fields: fields are cut by
  header marker, ending at the marker's end.
- `scripts/build_network_t3_energy.py` (`rule build_network_t3`): each T0
  generator -> (state, subsystem) by ONS 2024 observed output -> buses by
  EPE capacity of the matching kind; MMGD follows load; demand by EPE load
  within each subsystem; exports on RS's load buses. Main island only.
- `scripts/solve_t3_day.py` (`rule solve_t3_day`): one-hour feasibility
  solve, sliced before the model is built.

## Measured

| | |
|---|---|
| generators / load buses | 6,617 / 3,422 |
| capacity by carrier | equal to T0 exactly (e.g. hydro 102,628 MW, wind 31,794) |
| placements without a matching EPE kind | 11 |
| EPE hydro with a bus in busconnection | 58.9 of 86.6 GW (weights only, energy unaffected) |
| one hour, as first built | infeasible |
| one hour, no line limits | optimal, no shedding |
| one hour, with must-run shortfall outlet | optimal; shed 35.5 MWh, shortfall 43.7 MWh |
| memory / time, one hour | 11.2 GB / 385 s |

The infeasibility was two local bottlenecks: forced output (floors, small
plants) on a 138 kV bus in MS and a 69 kV bus in SC that their lines
cannot carry. `MUST_RUN_SHORTFALL_COST` (R$20,000/MWh) gives every bus
with forced output a priced outlet, reported in the solve.

## Gotchas

- T3 model building is ~8 GB regardless of hours: year-long T3 solves are
  not practical here; the clustered tiers carry the time dimension.
- WSL needs `.wslconfig` memory=24GB to survive this (see memory note).

## Next PR needs

- Cluster T3 to (state, subsystem) nodes: the new T1 (ADR-0026 decision 4).
