<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-13 — T0 transfer links

**Landed**

- `scripts/build_links.py::build_link_capacity()` — maps `SE`→`SE_CO` on
  both `id_subsistema_origem` and `id_subsistema_destino` (reusing
  `_ons.map_subsystems()` twice), then groups by `(bus0, bus1)` and takes
  `max(abs(val_intercambiomwmed))` per real boundary — the ADR-0006 proxy.
- `scripts/build_network.py::attach_links()` — one bidirectional `Link`
  (`p_min_pu=-1`) per boundary, reusing the existing `"AC"` carrier, no
  losses (`efficiency=1.0`, PyPSA's default), no cost — only the `p_nom`
  limit binds.
- `rules/build.smk::build_links_t0`, and `build_network_t0` now takes a
  fourth input, `resources/links_t0.csv`.
- `docs/STACK.md` updated in place: PyPSA moves to "solvable, interconnected
  T0 network"; both pipeline diagrams move "+ lines" from PLANNED to BUILT.
- 21 new tests (151 total).

**Key files:** `scripts/build_links.py`, `build_network.attach_links()`.

**This resolves PR-11's infeasibility completely, and reveals a new,
equally real finding in the process.**

**Verified against reality, not just asserted:**

Ran `snakemake solve_all` from a clean slate. `resources/links_t0.csv`'s
four capacities (`N-NE` 6019.3, `N-SE_CO` 10492.0, `NE-SE_CO` 8310.8,
`SE_CO-S` 6902.4 MW) matched ADR-0006's own numbers exactly. The solve
succeeded, and:

- **`S`'s load-shedding is now exactly zero** (`load_shedding_mwh_by_bus:
  {}`) — the `SE_CO-S` link's 6902 MW capacity comfortably covers `S`'s
  202.6 MW shortfall from PR-11.
- **Links are genuinely, heavily used**, not idle: mean utilisation ranges
  65.5% (`N-NE`) to 95.9% (`NE-SE_CO`) of each link's capacity — confirmed
  by computing `n.links_t.p0.abs().mean() / n.links["p_nom"]` directly on
  the solved network, not assumed from the topology alone.
- **Thermal generation dispatches at exactly 0 MW, at every one of 8784
  hours, at every subsystem** — checked directly (`n.generators_t.p[thermal_names].max().max()
  == 0.0`), not inferred from the summary. `objective_rs` in the dispatch
  summary is exactly `0.0` as a direct consequence. National free capacity
  (hydro + wind + solar + nuclear, 159,702 MW) exceeds even 2024's single
  peak-demand hour (102,086 MW, 15 March 14:00) — checked that specific
  hour directly: free generation alone (58,490 + 9,866 + 31,740 + 1,990 =
  102,086 MW) exactly equals demand, thermal still at 0.

That last point is not a bug. It is the "no availability profile" gap from
every earlier handoff since PR-10, now manifesting as a concrete wrong
number instead of an abstract caveat: this model assumes every generator
can produce at full nameplate capacity every hour, so once subsystems can
trade freely, "free" (zero marginal cost) generation looks abundant enough
to cover all of Brazil's demand alone — which is not true of the real
grid, where wind, solar and run-of-river hydro have real, materially lower
capacity factors. `dispatch_summary_t0.json`'s existing
`known_limitations` entry already named this gap in the abstract (PR-11);
this PR is the first time it was actually confirmed to bite.

**Gotchas**

1. **None new.** The carrier-registration lesson (PR-06) and the
   load-shedding-as-diagnostic pattern (PR-11) both transferred cleanly:
   `attach_links()` reused the existing `"AC"` carrier without needing a new
   one, and no consistency-check warnings appeared on the real solve.

**Dead ends**

None. `map_subsystems()` was designed generically enough (PR-08, `column=`
parameter) that applying it twice — once per interchange-boundary endpoint
— worked on the first attempt with no rework.

**Next PR needs**

- **Availability profiles are now unambiguously the next real gap**, not
  just a documented one — this PR's own solve proves it produces a wrong
  number (zero thermal dispatch, ever) without them. Needs atlite/ERA5
  (still fully `PLANNED`) to derive real `p_max_pu` time series for
  wind/solar, and — per PRIMER §5.6 — Brazil's own per-plant hourly
  generation data (already fetched in spirit by `curva_carga`'s sibling
  datasets, though not yet this specific one) is the differentiator for
  bias-correcting ERA5 against real observed output, which most countries
  cannot do.
- Hydro availability is a related but distinct question: real hydro output
  depends on water availability (PRIMER §2.3/§4), not a weather-derived
  capacity factor — that is the much larger SDDP.jl/water-value undertaking,
  not something atlite alone resolves. Worth keeping these two conceptually
  separate when scoping the next PR: wind/solar availability (atlite,
  tractable now) vs. hydro's true operational constraint (water value,
  still a long way off).
- Once availability profiles exist for wind/solar and thermal is dispatched
  for genuine economic reasons again, `n.buses_t.marginal_price` becomes
  meaningful for the first time, and validating it against observed ONS CMO
  (PRIMER §2.6/§3.4) — the project's actual headline target — finally
  becomes possible.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether the `p_min_pu=-1` bidirectional-symmetric assumption on Links
  should eventually be split into directional import/export limits, since
  ADR-0006 already notes real transfer limits are sometimes asymmetric.
  Not needed yet — no evidence this matters until a solve actually binds
  against a link's capacity limit in a specific direction, which hasn't
  happened (utilisation is real but the network never actually hit 100% on
  any link in 2024).
