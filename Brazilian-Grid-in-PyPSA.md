# Mapping the Brazilian Grid in PyPSA — Feasibility Assessment & Roadmap

*Assessment date: 12 Aug 2026. Scope: nodal + reduced PyPSA models of the SIN, open data inventory, stochastic hydro optimization, distribution/DG coupling.*

---

## 1. Executive verdict

**Doable, and more doable than in most countries.** Brazil is unusually well served by open data: ONS publishes ~83 datasets including *hourly generation per plant*, *per-plant curtailment*, *thermal variable costs (CVU)*, *forced outage rates*, and *daily reservoir hydraulics*. Very few countries give you that. The main gap — electrical parameters of the transmission network — has a viable open route (§2.1).

Three honest calibrations up front:

1. **"As close as possible to reality" is achievable at the ≥230 kV level, not below.** A nodal model of the ONS *Rede de Operação* with real impedances and per-unit generators is realistic within ~6–9 months. Below 230 kV you leave the ONS perimeter and enter BDGD/distribution territory, which is a different modelling problem entirely (§6).

2. **Rivalling SDDP/NEWAVE is a research contribution, not a product replacement.** What is realistic in 12 months: an open SDDP policy over individualized reservoirs with PAR(p) inflows and CVaR risk aversion that *backtests against published ONS CMO and EAR trajectories within a few percent on aggregate metrics*. What is not realistic: a regulatory-grade substitute. PSR's SDDP and CEPEL's NEWAVE carry 30 years of engineering, and the official chain's value comes as much from institutional acceptance as from algorithms. The open version's value is transparency, scenario freedom, and the ability to couple hydro policy to a full nodal network — which the official chain does *not* do in one model.

3. **Don't build the reduced models separately.** Build the nodal model once as the single source of truth and derive every reduced version by clustering. Maintaining parallel hand-built models is where projects like this die.

**The single highest-value lead:** the publicly published **DESSEM decks** contain ANAREDE-format electrical network base cases (`desselet.dat` indexes them per load level), with DC network representation including losses and security constraints, at **unit-generator granularity**. If those decks remain publicly downloadable in their current form, that is your backbone — real topology, real impedances, real limits, refreshed daily. Verify access first; it changes the whole plan. See §2.1 and §9.

---

## 2. Data inventory

Legend: 🟢 open & sufficient · 🟡 open but needs work/assumptions · 🔴 not openly available, needs proxy

### 2.1 Transmission network

| Item | Status | Source | Notes |
|---|---|---|---|
| Line registry ≥230 kV | 🟢 | ONS *Linhas de Transmissão da Rede de Operação* | Subsystem, UF, owner, voltage, length. CSV/XLSX, **updated daily**. No geometry, no impedance. |
| Substation registry ≥69 kV | 🟢 | ONS *Subestação da Rede de Operação* | |
| Transformer capacity | 🟢 | ONS *Capacidade de Transformação da Rede Básica* | |
| **Topology edge list (origin SE → destination SE)** | 🟢 | ANEEL **SIGET** (`Resolução Módulo Linha Transmissão Subestação Origem Subestação Destino.csv`) | This is the graph. Underused; most projects miss it. |
| Line & substation **geometry** | 🟢 | EPE Webmap ArcGIS REST (`gisepeprd2.epe.gov.br/arcgis/rest/services`), ANEEL **SIGEL** | Shapefile / GeoJSON / WMS. Existing + planned. |
| **Electrical parameters (R, X, B), thermal ratings, taps** | 🟡 | **DESSEM decks (ANAREDE cases)** — primary route; ONS *casos de referência* (agent-restricted) — authoritative route | Not in any tabular open dataset. Fallback: typical Ω/km per voltage class × bundle from EPE PET/PELP and ONS submodules — good enough for DC-OPF, poor for AC. |
| Geometry gap-fill / routing | 🟡 | OpenStreetMap (~305,000 km mapped in BR) | Use via `earth-osm`. **ODbL is viral** — a derived network DB inherits it. Decide early whether you want that. |
| Planned expansion | 🟢 | ONS PAR/PEL, EPE PDE 2035, ANEEL transmission auctions | For expansion scenarios. |

**Verdict:** topology and geometry are solved. Impedances are the one real gap, with DESSEM decks as the likely answer and typical-parameter synthesis as the guaranteed fallback. A DC-OPF nodal model is fully feasible either way; a credible AC model depends on the deck route working out.

### 2.2 Generation

