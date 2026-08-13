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

[Unreleased]: https://github.com/leonardovbonatto/pypsa-meets-brazil/commits/main
