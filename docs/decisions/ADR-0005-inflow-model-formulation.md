<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0005 — Inflow model formulation (SDDP epic, stage 1)

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** —
- **Superseded by:** — (expected: a future ADR individualizing reservoirs,
  per PRIMER §4.6 - this ADR is explicitly the REE/subsystem-aggregated
  stage, not the destination)

## Context

ADR-0007 constrained T0 hydro with an observed-generation backcast and
named its own intended successor: real water values, computed by a
multistage stochastic model (PRIMER §4 - PAR(p) inflows → SDDP.jl →
Benders cuts → coupled into PyPSA via linopy). That is this epic. It is,
by the project's own roadmap (`Brazilian-Grid-in-PyPSA.md` Phase 7,
12-16 weeks) and PRIMER's own words, "the intellectually hardest part of
this project." Two prior sessions' worth of state summaries have named it
as the agreed next step (the user's step 2) without starting it - this
ADR is that start.

The reserved question, per `docs/decisions/README.md`'s index (this ADR
fills slot 0005): **what inflow data source and aggregation level does
the first working SDDP policy use?** Two real options exist, and they
trade off against each other in a way this project has faced before
(ADR-0007, PR-19's MMGD): the *correct, larger* answer vs. the *smaller,
real, immediately buildable* one.

**Option A - the official chain's own data.** `VAZOES.DAT` (NEWAVE decks,
via `inewave`): ~95-year monthly natural inflow series (1931-), per plant.
The Brazilian standard basis for PAR(p) fitting (PRIMER §4.7), and
required regardless for Phase 3's individualized-reservoir physical model
(`hidr.dat`, cascade topology, head-dependent productivity) later. Needs
Fortran fixed-width deck parsing - real engineering lift, and this
project's own roadmap flags deck-format work as its critical-path risk
(§5, Phase 5 warning) even though that specific warning is about DESSEM,
not NEWAVE.

**Option B - ONS's own open ENA data.** Checked directly this session,
not assumed: `dados.ons.org.br`'s CKAN catalogue has real, live,
CC-BY-licensed daily Energia Natural Afluente datasets - confirmed
`ena-diario-por-reservatorio` exists (62 resources, license CC-BY, real
metadata fetched live). A prior session's preliminary check (recorded in
the PR-19 handoff, not re-verified line-for-line today because the CKAN
search API rate-limited after the first successful call - a real gotcha,
noted below) found subsystem-level coverage 2000-2026 and REE-level
2016-2026. No deck parsing; no credential requirement, unlike Gurobi and
atlite/ERA5, both blocked this project for unrelated reasons (network
licensing, CDS credentials). The real cost: **27 years of REE/subsystem
data, not 95** - PRIMER §4.7 is explicit that drought persistence is one
of two properties a synthetic inflow series must preserve or "the whole
exercise is compromised," and a shorter record gives PAR(p) less signal
to fit that persistence from.

**A third, orthogonal question, also checked directly:** is Julia/SDDP.jl
itself actually installable here? `pixi search -c conda-forge julia`
returns `julia-1.12.7`, linux-64, no blocker of the Gurobi/atlite kind.
SDDP.jl itself is a Julia-registry package (`Pkg.add("SDDP")`), not
conda - untested in this repo. This is good news but not proof: nobody
has yet installed Julia here, added SDDP.jl, or run anything through it.

## Decision

**Start with Option B (ONS open ENA data), at REE or subsystem
aggregation** - matching PRIMER §4.6's explicit instruction ("Get SDDP
converging on the aggregated formulation before attempting 150+
individualized reservoirs... if it does not converge on the easy version,
individualization will not rescue it") and this project's own established
pattern (ADR-0007, PR-19): ship the smaller, real, immediately-available
version first, name the larger correct one as the explicit next step, and
never present the interim as more than it is.

Concretely, this ADR authorizes the epic to proceed in this order:

1. **A Julia/SDDP.jl environment feasibility PR, before any Brazilian
   data.** Install Julia via pixi, add SDDP.jl, and solve SDDP.jl's own
   textbook two-stage hydrothermal example end-to-end through the
   Snakemake → Parquet → (eventually) linopy coupling PRIMER §4.5/§5.10
   already specifies. This isolates "does the coupling mechanism work at
   all" from "is the Brazilian data model right" - two independent risks
   this project has learned (repeatedly, this session) not to debug at
   the same time.