| Item | Status | Source |
|---|---|---|
| Plant registry (all sources, all statuses, coordinates) | 🟢 | ANEEL **SIGA** (~10.5k units in the 2023 DLR snapshot) |
| Installed capacity, commissioning dates | 🟢 | ONS *Capacidade Instalada de Geração*, SIGA |
| **Hourly generation per plant** | 🟢 | ONS *Geração por Usina em Base Horária* |
| **Thermal variable cost (CVU) per plant** | 🟢 | ONS *CVU das Usinas Térmicas* — direct marginal-cost calibration |
| Availability / outages | 🟢 | ONS *Dados de Disponibilidade de Usinas*, *Taxas TEIFa e TEIP* (forced outage rates → stochastic/adequacy studies) |
| **Wind & solar curtailment per plant** | 🟢 | ONS *Restrição de Operação por Constrained-off* (eólicas & fotovoltaicas, per-plant detail) |
| Wind/solar realized capacity factors | 🟢 | ONS *Fator de Capacidade de Geração Eólica e Solar* |
| Per-generating-unit data | 🟡 | ONS *Indicadores... por Unidade Geradora*; DESSEM decks model UG-level; `hidr.dat` gives hydro machine groups |
| Dispatch reason (merit vs. constraint) | 🟢 | ONS *Geração Térmica por Motivo de Despacho* |
| Thermal technical minima, ramp rates, start costs | 🟡 | DESSEM decks (`entdados.dat`) — otherwise assumed by technology |

**Verdict:** the best-instrumented layer. Per-plant hourly generation plus per-plant CVU plus per-plant curtailment is a validation dataset most modellers don't get.

### 2.3 Hydro & inflows

| Item | Status | Source |
|---|---|---|
| **Hydro plant physical cadastre** (cota-volume/cota-área polynomials, produtibilidade, tailrace, turbine limits, evaporation) | 🟢 | **`hidr.dat`** — distributed inside NEWAVE decks, read with `inewave`. Essential; there is no substitute. |
| **~95-year monthly natural inflow series per plant (1931–)** | 🟢 | **`VAZOES.DAT`** in NEWAVE decks — the standard basis for PAR(p) inflow modelling in Brazil |
| Daily/hourly reservoir operation (afluente, defluente, vertida, turbinada, nível) | 🟢 | ONS *Dados Hidráulicos por Reservatório* (hourly + daily) |
| ENA & EAR (reservoir / REE / subsystem / basin, daily) | 🟢 | ONS |
| Fluviometric measurements | 🟢 | ONS *Grandezas Fluviométricas*; ANA HidroWeb (daily series, national) |
| Flood-control volumes | 🟢 | ONS *Volume de Espera Recomendado* |
| Observed precipitation | 🟢 | ONS *Precipitação Diária Observada* |
| Basin geometry | 🟢 | ONS *Contornos das Bacias Hidrográficas* (shapefile) |
| Multi-use/irrigation constraints, hydraulic coupling rules | 🟡 | Partially in `operuh.dat` (DECOMP/DESSEM); the rest is in ONS operating procedures as prose |

**Verdict:** everything needed for individualized reservoir modelling is obtainable. `hidr.dat` + `VAZOES.DAT` are the crown jewels and both come free with the decks.

### 2.4 Demand

| Item | Status | Source |
|---|---|---|
| Semi-hourly verified load by load area, incl. MMGD share | 🟢 | ONS *Carga de Energia Verificada* |
| Hourly load curve, daily/monthly energy | 🟢 | ONS |
| Scheduled load (DESSEM input) | 🟢 | ONS *Carga de Energia Programada* |
| Subsystem interchange | 🟢 | ONS *Intercâmbios Entre Subsistemas*, *Intercâmbio do SIN com Outros Países* |
| Roraima (isolated) | 🟢 | ONS *Carga global de Roraima* |
| **Load allocation to individual buses** | 🔴 | Not published. Must be disaggregated — by load area → municipality (IBGE population/GDP, EPE consumption by class) → nearest substation. This is a modelling assumption, own it explicitly. |
| Demand scenarios to 2050 | 🟢 | EPE PDE 2035, DLR harmonized dataset (IEA/EPE/academic) |

### 2.5 Weather

