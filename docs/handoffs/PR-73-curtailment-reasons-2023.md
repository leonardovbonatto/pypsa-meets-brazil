<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-73 — Curtailment by reason, hydro must-run, held out on 2023 (ADR-0025)

## Diagnostic (ONS reason-coded constrained-off, GNRa % of potential)

| | 2024 | 2025 |
|---|---|---|
| wind ENE / CNF / REL | 2.5 / 5.2 / 0.8 | 9.7 / 7.0 / 2.5 |
| solar ENE / CNF / REL | 6.4 / 5.7 / 1.3 | 15.7 / 6.7 / 3.4 |

2025's growth is mostly energy-surplus curtailment, which T1 absorbs by
cutting free hydro (a ceiling-only backcast) instead of wind and solar.

## The test

ADR-0025 (`0c44851`) fixed, before 2023 was fetched: (a) only REL and ENE
curtailment as availability, (b) hydro must-run; adopt if T1 on 2023
passes more of ADR-0020's eight checks than the baseline. Switches:
`t0_options.curtailment` and `t0_options.hydro_must_run` (both off);
`config/config.2023.changed.yaml` turns them on. New connector
`restricao_coff_*_tm` (reason-coded).

Result: baseline 5 of 8, changed **infeasible**. Not adopted. See the ADR.

## Data-format fixes for 2023 (both variants; no change to 2024 or 2025)

1. `geracao_termica_despacho` 2023 lacks `val_fdexp`: dictionary marks it
   `required: false` (new option in `_inspect.to_pandera_schema`).
2. Termopernambuco reports up to 17 MW availability above installed in
   8,419 hours: availability clipped at installed capacity per row.
3. MMGD is not in `geracao_usina` before late April 2023 (2,832 hours):
   MMGD output 0 there. Assumed, not checked: ONS's load also excludes
   MMGD then. If it does not, 2023 thermal (1.079) is overstated by it.

## Across three years, T1 (ADR-0020's eight checks)

| | 2023 (held out) | 2024 (post hoc) | 2025 (held out) |
|---|---|---|---|
| passed | 5 | 8 | 4 |
| N-NE / N-SE_CO | 11.1% / 8.2% | 1.0% / 4.6% | 7.3% / 9.0% |

The N boundaries fail in both held-out years: likely structural (DLR's
corridors around N, or HVDC Belo Monte's controllable flow).

## Next PR needs

- A surplus outlet (hydro spill below observed) if (b) is retried, as a
  new pre-registered change, tested on a year still untouched (2022).
