<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-64 — International exports as load

ONS's observed 2024 generation (79.3 GW) exceeds T0 demand (78.9 GW, the
`curva_carga` load) by about 0.4 GW, which matched the 436 MW of hydro the
T0 solve curtailed in hours when every thermal generator sat at its floor
(4,540 hours). New connector `intercambio_internacional` (hourly verified
interchange per country; positive = export). `build_exports` puts each
country's net flow at its border subsystem; `attach_exports` adds it as a
signed Load `{s} exports`.

2024: Argentina +185.7 MW, Uruguay −24.0, Paraguay 0, all at S. Net
161.7 MW, so exports explain about 37% of the gap; the rest is likely
losses or consumption outside ONS's load series (not checked).

## Phase 1 gate (ADR-0020), run t0-c4c153ed

| | PR-63 | PR-64 |
|---|---|---|
| thermal | 1.055 | 1.058 fail |
| hydro (backcast) | 0.991 | 0.994 |
| SE_CO-S error / hourly corr. | 0.9% / 0.960 | 2.6% / 0.989 |
| N-NE | 15.0% | 15.3% fail |
| N-SE_CO | 9.6% | 9.4% fail |
| NE-SE_CO | 3.4% | 4.5% pass |

Kept for completeness of load, not for the score. The S boundary's hourly
shape is now almost exact.

## Next PR needs

- The remaining hydro curtailment happens when all thermal is at its
  monthly-constant floor: an hourly floor (ADR-0016's definition, hourly)
  is the next thing to test.