| Item | Status | Notes |
|---|---|---|
| ERA5 / ERA5-Land reanalysis | 🟢 | Via `atlite`. Standard route. |
| Bias correction | 🟡 | ERA5 wind is biased **low ~20%** and solar biased **high** in the literature. **Do not** blanket-apply GWA3 correction — evidence says it can be detrimental. Use quantile/Weibull quantile mapping. |
| **Brazil-specific advantage** | 🟢 | You can bias-correct against ONS **per-plant hourly generation** and published capacity factors. Very few countries allow plant-level calibration. Do this — it is your differentiator. |
| Ground stations | 🟢 | INMET automatic stations |
| Alternatives | 🟢 | MERRA-2, NASA POWER, CFSR, Global Wind Atlas 3 (siting only) |

### 2.6 Distribution & distributed generation

| Item | Status | Notes |
|---|---|---|
| **BDGD** — full georeferenced distribution network, all distributors, annual | 🟢 | ANEEL open data. Enormous (a geodatabase per distributor). |
| BDGD → OpenDSS converters | 🟢 | `bdgd2opendss` / `bdgd-tools` (eniocc), `bdgd2dss` (ArthurGS97) — active, peer-reviewed (SBAI/CBA) |
| MMGD registry (per connection: power, source, municipality, distributor, date) | 🟢 | ANEEL *Relação de empreendimentos de MMGD* + technical info (inverter make, module, blade height) |
| MMGD share of load, historical | 🟢 | Embedded in ONS *Carga Verificada* components |
| MV/LV → transmission bus mapping | 🔴 | Requires spatial join BDGD feeders ↔ substations; doable but bespoke |

---

## 3. What is genuinely *not* available

- **Impedances/ratings as a clean open table.** Only via decks or synthesis.
- **Bus-level load allocation.** Always a modelling assumption in Brazil.
- **Bilateral contract positions and agent-level commercial data.** CCEE aggregates only. Irrelevant for physical dispatch, fatal if you wanted to model market behaviour.
- **Protection settings, dynamic models, stability data.** Out of PyPSA's scope anyway.
- **Full ANAREDE reference cases** direct from ONS — restricted to accessing agents.
- **CEPEL model source code.** NEWAVE/DECOMP/DESSEM are closed and moved to subscription licensing in 2025 (now Gurobi-integrated). The *decks* are data, not code — reusable, but check current terms.
- **Detailed multi-use water constraints** (irrigation, navigation, sanitation withdrawals) beyond what's encoded in `operuh.dat`.

---

## 4. Where the DLR dataset fits (your link)

