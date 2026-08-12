<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Technical Primer

**Purpose.** This project is built largely through agent-assisted sessions. That is a
productivity multiplier and a comprehension risk: it is entirely possible to end up
with a working model you cannot defend. This document exists so that does not happen.
It explains every layer — the physics, the economics, the mathematics, the software —
well enough that you can read any pull request in this repository and judge whether it
is right.

**How to read it.** §1–2 are power systems and Brazil. §3–4 are the optimization
mathematics. §5 is the software stack. §6 is engineering practice. §7 is how to keep
control over agent-authored work — read that one even if you skip everything else.
§8 is a glossary you can jump back to.

Nothing here assumes prior power systems knowledge. It does assume you can read code.

---

## 1. Power systems from first principles

### 1.1 The four objects

Almost every power system model, including this one, is built from four things:

- **Bus** (or node) — an electrical connection point. Physically a substation busbar.
  Everything else attaches to a bus.
- **Branch** — a line or transformer connecting two buses.
- **Generator** — injects power at a bus.
- **Load** — withdraws power at a bus.

The fundamental constraint is that **at every bus, in every instant, injections must
equal withdrawals**. Electricity is not stored in the wires. This is the *energy
balance constraint*, and it turns out to be where prices come from (§3.4).

### 1.2 Power does not follow contracts — it follows physics

This is the single most important idea for understanding why nodal modelling matters.

If a generator in the Northeast sells power to a consumer in the Southeast, the
electrons do not travel along a designated path. Power spreads across *every*
available path simultaneously, splitting in inverse proportion to electrical
impedance — Kirchhoff's laws. A transaction between two points changes flows on lines
that have nothing to do with either party. These are **loop flows**, and they are why
a network can be congested in ways that a simple "transfer capacity between region A
and region B" picture completely misses.

A model that represents the grid as regions connected by transfer limits is a
**transport model**. A model that represents actual buses and impedances and lets
flows distribute by physics is a **power flow model**. The former is much easier and
is what most zonal energy models (including the 27-node DLR model) do. The latter is
what T3 in this project is for, and it is why §2.6's impedance question is on the
critical path: **without impedances you cannot do power flow, only transport.**

### 1.3 AC, and why we linearize it

Real grids are alternating current. The exact power flow equations relate, at every
bus, the voltage *magnitude* and voltage *angle* to injected active power (MW) and
reactive power (MVAr). They are nonlinear and nonconvex — products and sines of
unknowns. Solving an optimization problem with them at national scale, for 8760 hours,
is not practical today.

So we use the **DC approximation** (nothing to do with direct current; the name is
historical). It assumes:

1. Voltage magnitudes are all ≈ 1 per-unit (flat).
2. Angle differences between connected buses are small, so `sin θ ≈ θ`.
3. Line resistance is negligible next to reactance (true at high voltage).
4. Reactive power is ignored.

What survives is beautifully simple. Flow on the line between buses *i* and *j* is:

```
        θᵢ − θⱼ
Pᵢⱼ  =  ───────
          xᵢⱼ
```

Linear in the unknowns. The whole optimization becomes a **linear program**, which
solvers handle at enormous scale.

**What you give up:** voltages, reactive power, and voltage stability entirely. Losses
are absent unless you add them back approximately. For dispatch, congestion and price
formation the approximation is good and universally used. For voltage collapse or
protection studies it is useless — that is what ANAREDE and dynamic simulators are
for, and it is out of scope here.

**Why `x` (reactance) is the number that matters:** it is the only network parameter
in that equation. This is the concrete reason the transmission impedance question
(ADR-0003, PR-07) determines what T3 can be.

### 1.4 Dispatch, commitment, and what makes it hard

**Economic dispatch:** given which plants are running, how much should each produce to
meet load at least cost? Continuous decisions → linear program → easy.

**Unit commitment:** which plants should be running at all? Now you have binary on/off
variables, minimum up and down times, start-up costs, minimum stable output. →
**mixed-integer** linear program → genuinely hard. Solve time can grow explosively
with the number of integer variables.

This distinction drives a lot of practical decisions in this repo. T0 and T1 can carry
unit commitment comfortably. Full nodal T3 with unit commitment over 8760 hours is
where open solvers stop coping and you need commercial ones or decomposition.

### 1.5 Merit order and marginal cost

Order generators by their **marginal cost** — the cost of producing one more MWh.
Dispatch cheapest first until load is met. The last (most expensive) unit needed is
the **marginal unit**, and its cost sets the system price.

Marginal cost is *not* total cost. Capital costs are sunk and do not affect dispatch.
For thermal plants it is essentially fuel plus variable O&M — in Brazil this is
published directly per plant as **CVU**, which is a considerable gift for calibration.

