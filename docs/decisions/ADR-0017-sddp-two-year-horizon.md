<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0017 — A two-year SDDP horizon so year-end water has a value

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes:** — (lifts ADR-0014 decision 5's December end effect)
- **Superseded by:** —

## Context

The SDDP policy graph spans one year. Its last stage has no cuts, so water
left at the end of December is worth nothing, and the value of stored water
falls as the year runs out. The coupled 2024 run (ADR-0014) shows exactly
that: storage tracks observed EAR to May, then drains far faster (SE_CO 22%
in August against 56% observed) and prices sit at zero until an October
spike (PR-52). A CVaR policy with PR-43's fixed settings drains as fast, so
risk aversion is not the cause; the horizon is the remaining structural
suspect.

NEWAVE plans five years ahead plus a post-study period for the same reason.
SDDP.jl supports cyclic graphs, but a cyclic Markovian graph with 27 regimes
changes convergence behaviour; a longer linear horizon is the smaller step.

## Decision

1. **The regional policy graph spans `SDDP_HORIZON_YEARS = 2` years**: 24
   monthly stages, each mapped to its calendar month for demand, costs,
   renewables, floor and scenarios.
2. **Transitions come from 24-month PAR(1) simulations**, so December ->
   January follows the fitted persistence; training scenarios are still per
   calendar month, from the first simulated year.
3. **Scoring paths are unchanged** (the same 1000 one-year log-PAR(1)
   paths), so costs stay comparable with earlier designs.
4. **The coupled run uses the first year's cuts**, so December 2024 is valued
   against 2025. The second year's December keeps the end effect, now a year
   away from anything scored.

## Alternatives considered

- **Cyclic graph** (December links back to January with a discount). The
  standard infinite-horizon answer; deferred because it interacts with the
  Markov chain and the stopping rule.
- **A terminal value from historical storage.** Arbitrary and circular.

## Consequences

**Positive.** Late-year water has a value, which the backtest can test
directly.

**Negative.** Twice the nodes (648 regional) and slower training. In-sample
simulated cost now covers two years and is not comparable with earlier
in-sample figures; the scoring-path figures are.

**Risk.** If the backtest still fails on price, the horizon was not the main
cause, and storable inflow (gross ENA includes run-of-river energy) is next.

## Outcome (PR-55)

Built and run; **not adopted**. `SDDP_HORIZON_YEARS` stays at 1, and the
multi-year code stays, since one year reproduces the earlier results exactly.

| | one year (v2) | two years |
|---|---|---|
| storage, Pearson ≥ 0.6 in ≥ 3 | 4 of 4 | 2 of 4 (N 0.54, S 0.47) |
| SE_CO price rank (≥ 0.5) | 0.27 | −0.39 (zero every month) |
| SE_CO storage, Oct / Nov | 1% / 2% | 4% / 0% |
| cost on the 1000 PAR(1) paths | R$22.37bn | R$22.35bn |
| regime check | water value 0 everywhere | water value 0 everywhere |

The horizon was not the cause. With two years the water value at the
reference point is still zero in every subsystem, and the simulated training
cost was the same in every iteration (R$44,626m over two years): in SDDP's
world, water never limits the system, so the thermal floor sets every
scenario's cost. The next suspect is the energy SDDP thinks it has: gross
inflow, which counts run-of-river energy as storable.
