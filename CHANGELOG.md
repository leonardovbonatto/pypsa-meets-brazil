<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every pull request adds an entry under `[Unreleased]`. CI fails a PR that touches
code without touching this file, unless it carries the `no-changelog` label.

## [Unreleased]

### Added

- Repository scaffold: README, REUSE-compliant licensing, contribution guide,
  pre-commit hooks, ruff configuration, GitHub PR and issue templates (PR-01).
- ADR-0001 recording repository conventions — Conventional Commits, squash-merge,
  the four-layer change log, and the per-PR session budget (PR-01).
- `docs/decisions/`, `docs/data-dictionary/` and `docs/handoffs/` with their
  templates and usage rules (PR-01).
- Feasibility assessment and staged roadmap for the full programme
  (`Brazilian-Grid-in-PyPSA.md`).
- `docs/PRIMER.md` — technical primer covering power system fundamentals, the
  Brazilian sector, optimization and SDDP, the software stack, engineering practice,
  and how to review agent-authored work.
- `pixi.toml` environment pinned to Python 3.12, with `default` and `dev`
  environments and workflow tasks (`dry`, `smoke`, `test`, `lint`) (PR-02).
- Snakemake workflow skeleton: `Snakefile`, `rules/common.smk` and the
  `write_run_manifest` rule emitting the ADR-0001 §4 run manifest (PR-02).
- Default and smoke configurations under `config/` (PR-02).
- GitHub Actions `lint` and `test` workflows; `test` runs unit tests, resolves the
  DAG, executes the smoke workflow and validates the manifest (PR-02).
- `REUSE.toml` covering generated and format-constrained files (PR-02).
- `docs/handoffs/PR-02-workflow-skeleton.md` recording seven environment gotchas
  found while getting the workflow to run (PR-02).
- `scripts/fetch.py` — the fetch/provenance core: streams a URL to disk and
  writes the `resources/_provenance/<source>/<dataset>.json` record consumed
  by `write_manifest.py`, with a small CLI for standalone use (PR-03).
- `scripts/_inspect.py` — samples a fetched CSV and emits the
  `docs/data-dictionary/` YAML, plus `to_pandera_schema()` to validate a
  later fetch of the same dataset against a committed dictionary (PR-03).
- `scripts/check_meta.py` and `.github/workflows/meta.yml` — CI checks that a
  code PR touches the changelog, every committed provenance record has the
  required keys, and ADR numbers are unique (PR-03).
- `requests` and `pandera` added to `pixi.toml` (PR-03).
- `docs/handoffs/PR-03-fetch-provenance-schema-core.md`.
- First real data connector: `rules/fetch.smk` and `scripts/fetch_dataset.py`
  fetch ONS *Curva de Carga* (hourly verified load per subsystem) into
  `resources/ons/`, writing a committed provenance record per file (PR-04).
- `docs/data-dictionary/ons/curva_carga.yaml` — the first real data
  dictionary, generated from the 2024 file and annotated by hand with ONS's
  own field definitions, the MWmed unit, and the timezone and subsystem-code
  traps (PR-04).
- `sources:` block in `config/config.default.yaml` and a `fetch_all` target,
  deliberately outside `rule all` so CI never reaches the network (PR-04).
- CLI for `scripts/_inspect.py`, so dictionaries can be generated directly
  from a fetched file (PR-04).
- `test/test_data_dictionaries.py` — validates committed dictionaries against
  a real committed slice of upstream data, and requires every dictionary to
  carry per-column descriptions and notes (PR-04).
- `docs/handoffs/PR-04-ons-load-connector.md`.
- `docs/STACK.md` — companion to the primer covering the *tooling* rather than
  the domain: every layer from WSL2 up to this project's own conventions, what
  each tool is for, its engineering equivalent, and which parts are built versus
  still planned. 12 mermaid diagrams.
- `rules/build.smk` and `scripts/build_demand.py`: the T0 tidy demand series,
  `resources/demand_t0.csv`, one row per `(snapshot, subsystem)` in MW. Ready
  for a PyPSA `n.loads_t.p_set` build step to pivot directly (PR-05).
- `scripts/_common.py::snapshot_years()` derives which yearly files to fetch
  and build from `config.snapshots.start`/`end`, replacing a separate `years:`
  list that could silently drift out of sync with the modelled range (PR-05).
- `build_all` Snakemake target, alongside `fetch_all`. Both stay outside `all`
  since they reach the network or its downstream artifacts (PR-05).
