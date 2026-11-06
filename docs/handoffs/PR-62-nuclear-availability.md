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

## Scoping the per-plant thermal merit order (measured, not built)

`geracao_termica_despacho` carries both `cod_usinaplanejamento` (CVU's key)
and `ceg` (the key of `capacidade_geracao` and `disponibilidade_usina`):
the join PR-09 lacked. 2024 coverage:

| | |
|---|---|
| CVU plants with a 2024 value | 114 |
| bridge pairs (cod -> ceg) | 144 cod onto 97 ceg: several codes per plant (units) |
| availability plants (UTE) | 81, 22.25 GW installed, 17.28 GW mean available |
| of which with a CVU via the bridge | 78, 21.96 GW (NE 0.29 GW without) |
| registry TIPO I thermal | 31.5 GW: ~9.5 GW is not in the availability data |
| observed dispatched thermal | 6.58 GW, of which joined plants 4.47 GW |

So a per-plant (or CVU-band) merit order with real availability is feasible
for about two-thirds of dispatched thermal output. It needs an ADR first:
what to do with the ~2.1 GW from plants outside the join, how the ADR-0016
floor splits across plants (the dispatch dataset has it per plant), and
whether SDDP keeps one cost per subsystem.
