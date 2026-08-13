<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-11 — T0 solve

**Landed**

- `highspy` added to `pixi.toml` as an explicit dependency (it was already
  present transitively via `pypsa`/`linopy` — `pixi.lock` content is
  unchanged, only `pixi.toml`'s declaration is new). Gurobi deliberately
  **not** added: the user has an academic licence but it needs a persistent
  connection to the university network to activate from WSL2, which wasn't
  available. HiGHS was already `config.default.yaml`'s named default, so
  this PR just makes that setting real instead of aspirational.
- `build_network.py::attach_load_shedding()` — an always-available,
  deliberately expensive slack generator per bus (see Gotchas: it turned
  out to be load-bearing, not defensive).
- `scripts/solve_network.py` — `solve()` calls `n.optimize()` and raises if
  the status isn't `"ok"`; `summarize_dispatch()` computes mean dispatch by
  carrier and load-shedding per bus, and always embeds a `KNOWN_LIMITATIONS`
  list in the output so a summary can't be read without it.
- `rules/solve.smk::solve_network_t0` and a `solve_all` target (defined in
  `Snakefile` itself, after `RUN_ID`, same as `rule all` — needed because
  its outputs live under `results/{run}/`, unlike `build_all`'s static
  `resources/` paths). Kept outside `all`, same reasoning as `fetch_all`.
- `docs/STACK.md` updated in place: PyPSA moves to "solvable, no lines yet",
  linopy to "used indirectly", HiGHS to BUILT, Gurobi/COPT stay PLANNED with
  the WSL2/campus-network reason recorded. Both pipeline diagrams extended
  through the solve step.
- 11 new tests (130 total), including real (tiny, fast) HiGHS solves — not
  mocked — for a feasible network, merit-order correctness, and an
  infeasible network raising as designed.

**Key files:** `scripts/solve_network.py`, `build_network.attach_load_shedding()`.

**This is the first PR in the project where `n.optimize()` is called.** That
milestone matters less than what came with it: the first real solve attempt
against real 2024 data was **infeasible**, and understanding why turned into
this PR's actual content.

**Verified against reality, not just asserted:**

Before writing `solve_network.py`, ran `n.optimize()` directly against the
real (pre-load-shedding) `resources/networks/t0.nc` to see what would
happen, rather than assuming a clean solve. It returned `infeasible`.
Diagnosed by comparing each subsystem's total generator `p_nom` against its
own peak hourly demand: `S`'s capacity (21,409.9 MW) falls short of `S`'s
own peak load (21,612.5 MW) by 202.6 MW, in exactly 2 of 8784 hours, for
267.3 MWh of unmet demand across the whole year. `N`, `NE` and `SE_CO` all
have large headroom (17,500–41,500 MW). With no transmission lines, `S`
cannot import any of that spare capacity — the isolated single-bus problem
for `S` is genuinely infeasible at those 2 hours, and PyPSA solves all
snapshots jointly, so the whole network fails.

After adding `attach_load_shedding()` and rebuilding, the real solve
succeeded (`status="ok"`, `condition="optimal"`, objective ≈176.08M R$) and
`S`'s load-shedding dispatch was **267.34 MWh** — matching the
independently hand-computed shortfall almost to the decimal. This is the
cleanest confirmation in the project so far that a diagnostic mechanism
built from first principles produces exactly the number reality predicts.

The solve also surfaced the "stranded capacity" version of the same
no-lines gap, concretely rather than abstractly: `N`'s mean hydro dispatch
(7819.8 MW) lands almost exactly on `N`'s own mean load (7819.8 MW) at only
35% utilization of `N`'s 22,089.8 MW hydro capacity — the rest is real,
free, available capacity with nowhere to go, because `N` cannot export
without lines. `N`'s wind (426 MW, also free) isn't dispatched at all:
hydro alone already covers all of `N`'s demand.

**Gotchas**

1. **The load-shedding generator was not a defensive nice-to-have; it was
   required for the network to solve at all against real data.** Worth
   remembering for any future generator-set change (a new tier, a config
   with different capacity assumptions): re-check whether every subsystem's
   own capacity still covers its own peak demand before assuming a solve
   will succeed.
2. **`n.optimize()`'s `include_objective_constant` parameter currently
   defaults to `None`, which raises a `FutureWarning`** ("will change from
   True to False in version 2.0... improves LP numerical conditioning").
   Set it explicitly to `False` — adopts the recommended future behaviour
   now rather than carrying a warning that would silently flip behaviour on
   a future PyPSA upgrade.
3. **`pixi.lock` did not change** when `highspy` was added to `pixi.toml`,
   because it was already resolved transitively at the same version. Don't
   be alarmed by an "unchanged" lockfile after adding a dependency — check
   whether it was already present transitively before assuming something's
   wrong.

**Dead ends**

None. The infeasibility diagnosis (compare per-subsystem capacity to peak
load) was the first thing tried and was correct.

**Next PR needs**

- **Transmission lines.** This is now unambiguously the highest-value next
  step, not just a documented gap: it's the direct fix for both the `S`
  infeasibility (real transmission would let `S` import instead of shed
  load) and the `N`/`NE` stranded-capacity problem (real transmission would
  let them export). Needs `docs/decisions/ADR-0003` (transmission impedance
  source — already reserved for PR-07 in the ADR index, now overdue) before
  real `Line` components can be added with real `x` values; a first pass
  could use `Link`s with simple transfer-capacity limits between subsystems
  as an interim T0-appropriate simplification, explicitly documented as
  such, before real impedances land.
- **Availability profiles** (`p_max_pu` for wind/solar/hydro, via
  atlite/ERA5) — still the other half of the "clean solve ≠ correct
  dispatch" gap, unaddressed by this PR.
- Once lines exist, `n.buses_t.marginal_price` becomes meaningful for the
  first time, and validating it against observed ONS CMO (the project's
  actual headline target, PRIMER §2.6/§3.4) becomes possible.
- Gurobi remains available to swap in later (`config.solver.name: gurobi`)
  once campus-network access is available for licence activation — no code
  change needed, per `docs/STACK.md`'s "solver is a config switch" framing.

**Open questions**

- Still open from PR-06/08/10: isolated systems (Roraima).
- Whether `LOAD_SHED_COST = 10_000.0` R$/MWh should become a config value
  rather than a code constant, so a future sensitivity study can vary it.
  Not needed yet — no downstream analysis depends on its exact value today,
  only on it being clearly dominant over every real generator's cost.