[`dlr-ve/esy/open-brazil-energy-data`](https://gitlab.com/dlr-ve/esy/open-brazil-energy-data/open-brazilian-energy-data) — BSD-3 code, mostly ODbL data, published with the *Scientific Data* paper (Deng et al., 2023).

**Use it for:**
- **Tier-1 reduced model, near-free.** 27 nodes = federal states (ISO 3166-2), aggregated network from EPE Webmap with existing + planned variants, 10,541 plants from SIGA, hourly load disaggregated to states, ENA→hourly hydro inflows, VRE potentials at 0.09°, demand scenarios to 2050, cross-border exchange.
- **The provenance chain.** They already did the tedious work of mapping ANEEL/ONS/EPE fields onto PyPSA attributes. Mine that even if you don't use their numbers.
- **Benchmark.** Your rebuilt 27-node model should reproduce theirs. If it doesn't, you have a bug.

**Do not use it as your backbone:**
- Data is **2012–2020** — roughly six years stale as of now, and Brazil added enormous wind/solar/MMGD capacity since.
- State-level aggregation only. No path to nodal from it.
- Transfer capacities are **heuristic** ("four bundles of conductors" per line by voltage class), not real ratings.
- Hydro inflows disaggregated to states by installed-capacity share — fine zonally, wrong for individualized reservoir optimization.
- Known validation weaknesses they state honestly: wind correlation 0.23–0.58 vs. observations; solar MBE −7% to −36%; 847 plants with imputed coordinates.

**Net:** adopt as Tier 1 and as a methodology reference, refresh its inputs to 2026, and build the nodal tiers independently.

---

## 5. Proposed architecture

### Model tiers — one source of truth, clustered downward

```
T3  Nodal, unit-level        ~2–4k buses ≥230 kV, generators per unidade geradora
     │                        DESSEM/ANAREDE backbone + SIGET + SIGEL/EPE geometry
     │  cluster
T2  Nodal, clustered         ~100–300 nodes — planning workhorse
     │  cluster
T1  27 states                DLR-compatible, benchmarkable
     │  cluster
T0  4 subsystems + isolated  SE/CO, S, NE, N — NEWAVE-comparable, hydro policy dev
```

Every tier is produced by the same Snakemake workflow from the same raw inputs. Reduction uses PyPSA's `simplify_network` / `cluster_network` pattern (k-means or spectral on the busmap), preserving subsystem boundaries as hard clustering constraints — the SE/CO–NE–N–S structure must survive aggregation or your interchange validation becomes meaningless.

### Stack (all open unless noted)

| Layer | Choice |
|---|---|
| Orchestration | Snakemake (PyPSA-Eur/Earth convention) |
| Core | `pypsa`, `linopy` |
| Weather → CF | `atlite` + ERA5 (CDS API) |
| Geo | `geopandas`, `shapely`, `rasterio`, `earth-osm` |
| Brazilian decks | `inewave`, `idecomp`, `idessem` (rjmalves) — mature, pandas-native |
| Distribution | `OpenDSSDirect.py` / `dss-python`, `bdgd2opendss` |
| Stochastic hydro | **`SDDP.jl`** (odow) — mature, CVaR/risk measures, Markovian policy graphs. Possibly `HydroPowerModels.jl` as reference. |
| LP/MILP solver | HiGHS (open) for T0–T2; **Gurobi/COPT academic licence realistically required** for T3 with UC |
| Data versioning | Snakemake + pinned Zenodo/DOI inputs; DVC if raw data grows past a few hundred GB |

**Solver reality check:** full nodal Brazil, 8760 h, with unit commitment is a large MILP. HiGHS will not carry it. Budget for an academic Gurobi licence and/or time-slicing (representative days/rolling horizon) at T3.

**Julia↔Python bridge:** don't try to run SDDP inside Python. Run it as a separate Snakemake stage; exchange inflow scenarios and Benders cuts via Parquet/JSON. Loose coupling, easy to debug, no `juliacall` fragility.

---

## 6. The stochastic hydro layer — concrete design

This is the intellectually hardest piece and where the project either becomes distinctive or becomes another PyPSA country model. The design that works:

**Do not** try to make PyPSA itself stochastic-multistage. **Decouple the policy from the dispatch**, exactly as the official NEWAVE→DECOMP→DESSEM chain does — but do it open.

**Stage A — inflow model.** Fit a **PAR(p)** model on log-transformed monthly natural inflows from `VAZOES.DAT` (1931–present, per plant), the Brazilian standard, with spatial correlation across basins preserved via correlated residuals. Alternatives worth testing: Gaussian VAR, copula-based, or hidden-Markov regime models conditioned on ENSO. Validate synthetic series against historical ENA statistics.

**Stage B — policy.** Run SDDP.jl on a reduced hydro-thermal model:
- Start at **T0 (4 subsystems, REE-style equivalent reservoirs)** to get the machinery working and comparable to NEWAVE's classic formulation.
- Then move to **individualized reservoirs** (order 100–170 plants). SDDP.jl handles this; expect hours-to-days convergence, not minutes. This is precisely why CEPEL historically used REEs.
- Use **CVaR** risk aversion (λ, α) to match the Brazilian regulatory formulation.
- Output: **Benders cuts / future cost function** at each monthly stage boundary.

**Stage C — coupling into PyPSA.** This is the mechanically interesting part and it is clean in `linopy`:

```
m = n.optimize.create_model()
# add scalar cost-to-go variable α
# for each cut k from SDDP:
#   α ≥ a_k + Σ_i π_ik · (SoC_i − SoC_i^ref)
# add α to the objective
```

The PyPSA operational model then optimizes the *nodal network* against a terminal water-value function that came from a *stochastic* upstream model. That combination — full nodal network + stochastic water values — is something the official chain does not deliver in a single model, and it is a genuine contribution.

**Stage D — validation.** Backtest against published ONS *CMO Semi-Horário* / *CMO Semanal* and CCEE PLD, and against observed EAR trajectories per subsystem. Target: aggregate metrics within a few percent, correct seasonal shape. Do this before claiming anything.

**Cheaper interim option:** PyPSA rolling-horizon with heuristic water values. Literature puts the gap between rolling-horizon and optimal stochastic policy at ~0.7% for small storage systems up to ~8.5% for large ones — and Brazil is emphatically a *large* storage system, which is exactly why SDDP is worth the effort here. Use rolling-horizon as the Phase-2 placeholder, not the destination.

---

## 7. Distribution & DG — scope it tightly

Full national OpenDSS is not a project, it's a career. BDGD covers every distributor with tens of thousands of feeders. The defensible design is two-track:

**Track 1 (do this first, high value, low cost).** Aggregate MMGD to PyPSA nodes. The ANEEL MMGD registry gives you installed power, source, and municipality per connection; simulate PV profiles per municipality with `atlite`; inject as negative load or must-run generator at the mapped node. Validate against the MMGD component already broken out in ONS *Carga Verificada* — you have ground truth for this, which is rare.

**Track 2 (later, targeted).** Pick a handful of **representative feeders** per region/distributor archetype, convert BDGD→OpenDSS with `bdgd2opendss`, and run them offline to derive net-load shape corrections, hosting-capacity limits, and reactive/loss factors. Feed those *parameters* back into the PyPSA node. No live co-simulation.

**Only if a specific research question demands it:** true co-simulation via HELICS. Treat as a separate project with its own justification.

---

## 8. Staged roadmap

| Phase | Duration | Deliverable | Gate |
|---|---|---|---|
| **0. Foundations** | 2–3 wks | Repo, Snakemake skeleton, data-fetch layer for ONS/ANEEL/EPE APIs with caching, licence audit | All raw fetchers reproducible from scratch |
| **1. T0 zonal model** | 3–4 wks | 4-subsystem + isolated PyPSA model, hourly, 2024–2025 | Reproduces ONS energy balance & interchange within ~5% |
| **2. T1 27-node model** | 4–6 wks | State-level model, DLR-refreshed to 2026 | Reproduces DLR published results; then diverges only where inputs were updated |
| **3. Hydro physical model** | 4–6 wks | `hidr.dat` ingestion, individualized reservoirs, cascade topology, real head-dependent productivity | Simulated generation matches ONS hourly per-plant hydro output |
| **4. Weather & VRE calibration** | 4 wks | atlite pipeline + quantile-mapping bias correction against per-plant ONS output | Per-plant CF error materially below uncorrected ERA5 baseline |
| **5. T3 nodal network** ⚠️ | 8–12 wks | ≥230 kV nodal model, real impedances, DC-OPF, unit-level generators | Reproduces observed congestion patterns & constrained-off events |
| **6. Clustering framework** | 3 wks | T3→T2→T1→T0 automated reduction, subsystem-preserving | Clustered results track nodal within agreed tolerance |
| **7. Stochastic hydro** | 12–16 wks | PAR(p) + SDDP.jl policy + linopy cut coupling | Backtest vs. ONS CMO / CCEE PLD and EAR trajectories |
| **8. DG / MMGD** | 4 wks | MMGD aggregation per node | Matches MMGD component of ONS *Carga Verificada* |
| **9. OpenDSS track** | open-ended | Representative feeder studies → node parameters | Question-driven |

⚠️ **Phase 5 is the critical-path risk.** It hinges on the DESSEM deck route (§2.1). Resolve that in Phase 0 — a week of investigation there determines whether Phase 5 is 8 weeks or 20.

**Suggested first three moves:** Phase 0 → Phase 1 → Phase 3. Getting the hydro *physics* right early matters more than getting the network wide, because every downstream tier depends on hydro, and hydro is where Brazil differs most from the European models PyPSA was built around.

---

## 9. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| DESSEM decks not publicly accessible / terms restrict reuse | **High** | Investigate in week 1. Fallback: typical-parameter synthesis per voltage class → DC-OPF only, no AC |
| OSM ODbL contaminates your derived network DB | Medium | Decide early. If you want permissive licensing, build from ONS/ANEEL/EPE only and use OSM for visualisation only |
| Nodal MILP intractable on open solvers | Medium | Academic Gurobi/COPT; representative days; rolling horizon; drop UC at T3 |
| SDDP convergence on 170 individualized reservoirs | Medium | Stage it: REE first, individualize incrementally; cut selection & parallelism in SDDP.jl |
| Bus-level load allocation is unfalsifiable | Medium | Publish the allocation method as an explicit, swappable module; sensitivity-test it |
| Data schema drift on ONS/ANEEL portals | Low | Schema validation (`pandera`) in the fetch layer; fail loudly |
| Scope creep into sector coupling / H2 | Medium | Explicitly out of scope for v1. PyPSA-Earth sector-coupled already covers Brazil for H2 if needed later |

---

## 10. Positioning against existing work

- **PyPSA-Earth** — global, OSM-derived, automated. Gives you Brazil cheaply but with OSM-quality topology and no Brazilian hydro physics. Its `earth-osm` → `base_network` → `simplify_network` → `cluster_network` pattern is the right *architecture* to copy. Recent plant-validation work reportedly cut Brazil's data error from 80.2% to 2.7%.
- **PyPSA-Brazil (DLR)** — 27 nodes, well documented, peer-reviewed, honest about limitations, but state-level and 2012–2020.
- **Official chain (NEWAVE/DECOMP/DESSEM)** — authoritative hydro stochastics, closed source, subscription-licensed, and network-light at the long-term end.

**The gap nobody fills:** a nodal, unit-level, open Brazilian model with *real* hydro physics and *stochastic* water values, reducible to any resolution. That's the project. It's defensible, it's publishable, and every input it needs is either open or obtainable.

---

## 11. Immediate next steps

1. **Resolve the DESSEM/ANAREDE deck question.** Download a current deck, open it with `idessem`, confirm `desselet.dat` + ANAREDE base cases are present and check the reuse terms. This is the single decision that shapes the roadmap.
2. **Licence audit.** Per-dataset terms for ONS, ANEEL, EPE; decide the OSM/ODbL question now, not after you've built on it.
3. **Pull one NEWAVE deck** and confirm `hidr.dat` + `VAZOES.DAT` parse cleanly with `inewave`.
4. **Stand up the repo and Snakemake skeleton** with the ONS/ANEEL fetch layer and schema validation.
5. **Clone the DLR dataset**, reproduce their 27-node model in current PyPSA, and use it as the regression benchmark.

---

### Sources

[ONS Dados Abertos](https://dados.ons.org.br/) ·
[ONS — Linhas de Transmissão da Rede de Operação](https://dados.ons.org.br/dataset/linha-transmissao) ·
[ANEEL Dados Abertos](https://dadosabertos.aneel.gov.br/) ·
[ANEEL SIGET](https://dadosabertos.aneel.gov.br/dataset/sistema-de-gestao-da-transmissao-siget) ·
[ANEEL SIGA](https://dadosabertos.aneel.gov.br/dataset/siga-sistema-de-informacoes-de-geracao-da-aneel) ·
[ANEEL BDGD](https://dadosabertos.aneel.gov.br/dataset/base-de-dados-geografica-da-distribuidora-bdgd) ·
[ANEEL MMGD](https://dadosabertos.aneel.gov.br/dataset/relacao-de-empreendimentos-de-geracao-distribuida) ·
[EPE Webmap](https://gisepeprd2.epe.gov.br/WebMapEPE/) ·
[EPE Webmap ArcGIS REST](https://gisepeprd2.epe.gov.br/arcgis/rest/services/SMA/WMS_Webmap_EPE/MapServer) ·
[EPE — bases de dados de transmissão](https://www.epe.gov.br/pt/leiloes-de-energia/leiloes-de-transmissao/bases-de-dados) ·
[ONS PAR/PEL 2025](https://www.ons.org.br/Paginas/energia-no-futuro/suprimento-eletrico/parpel2025/sumario-executivo/index.aspx) ·
[DLR Open Brazilian Energy Data](https://gitlab.com/dlr-ve/esy/open-brazil-energy-data/open-brazilian-energy-data) ·
[Deng et al., *Scientific Data* (2023)](https://www.nature.com/articles/s41597-023-01992-9) ·
[PyPSA-Earth docs](https://pypsa-earth.readthedocs.io/) ·
[PyPSA models index](https://docs.pypsa.org/latest/home/models/) ·
[PyPSA rolling-horizon](https://docs.pypsa.org/latest/examples/rolling-horizon/) ·
[SDDP.jl](https://github.com/odow/SDDP.jl) ·
[inewave](https://github.com/rjmalves/inewave) · [idecomp](https://github.com/rjmalves/idecomp) · [idessem](https://rjmalves.github.io/idessem/) ·
[bdgd-tools](https://github.com/eniocc/bdgd-tools) · [bdgd2dss](https://github.com/ArthurGS97/bdgd2dss) ·
[CEPEL DESSEM manual v21](https://www.cepel.br/wp-content/uploads/2025/05/DESSEM_ManualUsuario_v21.pdf) ·
[ONS — comunicado publicação decks DESSEM](https://www.ons.org.br/Paginas/Noticias/20221107-Comunicado-sobre-a-publica%C3%A7%C3%A3o-dos-decksresultados-do-DESSEM-.aspx) ·
[OSM Power networks/Brazil](https://wiki.openstreetmap.org/wiki/Power_networks/Brazil) ·
[MapYourGrid — global grid data](https://mapyourgrid.org/global-grid-data/)
