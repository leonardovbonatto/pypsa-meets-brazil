<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-61 — One-way links with a routing tie-break

In the lossless T0 transport model, N's surplus reached SE_CO at the same
cost directly or through NE, and the 2024 solve routed about 2 GW through
NE. Each boundary is now two one-way Links (`b0-b1`, `b1-b0`, each up to
p_nom) carrying `LINK_TIE_BREAK_COST` = R$0.001/MWh. One-way, because on a
single two-way Link a cost on negative flow is a credit. The cost sits
below the coupled run's reservoir dispatch (0.005) and spill (0.01) costs.
`check_phase1_gate` nets the two directions.

## Phase 1 gate (ADR-0020), boundaries

| boundary | PR-60 error / capacity | PR-61 | model / ONS mean MW | hourly corr. |
|---|---|---|---|---|
| N-NE | 0.581 | 0.182 fail | −371 / −1,467 | 0.79 |
| N-SE_CO | 0.313 | 0.087 fail | +2,241 / +3,150 | 0.89 |
| NE-SE_CO | 0.331 | 0.028 pass | +4,009 / +3,775 | 0.93 |
| SE_CO-S | 0.031 | 0.032 pass | −12 / +209 | 0.93 |

Generation is unchanged (wind 0.977, solar 0.971, thermal 1.042 pass;
nuclear 1.111 fails).

## What remains on the N boundaries

N's net export is close (model +1,870 MW, ONS +1,683), but ONS routes more
of NE's export through N (NE -> N -> SE_CO). In a meshed AC grid flows
split by impedance; a transport model sends power by the cheapest path.
This is ADR-0006's stated T0 simplification, now with a number on it.

## Next PR needs

- Nuclear availability (Angra refuelling outages), from a non-circular
  source if ONS publishes one.
