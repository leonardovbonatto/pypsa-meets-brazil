<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-10 — T0 marginal cost

**Landed**

- `scripts/build_costs.py` — `build_thermal_marginal_cost()` maps ONS
  subsystem codes (reusing `_ons.map_subsystems()`) and takes the
  unweighted mean of every `(plant, week)` CVU observation per subsystem,
  **including** real zero-cost plants. `INCLUDE_ZERO_COST_PLANTS = True` is
  a named, documented switch, not a buried default.
- `scripts/build_network.py::attach_marginal_costs()` — sets `marginal_cost`
  on every generator: the CVU-derived value for thermal, and an explicit
  `NON_THERMAL_MARGINAL_COST = 0.0` for hydro/wind/solar/nuclear, with the
  reasoning for each carrier written next to the constant rather than left
  for someone to reverse-engineer later.
- `rules/build.smk::build_costs_t0`, and `build_network_t0` now takes a
  third input, `resources/costs_t0.csv`.
- 15 new tests (119 total).

**Key files:** `scripts/build_costs.py`, `scripts/build_network.py`.

**The aggregation decision, stated plainly:** one mean CVU per subsystem,
computed across every plant and every week in the fetched year(s), zero-cost
plants included. Rejected alternatives and why:

- **Per-plant merit order** — impossible without a join, and PR-09 already
  established `cvu_usina_termica`'s plant identity doesn't match
  `capacidade_geracao`'s (different ID scheme, different name spelling).
- **Excluding zero-cost plants** — they're real (biomass/bagasse
  co-generation, sync-condenser-mode units per the data dictionary), not
  missing data. Excluding them would need a specific rationale ("these never
  set the marginal price") this project doesn't have evidence for.
  Consequence worth knowing: the `N` subsystem has an unusually high
  zero-cost share (32% of observations vs. 10–16% elsewhere - see the PR-09
  handoff), so its blended mean (237 R$/MWh) sits well below its
  nonzero-only mean (346 R$/MWh, computed during exploration) — a property
  of `N`'s declared thermal fleet, not a bug.
- **Capacity-weighting** — would need the same plant-level join that doesn't
  exist. Unweighted mean was the honest fallback, not a hidden simplification.

**Verified against reality, not just asserted:**

Ran `snakemake build_all` from a clean slate for the built artifacts.
`resources/costs_t0.csv`'s four values (N 237.04, NE 639.28, S 464.42,
SE_CO 549.14 R$/MWh) matched, to several decimal places, numbers computed
independently while exploring the aggregation choice before writing any
code. Inspected the final network object directly: every thermal generator
carries its subsystem's cost, every other generator carries exactly `0.0`,
`n.consistency_check()` raised nothing, and no carrier warning appeared on
a second rebuild (the PR-06 lesson holding for a third PR running now).

**Gotchas**

1. **A test fixture mismatch, not a code bug, caught mid-session.** An early
   version of `test_build_network.py`'s `tidy_costs` fixture referenced `"S
   thermal"`, but the paired `tidy_generators` fixture only has `S wind` (no
   `S thermal`) - `attach_marginal_costs()` correctly raised
   `"no matching generator"`, which was the right behavior surfacing a wrong
   test, not a wrong implementation. Fixed by making the fixtures agree.
   Worth remembering: when a new "raises correctly" test fails, check the
   fixture data before suspecting the code under test.

**Dead ends**

None. The aggregation approach was decided before writing code (see "The
aggregation decision" above) and held up exactly as planned through
implementation and the real-data run.

**Next PR needs**

- **A solver.** `n.optimize()` is now meaningful to call for the first
  time — every generator has capacity, a bus, and a marginal cost. HiGHS
  (`highs`, already named in `config.default.yaml`) is the natural first
  solver PR: add the dependency, call `n.optimize()`, and check it produces
  a sane dispatch (hydro and renewables running near p_nom since their cost
  is 0, thermal filling the residual, no infeasibility).
- Once a solve exists, validating `n.buses_t.marginal_price` against
  observed ONS CMO (PRIMER §2.6, §3.4) becomes possible for the first time —
  the project's actual headline validation target, four PRs' worth of
  plumbing away from PR-01.
- Still unaddressed: no lines (all four buses are electrically
  disconnected — a solve will run four independent single-bus problems, not
  a real interconnected dispatch, until lines exist), no availability
  profile (`p_max_pu` implicitly 1.0 for every generator via PyPSA's own
  default — wind/solar producing at full nameplate every hour is
  substantially wrong and will look fine numerically while being physically
  false; needs atlite/ERA5).
- A first solver PR should probably surface the no-lines limitation loudly
  (e.g. in the manifest, or a printed warning) rather than let a technically
  successful `n.optimize()` be mistaken for a real dispatch result — this is
  exactly the "plausible, confident, wrong" failure mode PRIMER §7.1 warns
  about, and the first time this project can actually produce that failure
  mode for real.

**Open questions**

- Still open from PR-06/08: isolated systems (Roraima).
- Whether `INCLUDE_ZERO_COST_PLANTS` should become a config option rather
  than a code constant, once someone wants to sensitivity-test the
  aggregation choice. Not needed yet - premature until a solve exists to
  compare against.
