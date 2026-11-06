<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-60 — Small TIPO III plants as a must-run backcast

ONS's observed generation includes modalities "Pequenas Usinas (Tipo III)"
and "TIPO III", which the capacity registry does not cover. In 2024: hydro
2,693 MW, thermal 1,734, wind 442, solar 97 (PR-59's measurement).

`build_small_plants` gives each (subsystem, source) a `<source>_small`
generator: p_nom the peak observed output, p_max_pu the observed hourly
output over it, missing hours filled with zero. `build_network` makes them
must-run (p_min_pu = p_max_pu). Backcast, the MMGD principle (ADR-0007).
`check_phase1_gate` counts them under their source, as ONS does, and
reports the backcast part (`model_small_backcast_mw`).

## Phase 1 gate (ADR-0020)

| national | PR-59 | PR-60 |
|---|---|---|
| wind | 0.941 | 0.977 pass |
| utility solar | 0.941 | 0.971 pass |
| nuclear | 1.111 | 1.111 fail |
| thermal | 1.372 | 1.042 pass |
| hydro (backcast) | 0.945 | 0.989 |

Boundaries: SE_CO-S passes (3% of capacity); N-NE (58%), N-SE_CO (31%) and
NE-SE_CO (33%) fail. The model sends N's surplus through NE to SE_CO
instead of directly: N-NE +2,029 vs ONS −1,467, N-SE_CO −136 vs +3,150. In
a lossless transport model both paths cost the same: a tie.

## Next PR needs

- A tie-break on link flow (fewer hops), then nuclear availability.
- Small plants are not in SDDP's net load (`NET_LOAD_CARRIERS`); SDDP is
  paused, so this is noted, not changed.
