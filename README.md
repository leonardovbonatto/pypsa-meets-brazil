<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# pypsa-meets-brazil

An open, nodal model of the Brazilian National Interconnected System (SIN) in
[PyPSA](https://pypsa.org) — with real hydro physics and stochastic water values,
reducible to any spatial resolution.

> **Status: pre-alpha.** Scaffolding only. Nothing here solves a network yet.
> See [`Brazilian-Grid-in-PyPSA.md`](Brazilian-Grid-in-PyPSA.md) for the feasibility
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
data/              small static inputs (committed)
resources/         intermediate artifacts (gitignored, except _provenance/)
results/           model outputs + run manifests (gitignored)
julia/             SDDP.jl subproject
docs/decisions/    Architecture Decision Records
docs/data-dictionary/  committed schema snapshots — read these, not raw data
docs/handoffs/     per-PR session handoff notes
test/fixtures/     tiny real-shaped samples (committed)
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
