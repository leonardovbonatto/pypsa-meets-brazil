<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-06 — Bare T0 network

**Landed**

- `pypsa` added to `pixi.toml` — first domain modelling dependency. Resolved
  to 1.2.4; pulled in `linopy`, `xarray`, `netCDF4`, `scipy`, `networkx` as
  transitive deps, all confirmed importable before writing any code against
  them.
- `scripts/build_network.py` — `wide_demand()` pivots the tidy PR-05 series
  to one column per subsystem (what `n.add("Load", ...)` wants) and checks
  for gaps after pivoting; `build_network()` builds a bare `pypsa.Network`:
  snapshots from the demand series' index, one `Bus` per subsystem, one
  time-varying `Load` per bus. No generators, no lines, no solver.
- `rules/build.smk::build_network_t0` — depends on `resources/demand_t0.csv`,
  outputs `resources/networks/t0.nc`. Chains automatically off
  `build_demand_t0` off `fetch_ons_curva_carga`; no explicit wiring needed
  beyond matching filenames, confirmed by deleting all three artifacts and
  running `snakemake resources/networks/t0.nc` from scratch.
- 9 new tests (72 total), plus `docs/STACK.md` updated in place — its
  PyPSA entry moves from PLANNED to BUILT (bare), and both pipeline diagrams
  now show the demand → network step.

**Key files:** `scripts/build_network.py`, `rules/build.smk`.

**Verified against reality, not just asserted:**

Built the real T0 network from the real fetched data (not just the test
fixture): 4 buses, 8784 snapshots, `loads_t.p_set` with no NaNs, mean SIN
load 78,943 MW and 693.4 TWh/yr — the same numbers hand-verified in PR-04 and
reproduced again in PR-05, now a third time through an entirely different
code path (PyPSA's own data structures rather than pandas). Also ran
`n.consistency_check()` on the real network and round-tripped it through
`export_to_netcdf()` / reloading, confirming `loads_t.p_set` survives
byte-for-byte.

**Gotchas**

1. **`n.add("Bus", ..., carrier="AC")` does not register the carrier.** It
   only *references* one by name. `n.consistency_check()` catches this as a
   `WARNING` in the log, not an exception — so a network can look validated
   and still ship with an undefined carrier (missing colour, name, growth
   limits — nothing that breaks today, but a real gap the moment anything
   downstream keys off carrier attributes). Fixed by adding
   `n.add("Carrier", "AC")` before any bus references it. Caught by reading
   the actual Snakemake log output, not by any check passing or failing —
   worth remembering as a category of bug this project's own `n.consistency_check()`
   discipline does not fully cover on its own.
2. **A `RuntimeWarning: numpy.ndarray size changed, may indicate binary
   incompatibility`** appears once, from `netCDF4`, on first import in the
   test process. This is a known compiled-extension ABI-metadata mismatch
   between conda-forge packages, not a bug in this repository's code. Did
   not chase it — it does not affect any test outcome or the correctness of
   the exported file (round-trip test passes exactly). Flagging here so
   nobody spends an hour on it later.
3. **`pypsa`'s dependency solve was clean** — no channel gymnastics like
   PR-02's `snakemake-minimal`/bioconda issue. Worth calling out only because
   it was *not* a gotcha; don't assume every new conda-forge domain package
   will be this easy.

**Dead ends**

None this session — the API worked as documented on the first real attempt
against real data (see the exploratory script in the session; not committed,
since `test/test_build_network.py` covers the same ground properly).

**Next PR needs**

- The obvious next step per the roadmap is generators: fetch ONS plant
  registry / CVU / installed capacity, then attach `Generator` components to
  the T0 buses. That is a materially bigger PR than this one — plant-to-bus
  allocation for a 4-subsystem model is a real modelling decision (which
  plants belong to which subsystem is at least given directly by ONS's own
  registries, unlike the eventual T1+ bus-allocation problem flagged in the
  roadmap as needing an ADR) — but the connector and generator-attachment
  logic alone are probably session-budget-sized on their own. Consider
  splitting fetch+dictionary from generator-attachment if it runs long.
- Once generators exist, a solver (`highs` via conda-forge, per
  `config.default.yaml`'s existing but currently aspirational setting) is
  the natural following PR, at which point `n.optimize()` becomes callable
  for the first time and dispatch — and therefore validation against
  observed ONS CMO — becomes possible.
- `resources/networks/t0.nc` is rebuilt from scratch every time (~1.2 MB,
  seconds to build). No incremental-update logic exists or is needed yet;
  revisit only if build time becomes a real cost once generators/lines land.

**Open questions**

- Whether `build_network_t0`'s bus set should eventually include the
  isolated systems (Roraima) mentioned throughout `docs/PRIMER.md`, or
  whether those stay a separate, later concern given they are not part of
  the SIN's `SE_CO`/`S`/`NE`/`N` structure. Not decided; the current network
  only has the four synchronous subsystems in `config.subsystems`.
