<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-27 — ENA connector (ADR-0005 stage 1b)

**Landed:**

- `rules/fetch.smk::fetch_ons_ena_subsistema` + `config.default.yaml`'s
  `sources.ons.ena_subsistema` entry - real S3 URL, year-wildcarded.
- `scripts/_common.py::inflow_history_years()` - its own year range,
  independent of `snapshots.start/end`.
- `docs/data-dictionary/ons/ena_subsistema.yaml` - built from the full
  26-year (2000-2025), 37,988-row volume.
- `rules/build.smk::build_inflow` + `scripts/build_inflow.py` - tidy
  (date, subsystem) table, all four ENA figures.
- `test/test_build_inflow.py`, `test/fixtures/ons/ena_subsistema_sample.csv`,
  and a new `TestInflowHistoryYears` class in `test/test_manifest.py`.

Same fetch → dictionary → tidy shape as the six existing ONS connectors,
per ADR-0005's explicit scoping for this PR. No PAR(p) fitting yet - that
stays the next PR's job.

## The CKAN blocker from PR-26, resolved

PR-26's handoff flagged that `dados.ons.org.br`'s CKAN search/show API
rate-limited after one successful call. Sidestepped it entirely this
session: ONS's S3 bucket allows anonymous listing.
```
curl "https://ons-aws-prod-opendata.s3.amazonaws.com/?list-type=2&prefix=dataset/ena"
```
returned every ENA dataset folder directly - `ena_bacia_di` (basin),
`ena_ree_di` (REE), `ena_reservatorio_di` (reservoir), `ena_subsistema_di`
(subsystem) - without touching the CKAN API at all. **This is a better
research method than CKAN search for any future connector**: list the S3
bucket by prefix first, only fall back to CKAN if the prefix guess fails.

## What was found, not assumed

- **Real date range confirmed**: `ena_subsistema_di` has one CSV per year,
  2000 through 2026 (2026 partial, in progress - fetched only through
  2025). Matches PR-26's carried-forward preliminary estimate almost
  exactly, now independently verified rather than inherited.
- **Daily, not hourly** - a real structural difference from every other
  connector in this project. `ena_data` is a plain calendar date, no
  time-of-day component, no stated timezone in ONS's own dictionary
  (documented explicitly since it's an absence, not a confirmed fact).
- **A genuine unit discrepancy, not resolved by more reading**: ONS's own
  `DicionarioDados_EnaPorSubsistema.json` says `ena_bruta_regiao_mwmed`'s
  unit is "MWmes" (MW-month); the column name says "mwmed" (MW-average,
  this project's convention everywhere else). Reasoned to MWmed from
  PRIMER Sec 2.4's definition (ENA = flow x productivity, a power-equivalent
  quantity) and value magnitudes matching subsystem-scale power figures,
  not some larger month-scaled number - but this is inference, written
  down as inference in the data dictionary's notes, not asserted as fact.
  **Re-check before the PAR(p) PR does unit arithmetic that depends on it.**
- **No nulls anywhere** across the full volume - clean dataset, unlike
  several earlier ONS connectors.
- **`storable <= gross` holds on every row** in the real data - added as
  an actual raised-not-silent check in `build_tidy_inflow()`, the same
  discipline as PR-17/18's population-mismatch checks.

## Design choices worth knowing

- **`inflow_history_years()` is deliberately independent of
  `snapshot_years()`** - the single biggest structural difference from
  every prior connector. Capped the fetch at 2025 (last complete year);
  2026 exists upstream but is mid-year, and a partial trailing year
  entering a persistence-statistics fit silently would be a real bug
  waiting to happen, not a free extra data point.
- **All four ENA columns kept tidy**, not reduced to one. Unlike
  `build_demand.py` (exactly one real load column), this connector has no
  clear single "the" column yet - gross vs. storable, MWmed vs. %-of-MLT
  are all legitimate candidates for what PAR(p) actually fits on. Picking
  now would be a modelling decision smuggled into a connector PR.
- **`build_inflow` is not wired into `build_network_t0`** - this feeds the
  separate, still-PLANNED SDDP/PAR(p) pipeline. T0's network still uses
  ADR-0007's hydro backcast, untouched by this PR.

## Gotchas

- The dictionary-build YAML had a real bug on the first attempt: an
  unquoted note starting with `"Row-level cross-check: ..."` broke YAML
  parsing (a bare `:` right after a short prefix reads as a mapping key).
  Every dictionary note with an early colon needs single-quoting, matching
  the convention already used elsewhere in this file - not consistently
  applied until this bug surfaced it.
- `git status` initially showed 26 new provenance JSON files, one per
  fetched year - expected and correct (every fetch commits its own
  provenance record, ADR-0001 Sec 4), not something to squash or hide.

## Next PR needs

**PAR(p) fitting.** Fit on `resources/inflow_ena.csv`, validated against
the two properties PRIMER Sec 4.7 requires before it feeds SDDP.jl at
all: persistence (dry periods must cluster realistically) and spatial
correlation across subsystems (independent per-subsystem sampling would
understate true system risk). This PR's open unit question should be
resolved or at least re-verified before that fitting does arithmetic that
assumes MWmed.

After that, per ADR-0005's order: a first expectation-only SDDP policy on
real ENA data (using PR-26's now-proven coupling mechanism), then CVaR,
then individualized reservoirs (a future ADR).

## Open questions

- Whether "MWmes" in ONS's dictionary is a typo or a real distinct unit -
  unresolved, documented as an open inference in the data dictionary.
- Whether REE-level (`ena_ree_di`, finer than subsystem, coarser than
  reservoir) would be a better fit than subsystem-level once PAR(p)
  fitting starts - subsystem was chosen to match T0's own 4-subsystem
  granularity exactly, but REE is the level PRIMER Sec 2.4 names as the
  traditional Brazilian aggregation unit for this exact purpose.