- `docs/handoffs/PR-05-t0-demand-series.md`.
- `pypsa` added to `pixi.toml` — the first domain modelling dependency to
  land. `scripts/build_network.py` and `rules/build.smk::build_network_t0`
  build the bare T0 `Network`: one bus per subsystem, snapshots from config,
  the T0 demand series attached as time-varying loads. No generators, no
  lines, no solver yet (PR-06).
- `docs/handoffs/PR-06-bare-t0-network.md`.
- Second real data connector: `rules/fetch.smk::fetch_ons_capacidade_geracao`
  fetches ONS installed generating capacity (per generating unit, 5631 rows,
  current snapshot). `docs/data-dictionary/ons/capacidade_geracao.yaml` — the
  second real data dictionary, annotated with ONS's own field definitions and
  a documented finding: the `PY` subsystem code is the Paraguay-frequency
  (50 Hz) side of the binational Itaipu plant, not part of Brazil's 60 Hz SIN
  (PR-07).
- `docs/handoffs/PR-07-ons-capacity-connector.md`.
- `scripts/build_generators.py` and `rules/build.smk::build_generators_t0`:
  aggregate ONS installed capacity to `resources/generators_t0.csv`, one row
  per `(subsystem, technology)`, filtering to active units and excluding `PY`
  (Itaipu 50 Hz — not part of Brazil's SIN). `build_network.py::attach_generators()`
  attaches these to the T0 network as one `Generator` per row. Capacity and
  topology only — no marginal cost, no availability profile, `n.optimize()`
  still not callable (PR-08).
- `docs/handoffs/PR-08-t0-generator-capacity.md`.
- Third real data connector: `rules/fetch.smk::fetch_ons_cvu_usina_termica`
  fetches ONS thermal-plant variable cost (CVU), weekly per plant, one file
  per year (4881 rows for 2024). `docs/data-dictionary/ons/cvu_usina_termica.yaml`
  — records the R$/MWh unit, that CVU genuinely varies week to week (not
  noise), and that this dataset's plant IDs/names do not join cleanly against
  `capacidade_geracao`'s (PR-09).
- `docs/handoffs/PR-09-ons-cvu-connector.md`.
- `scripts/build_costs.py` and `rules/build.smk::build_costs_t0`: reduce
  weekly per-plant CVU to one R$/MWh value per subsystem (mean across all
  plants and weeks, real zero-cost plants included).
  `build_network.py::attach_marginal_costs()` sets this on the T0 network's
  thermal generators, and an explicit documented `0.0` default (not an
  accidental one) on hydro/wind/solar/nuclear. Still no lines, no
  availability profile, no solver — `n.optimize()` still not callable
  (PR-10).
- `docs/handoffs/PR-10-t0-marginal-cost.md`.
- `highspy` (HiGHS) added to `pixi.toml` as an explicit dependency — the
  first solver this project can actually call. `scripts/solve_network.py`
  runs `n.optimize()` and writes a dispatch summary that always carries a
  `known_limitations` list, so a result can't be read without it.
  `build_network.py::attach_load_shedding()` adds an always-available,
  high-cost slack generator per bus, discovered to be necessary because the
  `S` subsystem's own capacity falls short of its own peak demand in 2 of
  8784 hours (267 MWh/year) — with no transmission lines yet, that made the
  network genuinely infeasible without one. Its dispatch is the honest,
  quantified signal for exactly that gap (PR-11).
- `rules/solve.smk::solve_network_t0` and a `solve_all` target, kept outside
  `all` like `fetch_all`/`build_all` (PR-11).
- `docs/handoffs/PR-11-t0-solve.md`.
- `docs/decisions/ADR-0006-t0-transfer-representation.md` — T0 models
  inter-subsystem connections as PyPSA `Link`s (a transport model), not
  `Line`s: real impedances need DESSEM/ANAREDE deck parsing (ADR-0003, T3
  only). Topology and a transfer-capacity proxy both come from real data,
  not assumption.
- Fourth real data connector: `rules/fetch.smk::fetch_ons_intercambio_nacional`
  fetches ONS real hourly inter-subsystem interchange (signed, MWmed).
  `docs/data-dictionary/ons/intercambio_nacional.yaml` — confirms the SIN's
  real T0-relevant topology is exactly four boundaries (`N-NE`, `N-SE`,
  `NE-SE`, `SE-S`; no direct `N-S` or `NE-S`), and records the sign
  convention and the ONS-dictionary/data mismatch pattern seen again here
  (PR-12).
- `docs/handoffs/PR-12-ons-interchange-connector.md`.
- `scripts/build_links.py` and `rules/build.smk::build_links_t0`: reduce the
  real interchange series to one transfer-capacity row per real boundary
  (`p_nom = max(abs(flow))`, per ADR-0006). `build_network.py::attach_links()`
  attaches these as bidirectional PyPSA `Link`s. Re-solving after this
  resolves PR-11's `S` infeasibility completely (`load_shedding_mwh_by_bus`
  goes to `{}`) — and reveals a new, real finding: with subsystems now able
  to trade power, national free-generation capacity so comfortably exceeds
  even peak demand that thermal generation dispatches at exactly 0 MW for
  every hour of 2024. A genuine consequence of the still-open "no
  availability profile" gap, not a bug (PR-13).
