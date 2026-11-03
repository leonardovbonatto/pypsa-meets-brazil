<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-47 — CMO connector, the backtest target

**Landed:**

- `config.default.yaml` `cmo_semanal` (2005-2024) and `cmo_semi_horario`
  (2020-2024); `rules/fetch.smk::fetch_ons_cmo_semanal` /
  `fetch_ons_cmo_semi_horario`; both added to `fetch_all`.
- `scripts/build_cmo.py` + `rules/build.smk::build_cmo` ->
  `resources/cmo_weekly.csv` and `resources/cmo_monthly.csv`.
- `docs/data-dictionary/ons/cmo_semanal.yaml` / `cmo_semi_horario.yaml`, from
  the full volume (4,172 and 343,680 rows).
- `test/test_build_cmo.py` (15 tests) and two real fixtures.

Step 1 of the source-integration plan (`Brazilian-Grid-in-PyPSA.md` §8): the
roadmap's Phase 7 gate is a backtest against CMO, and nothing in the repo
held CMO until now. Same S3-listing method as PR-27; both datasets are CC-BY.

## Findings, each measured on the full volume

1. **The weekly date ends the operating week.** ONS's dictionary says only
   "reference date". Every value is a Friday, and on 2024 the weekly means
   correlate 0.920 with half-hourly means over the seven days ending on it,
   against 0.895 for the seven starting on it. Moderate evidence, since the
   two series come from different models (DECOMP vs DESSEM).
2. **The half-hourly files miss whole days**, 1 to 16 per year, always all
   subsystems together: 2020: 1, 2021: 2, 2022: 16, 2023: 14, 2024: 4. The
   build keeps them out and reports `coverage` per month; a partial day or
   subsystems disagreeing raises. Only 2022-12 and 2023-01 fall below 90%.
3. **Negative CMO is real**, small, and mostly NE (77 half-hours in
   August-September 2024, minimum -10.44). It coincides with NE's wind
   surplus season, a lead for the curtailment work.
4. **One half-hour of R$54,729.62/MWh** in N on 2020-10-10, the other
   subsystems near 300. Kept; `cmo_median` sits beside `cmo_mean` so it
   cannot pass for a month's level.
5. The weekly mean is labelled "R$/MW" in ONS's dictionary, almost certainly
   a typo: it always lies within its R$/MWh load blocks.

## The 2024 target, monthly mean of half-hourly CMO, R$/MWh

| | Jan-May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|
| SE_CO | 0.8-8.3 | 26 | 78 | 111 | 366 | 516 | 152 | 14 |
| N | 2.2-9.9 | 29 | 86 | 117 | 508 | 735 | 470 | 19 |

A wet first half, then the 2024 drought. Seasonal shape is the pass
condition agreed for step 6.

## Gotchas

- `inflow_history_years()` is the year-range helper for any dataset with a
  `years` key, despite its name; reused here rather than duplicated.
- Fixtures must be consecutive weeks: the build raises on any week gap, so a
  hand-picked sample of non-adjacent weeks fails its own check.

## Next PR needs

- Nothing to compare against yet: SDDP produces water values, not CMO, and
  PyPSA prices still come from the hydro backcast. Steps 4 and 5 make the
  comparison meaningful.
- No 2025 files on the bucket as of 2026-11-02; raise `end` when they appear.
