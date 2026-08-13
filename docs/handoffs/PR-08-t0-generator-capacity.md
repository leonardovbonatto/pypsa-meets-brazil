<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-08 — T0 generator capacity

**Landed**

- `scripts/_ons.py` — `SUBSYSTEM_MAP`, `EXCLUDED_SUBSYSTEM_CODES` (`{"PY"}`),
  and `map_subsystems()`, factored out of `build_demand.py` since
  `build_generators.py` needs the identical ONS-code mapping.
  `build_demand.py` re-exports `map_subsystems`/`SUBSYSTEM_MAP` so its
  existing tests and call sites didn't need to change.
- `scripts/build_generators.py` — `filter_active()` (drops decommissioned
  units), `map_technology()` (the 5 `nom_tipousina` categories →
  hydro/wind/solar/thermal/nuclear, raises on anything else), and
  `build_generator_capacity()`, which pipes filter → subsystem-map →
  technology-map → groups by `(subsystem, carrier)` and sums MW.
- `scripts/build_network.py::attach_generators()` — one `Generator` per
  `(subsystem, technology)` row, `p_nom` only. Registers each carrier before
  any generator references it (the PR-06 lesson, applied on the first try
  this time — no warning appeared on the real rebuild).
- `rules/build.smk::build_generators_t0`, and `build_network_t0` now takes
  a second input, `resources/generators_t0.csv`.
- 20 new tests (99 total).

**Key files:** `scripts/build_generators.py`, `scripts/_ons.py`,
`scripts/build_network.py`.

**Verified against reality, not just asserted:**

Ran `snakemake build_all` from a clean slate for the built artifacts
(`resources/generators_t0.csv` and `resources/networks/t0.nc` both deleted
first). Every one of the 15 `(subsystem, technology)` capacity figures in
the output matched, to the row, the pivot table computed independently
during PR-07's exploration — same numbers, arrived at through the actual
pipeline this time rather than an ad hoc script. National total 192.0 GW
(`PY`'s 7.0 GW correctly absent, 199.0 total − 7.0 = 192.0). Hydro alone
102.68 GW. Re-ran `build_network_t0` a second time and grepped the log for
"carrier"/"WARNING" — none appeared, confirming the PR-06 carrier-registration
gotcha didn't recur.

**Gotchas**

1. **None new this session** — genuinely. The PR-06 carrier lesson
  transferred directly: `attach_generators()` registers every carrier before
  any generator references it, and the real rebuild produced no warning on
  the first attempt. Worth noting as a case where a documented gotcha from
  an earlier handoff actually did its job.

**Dead ends**

None. The design (aggregate by `nom_tipousina`, exclude `PY` by name, reuse
the existing `SUBSYSTEM_MAP`) was set in PR-07's handoff and held up exactly
as planned — no rework needed once implementation started.

**Next PR needs**

- **Marginal cost.** `n.optimize()` is still not callable: generators have
  no `marginal_cost`, so dispatch would be arbitrary among free generators.
  ONS's `cvu-usitermica` dataset (thermal variable cost) is the natural next
  connector, following the exact fetch → dictionary → build shape from
  PR-04/05 and PR-07/08. Hydro's marginal cost (the water value) is a much
  larger undertaking — PRIMER §4 — and explicitly out of scope until the
  SDDP.jl work lands; a T0 pass that can at least dispatch thermal-vs-hydro
  on CVU alone (treating hydro as free/must-run, an explicit documented
  simplification) may be the pragmatic interim step before a solver PR.
- **Availability profiles.** `p_max_pu` defaults to 1 for every generator
  right now — every wind/solar/hydro MW is assumed available every hour,
  which is wrong and will produce nonsense once a solver is attached. Needs
  atlite/ERA5, still fully `PLANNED`.
- Once marginal cost exists (even just CVU for thermal), a solver PR
  (`highs`, already named in `config.default.yaml` but unused) becomes
  possible, and `n.optimize()` is callable for the first time — at which
  point validating dispatch against observed ONS CMO (PRIMER §2.6) becomes
  possible too.
- `docs/STACK.md`'s PyPSA entry should be updated again once generators
  exist there — not done in this PR, since STACK.md wasn't touched (no new
  tool, no new gotcha for the tooling guide specifically; this PR's findings
  are domain/pipeline, which belong in this handoff and the data dictionary,
  not the stack guide).

**Open questions**

- Still open from PR-06: isolated systems (Roraima) — not part of this
  network's four buses, undecided when/whether to add.
- Whether `p_nom_mw` aggregation should eventually preserve per-plant
  identity (rather than collapsing straight to subsystem×technology) for
  when T1/T2/T3 nodal tiers need it. Deferred: T0 is explicitly the
  4-subsystem zonal tier, and PRIMER's roadmap has T1+ deriving from a
  nodal T3 model built independently, not from upsampling T0 — so this
  aggregation is T0-specific and not expected to need to un-aggregate later.