For hydro, marginal cost is where it gets interesting. Water is free. But using water
now means not having it later. Its true marginal cost is an **opportunity cost** — the
**water value** — and computing it is the entire purpose of §4.

### 1.6 Capacity factor

Actual energy produced ÷ energy if the plant ran at full rated power the whole time.
A 100 MW wind farm producing 350 GWh/year has a capacity factor of
350,000 / (100 × 8760) ≈ 40%.

It is the standard currency for renewable resource quality, and the thing this project
calibrates weather data against (§5.6) — because Brazil publishes observed per-plant
generation, which most countries do not.

### 1.7 Voltage levels

Higher voltage moves more power over longer distances with lower losses (losses scale
with current squared; for a given power, higher voltage means lower current).

In Brazil: **≥230 kV is the transmission boundary** (the *Rede Básica* — a regulatory
definition). Below that is distribution, regulated differently, operated by different
companies, and represented in a completely different dataset (BDGD, §2.8). This
project's T3 models ≥230 kV. That boundary is not arbitrary — it is where the data,
the institutions and the physics all change.

---

## 2. The Brazilian system

### 2.1 The SIN

The *Sistema Interligado Nacional* covers almost the entire country — one synchronous
machine spanning a continent. It is divided into four subsystems for operational and
market purposes:

| Subsystem | Code | Character |
|-----------|------|-----------|
| Southeast / Centre-West | SE/CO | Largest load, largest reservoirs |
| South | S | Hydro + strong wind, distinct rainfall regime |
| Northeast | NE | Wind and solar dominant, increasingly export-constrained |
| North | N | Big run-of-river hydro (Belo Monte, Tucuruí) |

Plus **isolated systems**, chiefly Roraima, not synchronously connected.

The four-subsystem split matters more than it looks: it is the resolution at which
Brazil's *prices* are formed, and it is why §5's clustering must preserve those
boundaries as hard constraints. Aggregating across a subsystem border destroys the
quantity you are trying to validate against.

**The rainfall complementarity** is the physical heart of the system: rainy seasons in
the South and the Southeast/North are offset in time, so the interconnection lets one
region's water cover the other's dry season. This is why the SIN exists, and why
inter-subsystem transfer limits are economically central.

### 2.2 Who does what

Confusing this map is a common source of wasted effort. Each institution publishes
different data with different meanings.

| Body | Role | What it publishes that you need |
|------|------|--------------------------------|
| **MME** | Ministry — policy | Policy direction |
| **ANEEL** | Regulator — concessions, tariffs, registries | SIGA (plants), SIGET (transmission topology), SIGEL (geospatial), BDGD (distribution networks), MMGD (distributed generation) |
| **ONS** | System operator — dispatch, real time | Hourly generation per plant, load, reservoir hydraulics, curtailment, CVU, outage rates, network registries |
| **EPE** | Planning company | PDE expansion plans, Webmap geospatial layers |
| **CCEE** | Market chamber — settlement | PLD prices, model decks |
| **CEPEL** | Research centre (Eletrobras) | Builds NEWAVE / DECOMP / DESSEM. Closed-source, now subscription-licensed |
| **PSR** | Private consultancy | Builds the commercial SDDP model — the thing this project is measured against |

**Rede Básica vs Rede de Operação** — a distinction that catches people out. *Rede
Básica* is the regulatory perimeter (≥230 kV). *Rede de Operação* is what ONS actually
operates: Rede Básica **plus** a complementary network including some lower-voltage
assets that matter operationally. ONS datasets refer to the latter. They are not the
same set of lines.

### 2.3 Why hydro changes everything

Most of the world's power system models were designed around thermal systems, where
the binding question is "which plants run this hour". Brazil is hydro-dominated with
**multi-month storage**. The binding question becomes "how much water should we save
for later" — a fundamentally different, *intertemporal* and *uncertain* problem.

Three consequences that shape this entire repository:

1. **The economics are dominated by an opportunity cost that is not observable.**
   Water value has to be computed, not measured.
2. **Uncertainty is unavoidable.** Rainfall months ahead is unknowable; the decision
   cannot wait. Deterministic optimization with perfect foresight *cheats* — it knows
   the future and produces a benchmark no operator could achieve.
3. **The state of the system persists.** An emptied reservoir constrains next year.
   Models must carry storage state across long horizons.

This is why PyPSA alone is not enough here, and why §4 exists.

### 2.4 Hydro vocabulary

- **ENA** (*Energia Natural Afluente*) — inflow expressed as **energy**, not water
  volume: flow × productivity. The sector's natural unit.
- **EAR** (*Energia Armazenada*) — stored water expressed as energy. Usually quoted as
  a **percentage of maximum**, which is a classic units trap.
