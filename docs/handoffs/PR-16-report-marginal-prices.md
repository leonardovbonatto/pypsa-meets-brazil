<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-16 — Report marginal prices

**Landed**

- `scripts/solve_network.py::summarize_prices()` — mean `marginal_price`
  per bus (R$/MWh) plus an `all_prices_zero` flag, folded into the dispatch
  summary.
- A runtime warning when every price is zero, alongside the existing
  load-shedding warning.
- 3 new tests (182 total), including a textbook merit-order case asserting
  the price equals the *marginal* unit's cost (336.67 = mean of 10, 500,
  500), not the cheapest unit's.

**Key files:** `scripts/solve_network.py`.

**This PR is deliberately smaller than the one originally proposed, and the
reason matters.**

PR-15's verification noticed that `n.buses_t.marginal_price` was empty in
the saved `results/<run>/network_t0_solved.nc` — shape `(8784, 0)` — and
this was written up as a probable export bug that would silently drop the
project's headline output once prices became meaningful.

**That diagnosis was wrong, and checking it first is what caught it.**
Built a three-snapshot network with a deliberately binding expensive
generator so prices were genuinely nonzero (10, 500, 500 R$/MWh), exported
to netCDF, reloaded: prices survived **identically**. `generators_t.p`
survived too, as a control.

The real explanation is mundane: **PyPSA omits an all-default time series on
export**, and an all-zero `marginal_price` frame is all-default. Nothing is
broken, and nothing would have been lost once hydro is constrained and
prices become nonzero.

What *was* genuinely missing is smaller but real: the summary reported no
prices at all, so "every price is zero" — the signal that the model is
economically degenerate — required manually loading and inspecting the
solved network to notice. That is now a recorded field and a printed
warning.

**Verified against reality, not just asserted:**

- Round-trip test with nonzero prices (above) — the evidence that the
  originally-proposed fix was unnecessary.
- Re-solved the real 2024 network: the degenerate warning fires, and
  `dispatch_summary_t0.json` now records
  `"all_prices_zero": true` with `{"N": 0.0, "NE": 0.0, "S": 0.0,
  "SE_CO": 0.0}`.
- Also corrected a claim from the PR-15 write-up while verifying: hydro is
  **not** always spare-capacity-with-headroom. It hits its `p_nom` limit
  for 1,901–4,131 hours per subsystem (`S hydro` 4,131, `N hydro` 3,089,
  `SE_CO hydro` 2,396, `NE hydro` 1,901 of 8,784). Prices are still zero
  everywhere, but by a subtler route: when one subsystem's hydro binds, the
  marginal MWh comes from another subsystem's zero-cost generation across a
  transfer link, which still has headroom.

**Gotchas**

1. **An empty PyPSA `_t` frame after export does not imply data loss** — it
   may just mean every value equalled the component's default. Check by
   round-tripping a *non-default* case before concluding anything is
   broken. This cost one wrong diagnosis in the PR-15 write-up.
2. **`all_prices_zero` is deliberately tri-state** (`True`/`False`/`None`).
   `None` means no price frame exists at all — which is the legitimate
   state of a *reloaded* solved network whose prices were all zero. Reading
   that as `False` ("prices are not all zero") would be backwards.

**Dead ends**

The originally-scoped PR: fixing a netCDF export bug that does not exist.
Abandoned after the round-trip test, before any code was written.

**Next PR needs (PR-17: hydro observed-generation profile)**

Per the user's decision: use the cheap **option (b)** from the PR-15
handoff as a *ballpark reality check*, then do **option (a)** — real water
values via SDDP.jl — as the actual solution.

- Fetch ONS `geracao-usina-2` (hourly generation per plant) and build a
  hydro availability profile the same way `build_availability.py` already
  does for wind and solar. That constrains hydro and makes thermal
  dispatch, merit order and prices nonzero for the first time.
- **Label it unambiguously as backcasting**, in the code, the data
  dictionary, the handoff, and `KNOWN_LIMITATIONS`. It uses observed
  generation as a model *input*; validating the resulting prices against
  observed CMO would then be partly circular. It answers "is dispatch in
  the right ballpark?", not "does the model predict prices?".
- `all_prices_zero` should flip to `false` — that is the concrete pass/fail
  signal for whether PR-17 worked, and it is now recorded automatically.
- Compare the resulting per-carrier dispatch shares against ONS's own
  published 2024 generation mix. That is the actual ballpark test, and it
  is a fair one *because* the comparison target (annual mix) is coarser
  than the input (hourly per-plant profile).

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether `summarize_prices()` should eventually report the full hourly
  price series (or percentiles) rather than a mean, once prices are
  nonzero and CMO validation starts. A mean hides exactly the price spikes
  that matter (PRIMER §3.4: a spike means a binding constraint). Not needed
  while every price is 0.
