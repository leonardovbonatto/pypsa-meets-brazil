<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-62 — ONS plant availability connector; nuclear outages

New connector `disponibilidade_usina` (hourly operational availability per
plant, monthly files from 2015; dictionary built from all of 2024, 2.1M
rows). `build_nuclear_availability` sets nuclear p_max_pu to the summed
`val_dispoperacional` of Angra I and II over p_nom. Availability, not
output, so not a backcast. Nuclear left PR-59's commissioning scaling
(the MW figure already reflects the plants running).

## Phase 1 gate (ADR-0020), run t0-ab816517

| national | PR-61 | PR-62 |
|---|---|---|
| wind | 0.977 | 0.977 pass |
| utility solar | 0.971 | 0.971 pass |
| nuclear | 1.111 | 0.998 pass |
| thermal | 1.042 | 1.056 fail |

Boundaries unchanged: NE-SE_CO (3.8%) and SE_CO-S (3.9%) pass, N-NE
(18.6%) and N-SE_CO (8.0%) fail.

## Thermal, read with care

| MW | model dispatched | floor | model small | ONS total |
|---|---|---|---|---|
| N | 2,290 | 1,368 | 15 | 2,082 |
| S | 1,155 | 775 | 106 | 980 |
| NE | 173 | 173 | 97 | 624 |
| SE_CO | 3,266 | 3,191 | 1,517 | 4,476 |

- Most of thermal is a backcast: the floor (ADR-0016) is ONS's observed
  non-price thermal at monthly resolution, and small plants (PR-60) run as
  observed. ADR-0020 scores thermal without saying so; its pass or fail
  says little about the model.
- Merit-order thermal lands in N, whose single averaged CVU (R$237/MWh,
  unweighted over plants, PR-10) is the cheapest; NE sits at its floor
  while ONS ran ~350 MW more there.
- Nationally thermal is 457 MW high, matching hydro running 448 MW below
  its backcast ceiling: hydro, wind and solar are all free, and the
  monthly-constant floor oversupplies some hours.
- The availability data also shows thermal at 82% of installed (17.6 of
  21.4 GW in January): thermal outages are not modelled yet.

## Next PR needs

- A per-plant thermal merit order (CVU blocks per subsystem) instead of one
  averaged cost, and thermal availability from this connector.