- **REE** (*Reservatório Equivalente de Energia*) — several reservoirs aggregated into
  one equivalent reservoir. A dimensionality-reduction device, used because
  individualized stochastic optimization over 150+ reservoirs is computationally brutal
  (§4.6).
- **Cascade** — reservoirs on the same river. Water released upstream becomes inflow
  downstream, after a travel time. They cannot be optimized independently.
- **Productivity** (*produtibilidade*) — MW per m³/s, which **depends on head**, which
  depends on how full the reservoir is. A full reservoir generates more per unit of
  water than an empty one. This makes the physics nonlinear (PR-19).
- **Run-of-river** vs **reservoir** — the former has negligible storage and must use
  water as it arrives; the latter can shift it across months.
- **Vertimento** (spill) — water released without generating. Pure economic loss.

### 2.5 The official model chain

Brazil solves the water-value problem with three chained models at different time
resolutions. Understanding this chain is essential, because **this project
deliberately replicates its structure in the open**:

```
NEWAVE     5 years, monthly, stochastic (SDDP), aggregated (REE)
   │  passes down a future cost function (FCF)
   ▼
DECOMP     2 months, weekly, individualized plants
   │  passes down a future cost function
   ▼
DESSEM     1–2 weeks, half-hourly, FULL NETWORK, unit-level
```

Each model hands the next a **cost-to-go function**: a summary saying "here is what
stored water will be worth to you at the end of your horizon". That single idea — a
long-horizon stochastic model teaching a short-horizon detailed model the value of
storage — is exactly what §4.5 rebuilds with SDDP.jl and PyPSA.

Note what the chain does *not* do: the stochastic model (NEWAVE) has almost no network,
and the network model (DESSEM) has almost no stochastics. **Combining full nodal
detail with stochastic water values in one model is the gap this project targets.**

### 2.6 Prices: CMO and PLD

**CMO** (*Custo Marginal de Operação*) is the cost of supplying one more MWh — the
shadow price of the energy balance constraint (§3.4). ONS publishes it per subsystem.

**PLD** (*Preço de Liquidação das Diferenças*) is the settlement price: CMO subject to
regulatory caps and floors.

These are the project's headline validation target. If a model reproduces observed CMO
in shape and level, its water values and merit order are approximately right. If it
does not, something upstream is wrong.

### 2.7 Curtailment (*constrained-off*)

When wind or solar is available but cannot be dispatched — because the network cannot
carry it or the system cannot absorb it — output is curtailed. ONS publishes this
**per plant**.

This is an unusually powerful validation asset. Curtailment is a direct fingerprint of
network congestion. A nodal model that reproduces *which* plants were curtailed *when*
has demonstrated its topology and limits are right, in a way that aggregate energy
balances never could. This is Gate C in the plan.

### 2.8 Distribution and MMGD

**MMGD** (*micro e minigeração distribuída*) — mostly rooftop and small solar behind
the meter. It has grown enormously and it does not appear as generation in operator
data; it appears as **reduced load**. ONS helpfully breaks out the MMGD component of
verified load, giving direct ground truth.

**BDGD** is ANEEL's georeferenced database of every distributor's network — the actual
MV/LV topology, nationwide, annually. It is enormous, and it is the input to OpenDSS
studies (§5.9). Full national simulation is not a project; representative feeders are.

---

## 3. Optimization: what the solver actually does

### 3.1 Linear programming

An LP has three parts:

- **Decision variables** — what we choose. Here: generator output per plant per hour,
  flow on each line, reservoir storage, spill.
- **Objective** — what we minimize. Here: total system cost.
- **Constraints** — what must hold. Energy balance at each bus, generator limits, line
  limits, reservoir dynamics.

Everything must be **linear** in the variables. Then the feasible region is a convex
polytope, the optimum sits at a vertex, and solvers find it reliably at scale —
millions of variables is routine.

**Mixed-integer** LP (MILP) adds variables restricted to integers, typically 0/1 for
on/off. This breaks convexity and the solver must search a tree of possibilities.
Hardness increases dramatically. Unit commitment is the reason we care.

### 3.2 What a model looks like here

Schematically, the core dispatch problem:

```
minimize     Σ    marginal_cost[g] · output[g,t]
           g,t

subject to
  (balance)  Σ output[g,t] − Σ load[l,t] + Σ flow_in[b,t] = 0     ∀ bus b, time t
  (gen)      0 ≤ output[g,t] ≤ capacity[g] · availability[g,t]     ∀ g, t
  (line)     −limit[ℓ] ≤ flow[ℓ,t] ≤ limit[ℓ]                      ∀ ℓ, t
  (physics)  flow[ℓ,t] = (θ[i,t] − θ[j,t]) / x[ℓ]                  ∀ ℓ, t
  (storage)  level[s,t] = level[s,t−1] + inflow[s,t] − release[s,t] − spill[s,t]
```

