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

### Changed

- `REUSE.toml` now attributes ONS-derived files (fixtures, data dictionaries)
  to ONS rather than to this project. Their data is CC-BY, and attribution is
  what that licence requires (PR-04).
- Renamed `test/fixtures/ons_carga_sample.csv` to `synthetic_load_sample.csv`:
  it is invented data, and the old name implied otherwise now that real ONS
  fixtures sit beside it (PR-04).
- `config.default.yaml`: removed `sources.ons.curva_carga.years`, now derived
  from `snapshots` instead of listed separately (PR-05).

[Unreleased]: https://github.com/leonardovbonatto/pypsa-meets-brazil/commits/main
