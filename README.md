<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# pypsa-meets-brazil

An open, nodal model of the Brazilian National Interconnected System (SIN) in
[PyPSA](https://pypsa.org) — with real hydro physics and stochastic water values,
reducible to any spatial resolution.

> **Status: early build, T0 only.** The 4-subsystem T0 tier fetches real 2024 ONS
> data, builds a PyPSA network, and solves it end-to-end — thermal, wind, solar,
> hydro, nuclear, MMGD and small-plant generation, inter-subsystem transfer,
> marginal prices. Hydro in the T0 solve is a **backcast** from observed
> generation (ADR-0007). An SDDP.jl water-value policy coupled into PyPSA exists
> (ADR-0014) but fails its pre-registered 2024 backtest on price (ADR-0015,
> `docs/handoffs/PR-57-*.md`); that line is paused. The roadmap's Phase 1 gate
> (ADR-0020) is scored and T0 fails it: with wind and solar availability before
> curtailment (ADR-0023) T0 over-produces wind, having no congestion inside a
> subsystem. The **T1 tier (27 states, ADR-0022)** is built on DLR's topology and
> ONS 2024 data; on 2024 it reproduces ONS's interchange on all four boundaries
> and its wind and solar within 1.5% (post hoc, `docs/handoffs/PR-71-*.md`). The
> pre-registered out-of-sample test on 2025 (ADR-0024) fails, 4 of 8: wind and
> solar over-produce and the two N boundaries miss (`docs/handoffs/PR-72-*.md`).
> T2–T3 (clustered, nodal) are not started.
> See [`docs/STACK.md`](docs/STACK.md) for exactly what's built vs planned, and
> [`Brazilian-Grid-in-PyPSA.md`](Brazilian-Grid-in-PyPSA.md) for the feasibility
> study and staged roadmap this project is built on.

## What this is

Brazil is unusually well served by open data — ONS publishes hourly generation
*per plant*, per-plant curtailment, thermal variable costs, forced outage rates and
daily reservoir hydraulics. Very few countries offer that. What does not exist is an
open model that puts it together at nodal resolution with credible hydro physics.

This project builds one, in four tiers derived from a single source of truth:

| Tier | Resolution | Purpose |
|------|-----------|---------|
| **T3** | Nodal ≥230 kV, unit-level generators | Highest fidelity; congestion and curtailment studies |
| **T2** | ~100–300 clustered nodes | Planning workhorse |
| **T1** | 27 federal states | Benchmarkable against published models |
| **T0** | 4 subsystems + isolated systems | Fast iteration; stochastic hydro policy development |

Every reduced tier is produced by clustering the nodal model — not hand-built
separately. Subsystem boundaries (SE/CO, S, NE, N) survive aggregation as hard
constraints.

## The distinctive part

The official Brazilian chain (NEWAVE → DECOMP → DESSEM) has authoritative hydro
stochastics but is closed-source and network-light at the long-term end. This project
decouples the same way, in the open:

```
VAZOES.DAT (1931–)  →  PAR(p) inflow model  →  SDDP.jl policy (CVaR)
                                                      │
                                              Benders cuts (Parquet)
                                                      ▼
                              PyPSA nodal dispatch + cost-to-go variable α
```

A full nodal network optimised against *stochastic* water values is something the
official chain does not deliver in a single model.

## Layout

```
Snakefile          workflow entrypoint, includes rules/*.smk
config/            one config per tier, plus a CI-runnable smoke config
rules/             Snakemake rule groups
scripts/           one importable, testable module per rule
resources/         intermediate artifacts (gitignored, except _provenance/)
results/           model outputs + run manifests (gitignored)
docs/decisions/    Architecture Decision Records
docs/data-dictionary/  committed schema snapshots — read these, not raw data
docs/handoffs/     per-PR session handoff notes
test/fixtures/     tiny real-shaped samples (committed)
julia/             SDDP.jl subproject (ADR-0005) — its own pixi environment

data/              (planned, not yet created) small static inputs
```

## Getting started

Requires WSL2/Ubuntu (or Linux/macOS) — Snakemake is not supported on native Windows.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the full bootstrap.

```bash
pixi install
pixi run snakemake -n                                        # dry-run
pixi run snakemake -j4 --configfile config/test/config.smoke.yaml
```

## Data sources

All inputs are open. Primary: [ONS Dados Abertos](https://dados.ons.org.br/),
[ANEEL Dados Abertos](https://dadosabertos.aneel.gov.br/) (SIGA, SIGET, SIGEL, BDGD, MMGD),
[EPE Webmap](https://gisepeprd2.epe.gov.br/WebMapEPE/), ERA5 via
[atlite](https://github.com/PyPSA/atlite), and CEPEL model decks parsed with
[`inewave`](https://github.com/rjmalves/inewave) / [`idessem`](https://github.com/rjmalves/idessem).

Every fetch records its provenance (source URL, timestamp, sha256, row count, schema
hash) under `resources/_provenance/`, which is committed. You can always answer which
vintage of upstream data produced a given result.

## Related work

- [PyPSA-Earth](https://github.com/pypsa-meets-earth/pypsa-earth) — global, OSM-derived; this project follows its workflow architecture
- [PyPSA-Eur](https://github.com/PyPSA/pypsa-eur) — the conventions used here (pixi, `rules/`, `scripts/`)
- [DLR Open Brazilian Energy Data](https://gitlab.com/dlr-ve/esy/open-brazil-energy-data/open-brazilian-energy-data) — 27-node, 2012–2020; used here as a regression benchmark

## Licence

Code MIT, documentation CC-BY-4.0, OSM-derived artifacts ODbL-1.0.
[REUSE](https://reuse.software)-compliant — see `LICENSES/` and [ADR-0002](docs/decisions/).