The last constraint is what links time periods and makes hydro interesting. Without
storage, each hour is an independent problem.

### 3.3 Duals — the most useful idea you may not know

Every constraint in an LP has an associated **dual variable** (shadow price): the
amount the objective would improve if that constraint were relaxed by one unit.

That is not an abstraction. It is the price.

### 3.4 Why the dual of energy balance is the electricity price

Take the energy balance at bus *b*, hour *t*. Its dual answers: *if load here were one
MWh higher, how much would total system cost rise?* That is precisely the marginal cost
of supplying that node — the **Locational Marginal Price**, and in Brazil's zonal
formulation, the **CMO**.

Consequences worth internalising:

- If no line is congested, prices are equal everywhere (minus losses). Congestion is
  what makes prices differ by location.
- A price spike means a binding constraint, and the dual tells you which.
- **You do not compute prices separately. You read them off the solved model.** In
  PyPSA they appear as `n.buses_t.marginal_price`.

When a PR claims to reproduce CMO, this is the mechanism. It is worth understanding
well enough to know when the claim is meaningful.

### 3.5 Multi-stage decisions under uncertainty

Now the hard part. A hydro operator decides how much water to release *this month* not
knowing next month's rainfall. Next month they will decide again, knowing more. This is
a **multistage stochastic** problem: decide, observe, decide again.

Three inadequate approaches, and why they fail:

- **Deterministic with perfect foresight.** Assume you know all future inflows. Gives a
  lower bound on cost that no real operator can achieve. Useful as a benchmark, invalid
  as a policy.
- **Deterministic with average inflows.** Systematically wrong, because the cost of
  being short is far higher than the saving from being long — the problem is asymmetric.
- **Rolling horizon.** Optimize a window, advance, re-optimize. Practical and honest
  about foresight, but needs a heuristic value for water left at the window's end,
  and that heuristic is doing all the real work. Literature puts the gap to an optimal
  stochastic policy at roughly 0.7% for small storage systems and up to ~8.5% for large
  ones. **Brazil is emphatically a large storage system** — which is exactly why the
  effort in §4 is justified here and would not be in, say, Denmark.

---

## 4. Stochastic optimization and SDDP

### 4.1 Bellman's idea

Define a **cost-to-go function** `V_t(x)`: the expected optimal cost of running the
system from time *t* onward, given state *x* (here, reservoir levels).

```
V_t(x) = min  [ immediate_cost(u)  +  E[ V_{t+1}( x' ) ] ]
          u
```

where `u` is this stage's decision and `x'` the resulting next state. Solve backwards
from the end and you have an optimal policy.

**The obstacle:** you cannot tabulate `V` over a 150-dimensional storage space. Ten grid
points per reservoir gives 10¹⁵⁰ states. This is the curse of dimensionality, and it is
why Brazil historically aggregated reservoirs into REEs.

### 4.2 The insight behind SDDP

For linear subproblems, **`V_t(x)` is convex** in the state. And any convex function is
the supremum of its tangent planes.

So: never tabulate `V`. **Approximate it from below by a maximum of linear functions** —
"cuts" — and add cuts where they matter. Each cut is one inequality:

```
α  ≥  a_k  +  Σ  π_k,i · ( x_i − x̄_k,i )
              i
```

with `π` the dual variables (§3.3) of the storage-balance constraints — the marginal
value of stored water at that trial point. **The water value is a shadow price.** That
is the whole conceptual bridge from §3.4 to hydro scheduling.

### 4.3 The algorithm

**Forward pass.** Sample an inflow scenario. Walk forward through stages, solving each
with the current cut approximation. Record the storage states visited. This is
simulation — it produces a *statistical upper bound* on cost.

**Backward pass.** Walk back through the visited states. At each, solve the next
stage's subproblem for every inflow realization, collect duals, average them into a new
cut, and add it. The approximation of `V` improves *where the policy actually goes* —
which is why it beats gridding the whole state space.

**Convergence.** The lower bound (from the cut model at stage 1) rises monotonically.
The upper bound (from simulation) is noisy. Stop when the gap is acceptably small.

**Why it works:** cuts are valid lower bounds everywhere, so the approximation never
overshoots, and the forward pass concentrates effort on relevant regions of the state
space.

### 4.4 Risk aversion and CVaR

Expected cost is not what the Brazilian sector minimizes. A 5% chance of rationing is
politically and economically unacceptable in a way that its expected-value contribution
does not capture.

**CVaR** (Conditional Value at Risk) at level α is the expected cost *in the worst α
fraction of outcomes*. The regulatory formulation uses a convex combination:

```
(1 − λ) · E[cost]  +  λ · CVaR_α[cost]
```

It remains convex, so SDDP still applies — SDDP.jl supports it natively. Using plain
expectation would produce a systematically less conservative policy than the real
system's, and CMO validation would fail in a specific, diagnosable way: your model would
be too willing to empty reservoirs.

### 4.5 How this couples to PyPSA

The chain:

```
VAZOES.DAT ──► PAR(p) inflow model ──► SDDP.jl ──► cuts (Parquet)
  (1931–)         (§4.7)               (Julia)          │
                                                        ▼
                                     PyPSA + linopy custom constraints
                                          minimize  …existing costs… + α
                                          s.t.  α ≥ cut_k   ∀ k
