<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-75 — T3 nodal structure from EPE (ADR-0026)

`build_network_t3` (rule `build_network_t3_structure`, local only) turns
PR-74's tidy tables into a PyPSA network under `resources/epe/`: AC buses,
lines, transformers and HVDC links. No loads or generators yet.

## Decisions taken in code (all in the module docstring)

- `Existing = 1` means "enters later": all 279 such lines are switched on
  by dated modifications in `mcirc.dat` (2030-2040); G.ARAN's HVDC enters
  in 2030 (`mdcline.dat`). They are left out.
- Transformers are PyPSA Lines with x in ohm referred to bus0's voltage,
  which gives back x % on 100 MVA in the linear power flow, without a
  Transformer's s_nom acting as a limit EPE does not give. No thermal
  limit on them.
- Lines rated 99999 get no thermal limit (1,155 lines).

## The system map matters

PR-74 mapped only systems 1-4, 6, 7, and the T3 grid fell into islands
right at the North. The small systems are the plants and interconnection
nodes NEWAVE models apart: 5 Itaipu/Foz do Iguacu (SE_CO), 8 Belo Monte
(N), 9 Teles Pires/Sinop/Colider (SE_CO), 11 Tapajos (N), 100 Ivaipora 765
kV (S, a judgement call on the S/SE_CO boundary), 200 Imperatriz (N), 300
Xingu (N). Only DC buses (system 10) stay unmapped.

## Result

| | before the map fix | after |
|---|---|---|
| AC buses | 13,086 | 13,122 |
| largest island | 12,514 | 12,865 (98.0%) |
| outside it | 572 (297 in Manaus-Amapa-Roraima) | 257 (mostly 1-2 bus islands) |
| HVDC links | 12 | 14 (G.ARAN excluded) |

No zero reactances; negative x on 101 lines (series capacitors) and 937
transformers (three-winding star points), which DC power flow handles.

## Next PR needs

- Loads and generators on T3: ONS's 2024 load per subsystem spread over
  `dload.dat`'s load buses; plants placed by `busconnection.dat`
  (plant type and code per bus) or by name, matched to ONS's registry.
- Decide what to do with the 257 buses off the main island (drop, or
  report what they carry once loads and plants are attached).