- `docs/handoffs/PR-13-t0-transfer-links.md`.
- Fifth real data connector: `rules/fetch.smk::fetch_ons_fator_capacidade`
  fetches ONS real hourly wind/solar capacity factor, per plant-group, one
  file per (year, month) since this dataset is large (~37-40 MB/month).
  `scripts/_common.py::snapshot_year_months()` derives which (year, month)
  pairs to fetch, the month-level analogue of `snapshot_years()`.
  `docs/data-dictionary/ons/fator_capacidade.yaml` — records that
  `val_fatorcapacidade` is exactly PyPSA's `p_max_pu` definition, that a
  small fraction of real values exceed 1.0 (must be clipped), and a real,
  verified gap: `SE_CO` has zero wind rows in this dataset in every month
  checked, despite having ~261 MW of registered wind capacity (PR-14).
- `docs/handoffs/PR-14-ons-capacity-factor-connector.md`.
- `scripts/build_availability.py` and `rules/build.smk::build_availability_t0`:
  aggregate the real capacity-factor data into an hourly `p_max_pu` per
  `(subsystem, technology)` — the aggregate fleet capacity factor
  (sum generation / sum capacity), clipped to `[0, 1]`.
  `build_network.py::attach_availability()` sets it on the matching
  generators; anything uncovered (only `SE_CO wind`) keeps PyPSA's 1.0
  default, explicitly documented rather than silent. Wind's mean dispatch
  duly falls from 12,655 to 8,855 MW — but thermal dispatch stays at
  exactly 0 MW, and isolating why produced the more important finding
  below (PR-15).
- `docs/handoffs/PR-15-t0-availability-profile.md`.
- `scripts/solve_network.py::summarize_prices()` — records mean
  `marginal_price` per bus (R$/MWh, the CMO validation target) in the
  dispatch summary, plus an explicit `all_prices_zero` flag and a runtime
  warning for the *economically degenerate* case where a zero-cost
  generator always has headroom so nothing scarce ever sets a price. That
  is the current state, and it was previously invisible without manually
  inspecting the solved network (PR-16).
- `docs/handoffs/PR-16-report-marginal-prices.md`.

### Changed

- `REUSE.toml` now attributes ONS-derived files (fixtures, data dictionaries)
  to ONS rather than to this project. Their data is CC-BY, and attribution is
  what that licence requires (PR-04).
- Renamed `test/fixtures/ons_carga_sample.csv` to `synthetic_load_sample.csv`:
  it is invented data, and the old name implied otherwise now that real ONS
  fixtures sit beside it (PR-04).
- `config.default.yaml`: removed `sources.ons.curva_carga.years`, now derived
  from `snapshots` instead of listed separately (PR-05).
- `scripts/build_demand.py`'s subsystem mapping moved to the new shared
  `scripts/_ons.py`, since `build_generators.py` needs the identical mapping
  (PR-08).
- `docs/data-dictionary/ons/fator_capacidade.yaml` regenerated from all 12
  months of 2024 rather than January alone. A January-only sample had no
  nulls in `val_latitudesecoletora`, so the derived schema marked it
  non-nullable and pandera then rejected the real full-year frame (16,848
  nulls). Generalized lesson recorded in the dictionary's notes: build a
  dictionary from the same data volume that will be validated against it
  (PR-15).
- `scripts/solve_network.py::KNOWN_LIMITATIONS` rewritten: the old entries
  claimed "no transmission lines" and "no availability profile", both since
  fixed. It now leads with the real dominant caveat — hydro is unconstrained
  and free — because a stale caveat naming an already-fixed problem is as
  misleading as a missing one (PR-15).

[Unreleased]: https://github.com/leonardovbonatto/pypsa-meets-brazil/commits/main