```

In PyPSA this is not exotic. You call `n.optimize.create_model()` to get the linopy
model, add a scalar variable `α`, add one constraint per cut linking `α` to the
storage variables, and add `α` to the objective. PyPSA then optimizes the **nodal
network** against a **stochastic** valuation of stored water.

Two languages, deliberately. They exchange Parquet files through Snakemake. No
in-process bridge, nothing fragile.

### 4.6 REE first, individualized second

Gate D in the plan exists for a reason. Get SDDP converging on the aggregated (REE)
formulation before attempting 150+ individualized reservoirs. If it does not converge
on the easy version, individualization will not rescue it, and you will have spent
weeks discovering that.

### 4.7 PAR(p): the inflow model

SDDP needs a **stochastic process** for inflows, not a historical record.

**PAR(p)** — Periodic AutoRegressive — is the Brazilian standard. "Periodic" because
monthly inflows are strongly seasonal, so autoregressive coefficients vary by month:
January depends on December differently than July depends on June. Fitted on
log-transformed flows (they are positive and skewed), on `VAZOES.DAT`'s ~95-year record.

Two things it must preserve or the whole exercise is compromised:

- **Persistence.** Dry periods cluster. If your synthetic series has droughts that are
  too short, the model will be far too optimistic about storage.
- **Spatial correlation.** Basins are correlated. Independent per-basin sampling
  produces implausible scenarios where half the country is dry and half is flooding,
  which understates true system risk.

Validate synthetic series against historical ENA statistics — mean, variance,
autocorrelation, drought duration distribution, cross-basin correlation — before it
feeds anything.

---

## 5. The tech stack

### 5.1 PyPSA

The core framework. A `Network` object holds:

- **Components** — `Bus`, `Line`, `Link`, `Transformer`, `Generator`, `Load`,
  `StorageUnit`, `Store`. Static attributes live in DataFrames (`n.generators`).
- **Snapshots** — the time index (`n.snapshots`), typically hourly.
- **Time-varying data** — in `_t` structures (`n.generators_t.p_max_pu`,
  `n.loads_t.p_set`).
- **Results** — written back after solving (`n.generators_t.p`,
  `n.buses_t.marginal_price`).

Calling `n.optimize()` builds the LP/MILP from the components, hands it to a solver,
and writes results back. PyPSA's real value is that it encodes correct power system
formulations — DC power flow, storage dynamics, unit commitment — so you do not
re-derive them and get a sign wrong.

`StorageUnit` vs `Store`: a `StorageUnit` bundles storage with its own power
conversion (natural for a hydro plant with a reservoir); a `Store` is pure energy
storage needing a separate `Link`. Hydro cascades generally want `StorageUnit` plus
explicit `Link`s for water routing.

### 5.2 linopy

PyPSA's optimization layer. It builds the LP/MILP using xarray-style labelled arrays
and dispatches to a solver.

You care because **it is the seam for customization**. Anything PyPSA does not model
natively — SDDP cuts (§4.5), head-dependent hydro productivity (PR-19), bespoke
reservoir coupling — enters through linopy:

```python
m = n.optimize.create_model()
alpha = m.add_variables(name="cost_to_go", lower=0)
m.add_constraints(...)          # one per SDDP cut
m.objective += alpha
n.optimize.solve_model()
```

### 5.3 Snakemake

A workflow manager. You declare **rules** with inputs and outputs; it infers the
dependency DAG and runs what is needed.

```python
rule build_demand:
    input:  "resources/ons/carga_verificada.parquet"
    output: "resources/demand_{tier}.nc"
    script: "../scripts/build_demand.py"
