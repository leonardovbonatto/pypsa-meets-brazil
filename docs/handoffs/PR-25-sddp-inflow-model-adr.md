<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-25 — ADR-0005: inflow model formulation (SDDP epic, stage 1)

**Landed:** no code. The SDDP epic's first ADR - fills the slot reserved
since `docs/decisions/README.md`'s index was written, deciding how the
epic starts rather than starting to build blind.

## The decision, in one line

Start with ONS's own open ENA data (CC-BY, REE/subsystem level) and a
Julia/SDDP.jl feasibility smoke test *before* touching real Brazilian
data - not the NEWAVE-deck route (`VAZOES.DAT`), not individualized
reservoirs, not CVaR. Full reasoning in `docs/decisions/ADR-0005-*.md`.

## What was actually checked this session, not assumed

- **Julia is installable.** `pixi search -c conda-forge julia` returns
  `julia-1.12.7`, linux-64, no credential wall. This does *not* mean
  SDDP.jl (a Julia-registry package, not conda) installs or runs cleanly
  - untested. That's exactly why the epic's first PR is a smoke test, not
  the real data pipeline.
- **ONS's ENA data is real.** One live CKAN API call
  (`package_show?id=ena-diario-por-reservatorio`) returned full metadata:
  CC-BY licence, 62 resources, real. Every subsequent call - same
  endpoint, same headers, from both WSL and the Windows-side network path
  - 403'd. Not a WSL-specific block (ruled out by testing both paths);
  looks like rate-limiting on the CKAN search/show API specifically. This
  matters for the next PR: **every existing ONS connector in this repo
  downloads from `ons-aws-prod-opendata.s3.amazonaws.com` directly, never
  the CKAN API** - the ENA connector should do the same once the exact
  S3 resource URL is known, not depend on CKAN search being reliably
  reachable.
- **A prior session's ENA date-range claims (subsystem 2000-2026, REE
  2016-2026) were NOT re-verified line-for-line** - the rate-limiting hit
  before that was possible. Carried into the ADR as "prior preliminary
  research," explicitly flagged as needing the connector PR's own fresh
  check, per this project's own PR-15 lesson (verify against the volume
  you'll actually validate against, don't inherit a claim).

## Found while researching, fixed in the same PR

Two more instances of the stale-forward-reference pattern PR-23 already
named and fixed elsewhere, found by reading PRIMER §4 closely for this
ADR rather than a dedicated sweep:
- PRIMER §4.6 cited "Gate D in the plan" - no such gate exists; the
  roadmap uses numbered phases 0-9, not lettered gates. Removed.
- `docs/decisions/README.md`'s index guessed specific future PR numbers
  for ADR-0002/0004 (`Planned (PR-08)`, `Planned (PR-27)`) - same fragile
  pattern, real numbering has never matched an early guess anywhere else
  in this repo. Stripped to plain `Planned`.

## Key files

- `docs/decisions/ADR-0005-inflow-model-formulation.md` - the decision.
- `docs/decisions/README.md` - index updated.
- `docs/PRIMER.md` §4.6 - one stale reference removed.

## Gotchas

- The CKAN rate-limiting above - budget for retry/backoff logic in the
  ENA connector PR, or just target S3 directly and skip CKAN search
  entirely (preferred - matches every existing connector).
- ADR-0005 explicitly does *not* decide CVaR parameters, stage count, or
  monthly vs. weekly resolution - deliberately deferred to keep this ADR
  to the one question its slot was reserved for (inflow *data source and
  aggregation*), not the whole epic's design.

## Next PR needs

**PR-26 (or whichever number): Julia/SDDP.jl environment feasibility
smoke test.** Install Julia + SDDP.jl, solve SDDP.jl's own textbook
two-stage hydrothermal example, prove the Snakemake → Parquet coupling
works end-to-end on a toy problem. Deliberately no Brazilian data yet -
isolates the coupling-mechanism risk from the data-modelling risk, per
this ADR's staged order.

After that: the ENA connector (same shape as the six existing ONS
connectors), then PAR(p) fitting with the persistence/spatial-correlation
validation PRIMER §4.7 requires, then a first expectation-only SDDP
policy, then CVaR, then individualized reservoirs (a future ADR
superseding this one).

## Open questions

- Exact ENA date coverage per aggregation level - deferred to the
  connector PR's own fresh check (see Gotchas).
- Whether SDDP.jl's Julia-registry install is smooth in this pixi/WSL2
  environment at all - the single biggest unknown the smoke-test PR
  exists to resolve.