2. **An ENA connector**, same shape as the six ONS connectors already
   built (fetch → real data dictionary from the full data volume, not a
   sample, per the PR-15 lesson → tidy table), at subsystem or REE level
   depending on what today's live check confirms once rate-limiting isn't
   in the way.
3. **PAR(p) fitted on that ENA series**, validated against the two
   properties PRIMER §4.7 requires (persistence, spatial correlation)
   before it feeds SDDP.jl at all - not assumed to be fine because the
   code ran.
4. **A first SDDP.jl policy** on the REE/subsystem-aggregated hydro-thermal
   problem, expectation-only (no CVaR) as the first target - CVaR is a
   real requirement (PRIMER §4.4) but adding it before a plain-expectation
   policy converges is compounding two unknowns again.
5. Only then, CVaR risk aversion, and only after that, individualized
   reservoirs (a future ADR, superseding this one).

## Alternatives considered

- **Option A first (NEWAVE deck route via `inewave`).** Rejected as the
  *first* step, not rejected outright - it is very likely still needed
  for Phase 3's individualized physical hydro model regardless, and
  nothing here forecloses it. Rejected as the entry point because it
  blocks the entire epic on Fortran deck parsing succeeding before SDDP.jl
  itself is ever exercised, repeating the exact mistake this project's own
  discipline exists to avoid: coupling an unproven engineering step to an
  unproven modelling step.
- **Rolling-horizon heuristic water values** (named as the roadmap's own
  "cheaper interim option"). Rejected: the roadmap's own text says the
  rolling-horizon-vs-optimal-stochastic-policy gap runs 0.7% for small
  storage systems up to 8.5% for large ones, and immediately adds "Brazil
  is emphatically a large storage system" - meaning this project would be
  choosing the approach documented as *worst-suited* to its own case.
  ADR-0007's backcast already serves as the "something better than
  nothing, cheaply" interim; a second, weaker interim on top of it adds
  complexity without a comparable payoff.
- **Full individualized reservoirs from the start.** Rejected per PRIMER
  §4.6, directly: 10 grid points per reservoir over 150+ reservoirs is
  10¹⁵⁰ states, the canonical curse-of-dimensionality example the same
  section opens with. Convergence risk on the hard version first, with no
  working easy version to fall back to or compare against, is not a risk
  worth taking when the cheap version is available.
- **Skip SDDP entirely, keep ADR-0007's backcast as the destination.**
  Rejected: this is precisely the risk ADR-0007 itself named ("the interim
  becomes the destination... deprivileged"). Both the user and this
  project's roadmap treat stochastic water values as the differentiator
  that makes this project worth building at all.

## Consequences

**Positive.** Unblocks the only path to a genuine answer to "does this
model predict prices," which the backcast (ADR-0007) explicitly cannot
give. Follows an already-validated project pattern (cheap-real-interim,
named larger destination) rather than inventing a new risk posture for
the hardest part of the project.

**Negative.** A 27-year inflow record materially understates
drought-persistence tail risk relative to `VAZOES.DAT`'s 95 years (PRIMER
§4.7) - any SDDP policy built on Option B data must carry that as an
explicit caveat, the same way ADR-0007's backcast caveat travels with
every dispatch summary. This is not a one-time caveat to write and
forget; `KNOWN_LIMITATIONS` must gain an entry for it once a policy exists
to caveat.

**Risk.** Three real unknowns, deliberately staged so they are debugged
one at a time rather than together: (1) whether SDDP.jl actually installs
and runs cleanly from this pixi/WSL2 environment - checked today only to
the level of "Julia itself is on conda-forge," not "SDDP.jl solves
anything here"; (2) whether ONS's ENA data, once actually fetched in full
(not just discovered via one successful CKAN call before rate-limiting),
has the date coverage and quality prior sessions' preliminary research
assumed; (3) whether a REE/subsystem-aggregated PAR(p) policy converges
at all before any individualization is attempted, per PRIMER §4.6's own
warning about what happens if it doesn't.

**A concrete gotcha for the next PR to know about:** `dados.ons.org.br`'s
CKAN *search/show API* returned a real, detailed result once this
session, then 403'd on every subsequent call (from both the WSL and
Windows-side network paths, ruling out a WSL-specific block) - looks like
aggressive or inconsistent rate-limiting, not a credential wall like
Gurobi/CDS. Not yet a confirmed blocker: every existing ONS connector in
this repo downloads resource files directly from
`ons-aws-prod-opendata.s3.amazonaws.com`, never the CKAN API - the
connector PR should target that S3 path directly (once the exact resource
URL is known) rather than depend on CKAN search working reliably.