```

Why not a plain script:

- **Incrementality.** Change the demand builder and only downstream steps rerun. On a
  pipeline where a full run means ERA5 cutouts and multi-hour solves, this is the
  difference between a usable project and an unusable one.
- **Parallelism.** Independent rules run concurrently, free.
- **Reproducibility.** The DAG *is* the documentation of how outputs were made.
- **Wildcards.** `{tier}` generates T0–T3 from one rule.

`snakemake -n` (dry run) shows what would run without running it — the cheapest
sanity check in the repo, and one CI performs on every PR.

**It does not properly support native Windows.** Hence WSL2.

### 5.4 pixi

Environment manager, lockfile-based, conda-forge underneath — PyPSA-Eur's current
convention. `pixi.toml` declares dependencies; `pixi.lock` pins exact resolved
versions including transitive ones. `pixi install` reproduces the environment
byte-identically on any machine.

This matters because the geospatial and numerical stack (GDAL, PROJ, HDF5, solvers) is
notoriously version-sensitive, and "it worked last month" is not reproducibility.

### 5.5 atlite

Converts weather reanalysis into power system time series.

A **cutout** is a subset of ERA5 (a global weather reanalysis — a physically consistent
reconstruction of past weather from a model constrained by observations) for your
region and period, cached locally. atlite then applies turbine power curves or PV
panel models to produce per-location capacity factor time series, and aggregates them
to model regions.

ERA5's resolution is roughly 30 km. That is coarse for wind, which varies sharply with
terrain — hence §5.6.

### 5.6 Bias correction (and why Brazil is lucky)

Published validation finds ERA5-derived wind power biased **low by around 20%** and
ERA5-derived solar biased **high**. Uncorrected, your model builds the wrong system.

The literature also warns that correcting with the Global Wind Atlas can be
*detrimental*; quantile-mapping approaches perform better.

Brazil's advantage: **ONS publishes hourly generation per plant.** You can bias-correct
against observed output at the individual plant, rather than against a coarse
national aggregate. Most countries cannot do this. It is one of the strongest
differentiators available to this project — take it seriously (PR-23).

### 5.7 Geospatial, validation, and deck parsing

- **geopandas / shapely** — vector geometry: point-in-polygon, spatial joins,
  reprojection. Used to attach plants to buses, buses to states, feeders to nodes.
  Watch coordinate reference systems: Brazilian sources mix SIRGAS 2000 and WGS 84;
  mismatched CRS produces silently wrong joins, not errors.
- **pandera** — schemas for DataFrames. Declare expected columns, dtypes and ranges;
  fail loudly at the boundary. Combined with committed schema hashes, an upstream
  change becomes a red build instead of a wrong number.
- **`inewave` / `idecomp` / `idessem`** — parse CEPEL deck files into pandas. These
  are fixed-width Fortran-era formats; hand-parsing them is a well-known way to lose a
  week. `hidr.dat` (hydro plant physical cadastre) and `VAZOES.DAT` (the ~95-year
  inflow record) come through here.

### 5.8 Solvers

- **HiGHS** — open source, excellent for LP, adequate for modest MILP. Default here.
- **Gurobi / COPT** — commercial, dramatically faster on hard MILP; free academic
  licences. Realistically required for nodal unit commitment.

The solver is a config switch, not an architectural commitment. Keep it that way.

### 5.9 OpenDSS

A distribution system simulator: unbalanced three-phase power flow at feeder level,
individual transformers, single-phase laterals.

A genuinely different problem from transmission OPF. Distribution networks are radial
and unbalanced; the DC approximation (§1.3) does not hold, and you are *simulating* a
given state rather than *optimizing* dispatch.

Used here only in the targeted track: convert representative BDGD feeders, study them
offline, extract parameters (hosting capacity, net-load shape, loss factors) and feed
those into the PyPSA node. Nationwide co-simulation is out of scope.

### 5.10 Julia and SDDP.jl

Julia appears solely for SDDP.jl (§4), which is the mature, well-tested implementation
with risk measures and Markovian policy graphs built in. Reimplementing SDDP in Python
would be a large, bug-prone project with no upside.

Coupling is deliberately loose: Snakemake calls Julia as a separate stage; data crosses
as Parquet. No `juliacall`, no shared process, nothing to debug across a language
boundary.

---

## 6. Software engineering practice

### 6.1 Git, and why the conventions

**Commit** = a snapshot plus a message. **Branch** = an independent line of work.
**Pull request** = a proposal to merge, with review. **Merge** = integration.

This repo uses **squash-merge**: every PR collapses to exactly one commit on `main`.
Consequences:

- `git log --oneline` reads as a project narrative rather than a stream of
  "wip", "fix typo", "actually fix".
- Reverting a feature is reverting one commit.
- A future session can load the entire project history cheaply — which, on an
  agent-heavy project, is a real operational benefit rather than aesthetics.

**Conventional Commits** (`feat:`, `fix:`, `data:`…) make the history machine-readable,
so changelogs and version bumps can be derived rather than curated by hand.

### 6.2 CI

Automated checks on every push and PR:

- **lint** — formatting, style, licence headers, commit message format.
- **test** — pytest against committed fixtures.
- **smoke** — `snakemake -n` plus a tiny end-to-end run.
- **meta** — changelog entry present, provenance valid, ADR numbering unique.

**CI never downloads real data.** No credentials, no flakiness, no multi-GB pulls, no
dependence on a portal being up. Fixtures only.

### 6.3 Testing, in three layers

1. **Unit tests on fixtures** — a small, real-shaped sample committed to the repo.
   Fast, deterministic, catch parsing and transformation bugs.
2. **Smoke test** — the whole workflow on 72 hours of tiny data. Catches integration
   breakage; proves nothing about correctness.
3. **Validation against reality** — the model reproduces observed ONS series.

**Only the third tells you the model is right.** Layers 1 and 2 tell you the code runs.
This distinction is the single most important thing to hold onto when reviewing a PR
that says "all tests pass". So does a model that predicts negative demand.

### 6.4 Provenance and reproducibility

Every fetch writes a small JSON: source URL, retrieval timestamp, sha256, byte size,
row count, schema hash. Committed. Every solve writes a run manifest: config hash, git
SHA, solver version, input provenance hashes, objective, runtime.

Two payoffs. You can always answer *which vintage of ONS data produced this figure* —
non-negotiable for anything published. And because the schema hash is versioned,
**silent upstream schema drift becomes a visible git diff** rather than a number that
quietly changes meaning.

### 6.5 ADRs

Decisions get written down at the moment they are made, with the alternatives rejected
and the reasoning, and are immutable thereafter. Superseding writes a new record.

This project is full of choices that are assumptions rather than facts — bus-level load
allocation, impedance synthesis, bias-correction method, REE versus individualized
reservoirs. Every one will be questioned in review or in a paper. The reasoning is
worth far more written down at the time than reconstructed a year later.

---

## 7. Maintaining control over agent-authored work

This section is the reason the document exists.

### 7.1 The actual risk

The risk is not that an agent writes code that crashes — that is visible and cheap.
The risk is **plausible, confident, wrong**: a number with no source, a validation that
validates nothing, a unit conversion that is silently off by a factor of two, a claim
that a model "matches well" with no stated metric.

Everything below is designed to surface that specific failure mode.

### 7.2 Failure modes, and how each shows up

| Failure mode | What it looks like | How to catch it |
|---|---|---|
| **Fabricated numbers** | A capacity, a limit, a coefficient with no citation | Ask for the source. Demand a provenance record or a data-dictionary path. |
| **Self-validation** | "Model output matches expected values" — where "expected" came from the same model | Ask *what observed series* it was compared against, and demand the error figure. |
| **Silent unit errors** | Results off by ~2, ~3.6, or a clean factor | Check units explicitly. MW vs MWmed vs MWh, m³/s vs hm³/month, % of useful volume vs absolute. |
| **Scope narrowing** | Summary says "implemented X" but the diff covers a fraction | Read the diff, not the summary. Check the tests actually exercise the claimed behaviour. |
| **Hallucinated APIs** | Calls to functions that do not exist in that version | CI catches most. Be suspicious of unusually convenient methods. |
| **Pattern misapplication** | European modelling conventions applied to Brazilian hydro | Ask why this approach fits *this* system. §2.3 is your test. |
| **Confident uncertainty** | Firm claims about data availability or licence terms | Require a URL and a retrieval date. |
| **Overfitted validation** | Tuned until it matched, presented as validation | Ask what was held out. If nothing, it is calibration, not validation. |

### 7.3 The review checklist

For every PR, in this order:

1. **Read the diff, not the summary.** Summaries describe intent; diffs describe reality.
2. **Check the claim has a number.** "Matches well" is not a result. "MAE 3.2% against
   ONS verified load, Jan–Dec 2024" is.
3. **Check the comparison used observed data**, from a source that is not the model.
4. **Check units** at every boundary where data enters or leaves.
5. **Check provenance exists** for anything new.
6. **Check the data dictionary** was written and includes `unit` and `notes` — those
   two fields cause the most real bugs and cannot be auto-inferred.
7. **Check the handoff note** records gotchas and dead ends. An empty one usually means
   the session did not reflect.
8. **Check the session budget.** An over-budget PR was likely produced by a session
   running low on context — exactly when quality degrades.

### 7.4 Questions worth asking

These are chosen because they are hard to answer well without having actually done the
work:

- *"What did you compare this against, and what was the error?"*
- *"Which part of this are you least confident about?"* — a good answer names something
  specific; a bad one is reassurance.
- *"What would falsify this result?"*
- *"Show me the provenance record for that input."*
- *"What did you assume that isn't in the data?"* — this is the ADR question.
- *"If this number were wrong by a factor of two, what would break?"* — probes whether
  sanity checks exist.

### 7.5 The habit that matters most

**Reproduce one number yourself, by hand, per epic.**

Take one hour, one plant, one reservoir. Pull the raw ONS value. Compute what the model
should produce. Compare. It takes twenty minutes and it is the only check that cannot
be gamed by a plausible-sounding summary — including one written by me.

If you do nothing else from this section, do this.

### 7.6 What you should be able to explain unaided

A working comprehension test. By the end of each epic, you should be able to say, in
your own words:

- **Epic 1** — where the load data comes from, and what MWmed means.
- **Epic 3** — why reservoir productivity depends on head, and why that is nonlinear.
- **Epic 4** — why ERA5 wind is biased low, and what quantile mapping does about it.
- **Epic 5** — why impedance determines flow, and what a shadow price on a line means.
- **Epic 7** — what a Benders cut is, and why the dual of the storage constraint is the
  water value.

If any of these is fuzzy when the corresponding code is merging, stop and close the gap
before building on top of it. That is the whole point of maintaining control.

---

## 8. Glossary

**ANAREDE** — CEPEL power flow software; its case format carries network parameters.
**ANEEL** — Brazilian electricity regulator.
**BDGD** — georeferenced distribution network database, all distributors.
**Benders cut** — a linear lower bound on the cost-to-go function.
**Bus** — electrical node.
**Capacity factor** — actual ÷ maximum possible energy.
**CCEE** — market settlement chamber.
**CEPEL** — research centre; author of NEWAVE/DECOMP/DESSEM.
**CMO** — marginal operating cost; the shadow price of energy balance.
**Constrained-off** — curtailed renewable output.
**CVaR** — expected cost in the worst α fraction of outcomes.
**CVU** — published variable cost of a thermal plant.
**DC-OPF** — linearized optimal power flow.
**Deck** — a model's complete input file set.
**DESSEM** — half-hourly day-ahead model with full network.
**Dual / shadow price** — improvement in objective per unit relaxation of a constraint.
**EAR** — stored energy in reservoirs.
**ENA** — inflow expressed as energy.
**EPE** — energy planning company.
**ERA5** — global weather reanalysis.
**FCF** — future cost function; the cost-to-go passed between models.
**`hidr.dat`** — hydro plant physical cadastre.
**LMP** — locational marginal price.
**Merit order** — dispatch ordering by marginal cost.
**MMGD** — micro and mini distributed generation.
**NEWAVE** — long-term stochastic model using SDDP.
**ONS** — system operator.
**PAR(p)** — periodic autoregressive inflow model.
**PLD** — settlement price; capped/floored CMO.
**PSR** — consultancy behind the commercial SDDP model.
**Rede Básica** — regulatory transmission perimeter, ≥230 kV.
**Rede de Operação** — what ONS operates: Rede Básica plus complementary network.
**REE** — equivalent energy reservoir; aggregated reservoirs.
**Run-of-river** — hydro plant with negligible storage.
**SDDP** — Stochastic Dual Dynamic Programming.
**SIN** — the Brazilian interconnected system.
**Snapshot** — a time step in PyPSA.
**Unit commitment** — the binary on/off scheduling problem.
**`VAZOES.DAT`** — ~95-year natural inflow record per plant.
**Vertimento** — spill; water released without generating.
**Water value** — marginal opportunity cost of stored water.

---

## 9. Going deeper

**Power systems.** Kirschen & Strbac, *Fundamentals of Power System Economics* — the
best single book on why prices are duals. Wood, Wollenberg & Sheblé, *Power Generation,
Operation and Control* — the classic on dispatch and commitment.

**Stochastic optimization.** The SDDP.jl documentation is unusually good and doubles as
a tutorial on the method itself. Shapiro, Dentcheva & Ruszczyński, *Lectures on
Stochastic Programming* — the rigorous treatment.

**PyPSA.** The official docs and examples; PyPSA-Eur's source is the best worked
example of a large workflow.

**Brazil.** ONS publishes operating procedures and the PAR/PEL; CEPEL publishes model
manuals (the DESSEM manual is a detailed description of how the system is actually
dispatched); EPE's PDE explains the planning logic.

**This project.** [`Brazilian-Grid-in-PyPSA.md`](../Brazilian-Grid-in-PyPSA.md) is the
feasibility assessment and staged roadmap. `docs/decisions/` holds the reasoning behind
every consequential choice as it is made.
