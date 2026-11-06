<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-70 — Wind and solar availability before curtailment (ADR-0023)

New connectors: `restricao_coff_eolica_detail_tm` (2024 complete) and
`restricao_coff_fotovoltaica_detail_tm` (from April 2024), one rule
(`fetch_ons_restricao_coff`, `kind` EOLICA or FOTOVOLTAICA). About 200 MB a
month each. `build_uncurtailment` turns them into a factor per (hour,
subsystem, carrier); `build_network.attach_uncurtailment` scales T0's wind
and solar p_max_pu by it (`uncurtailed=True` in the rule).

## 2024 curtailment, measured

Unrealised output in restricted periods: wind NE 10.4% of potential, N
2.6%, S 1.7% (monthly 0.8% in January to 17.8% in September); solar NE
17.7%, SE_CO 10.7% (April-December; up to 22.5% in September).

## Result

**T1 now passes ADR-0020's interchange criterion on all four boundaries**,
with no fitting to 2024 curtailment:

| boundary | ONS | T1 | error / capacity | hourly corr. |
|---|---|---|---|---|
| N-NE | −1,467 | −1,406 | 1.0% | 0.76 |
| N-SE_CO | 3,150 | 2,666 | 4.6% | 0.91 |
| NE-SE_CO | 3,775 | 3,592 | 2.2% | 0.92 |
| SE_CO-S | 209 | 353 | 2.1% | 0.995 |

T1 vs ONS generation: wind 1.014, solar 1.003, nuclear 0.998, thermal
0.987. T1 curtails roughly what ONS did, from congestion between states.

The pre-registered checks, as they stand:
- T1 gate (ADR-0022): **fails** on generation-within-1%-of-T0 (wind 0.947,
  solar 1.041, hydro 1.012): T1 now curtails and T0 cannot. Interchange
  passes.
- T0 gate (ADR-0020): **fails**: wind 1.071, NE-SE_CO 6.2% (only SE_CO-S
  passes); T0 has no congestion inside subsystems.

## Gotchas

- The 2024 files' columns differ from ONS's dictionary
  (val_geracaoverificada / val_geracaoestimada, not val_geracao /
  val_geracaoreferencia).
- Provenance names keep the upper-case kind (restricao_coff_EOLICA_...),
  matching the rule's output pattern.

## Next PR needs

- A T1 gate scored against ONS (ADR-0020's full criterion applied to T1),
  written as its own ADR rather than by redefining ADR-0022's check.
