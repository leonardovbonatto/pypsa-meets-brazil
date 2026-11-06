<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-69 — The T1 benchmark (ADR-0022 decision 5), scored: fails

`check_t1_gate` compares the solved T1 network with the solved T0 network
(national generation by source within 1%) and with ONS (inter-subsystem
flow, summed over T1 links crossing each T0 boundary, within 5% of the T0
boundary capacity: ADR-0020's criterion). Both criteria were written in
ADR-0022 (`d3aac17`) before T1 ran. Target
`results/<run>/t1_gate/report.json`.

## Result

| source | T1 / T0 |
|---|---|
| hydro | 1.0009 pass |
| nuclear | 1.0000 pass |
| solar | 0.9883 **fail** |
| MMGD | 0.9999 pass |
| thermal | 1.0071 pass |
| wind | 0.9975 pass |

| boundary | T1 mean | ONS mean | error / capacity | hourly corr. |
|---|---|---|---|---|
| N-NE | −821 | −1,467 | 10.7% fail | 0.76 |
| N-SE_CO | 2,337 | 3,150 | 7.7% fail | 0.90 |
| NE-SE_CO | 3,814 | 3,775 | 0.5% pass | 0.93 |
| SE_CO-S | 316 | 209 | 1.5% pass | 0.996 |

## The solar miss is topology, not the split

All 37 MW of T1's solar curtailment is in RN, whose corridor to CE is at
capacity 42% of hours: the NE transmission constraint behind ONS's real
2024 constrained-off. But the observed output that set solar's
availability is already net of ONS's curtailment, so T1 curtails on top of
it. The 1% check was meant to catch energy lost in the split; it also
catches dispatch changes from topology, as here. Links at capacity in more
than 20% of hours: BA-MG 63%, TO-PA 61%, RN-CE 42%, PI-TO 39%, RJ-ES 38%.

## Next PR needs

- Availability for wind and solar before curtailment (ONS publishes
  constrained-off per plant) so curtailment is not counted twice.
- The N boundaries: more of NE's export should cross N.
