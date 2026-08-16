<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0007 — Hydro constrained by observed generation (interim backcast)

- **Status:** Accepted
- **Date:** 2026-08-14
- **Supersedes:** —
- **Superseded by:** — (expected: a future ADR introducing SDDP water values)

## Context

PR-15 established, by direct measurement rather than inference, that the T0
model is **economically degenerate**: national hydro nameplate capacity
(102,678 MW) exceeds national demand in all 8,784 hours of 2024, hydro carries
`marginal_cost = 0`, and hydro has no availability profile. The solver
therefore covers essentially all demand with hydro, dispatches thermal at
exactly 0 MW in every hour, and produces `objective_rs = 0` with a marginal
price of 0 at every bus in every hour (verified in PR-16).

In that state nothing downstream is testable. Merit order, thermal dispatch,
interchange economics and prices are all meaningless, and the project's
headline validation target — reproducing observed CMO — cannot even be
attempted.

The correct fix is a **water value**: hydro's true marginal cost is the
opportunity cost of not having the water later, which must be *computed* by a
multistage stochastic model (PRIMER §4: PAR(p) inflows → SDDP.jl → Benders
cuts → coupled into PyPSA via linopy). That is a multi-PR epic and the
intellectually hardest part of this project.

Meanwhile ONS publishes `geracao-usina-2`: **hourly verified generation per
plant**, including hydro. Dividing observed hydro generation by installed
hydro capacity yields an hourly `p_max_pu` per subsystem, exactly the shape
already used for wind and solar (PR-15).

## Decision

Constrain T0 hydro with an availability profile derived from **observed
historical generation**, as an explicitly-labelled **interim backcast**, while
the water-value work proceeds separately.

This is **backcasting, not optimisation**. The model is being told what hydro
actually did, rather than deciding what hydro should do. Consequences that
must be stated wherever a result is presented:

1. **Hydro dispatch is an input, not a result.** The model cannot be said to
   have "chosen" hydro output; it was given it.
2. **Validating prices against observed CMO is partly circular.** Observed
   generation is derived from the same real dispatch that produced observed
   prices. Any price agreement is weak evidence, and must not be presented as
   the model predicting prices.
3. **What it *does* legitimately answer** is narrower and still worth having:
   given real hydro output, does the rest of the system behave sensibly? Is
   the thermal/renewable/interchange split in the right ballpark against ONS's
   published generation mix? Does the pipeline produce nonzero, plausibly
   ordered prices at all?

A fair test exists within those limits: comparing **annual generation mix by
carrier** against ONS's published figures is legitimate, because the
comparison target (an annual aggregate) is much coarser than the input (an
hourly per-subsystem hydro profile), and because thermal, wind and solar
dispatch remain genuine model outputs.

## Alternatives considered

- **Wait for SDDP water values before constraining hydro at all.** Rejected as
  the immediate step: it leaves the model degenerate and untestable for the
  duration of a large epic, so every intervening PR would ship unverifiable.
  Still the correct destination; this ADR does not displace it.
- **A flat hydro capacity factor** (e.g. a constant 0.5 `p_max_pu`). Rejected:
  invents a number with no basis and discards real seasonal and inter-subsystem
  structure that is freely available.
- **A nonzero fabricated hydro `marginal_cost`** to force thermal into merit
  order. Rejected outright: a made-up water value presented as a cost is
  exactly the "plausible, confident, wrong" failure mode PRIMER §7.1 warns
  about, and it would be far harder to spot later than an explicit profile.
- **`p_set` / must-run rather than `p_max_pu`.** Rejected: `p_max_pu` sets an
  upper bound and leaves the solver free to dispatch *less* hydro when that is
  cheaper, preserving some optimisation. Fixing `p_set` would make hydro purely
  exogenous and remove even that.

## Consequences

**Positive.** The model stops being degenerate: thermal dispatch, interchange
and prices become nonzero and inspectable for the first time. It exercises the
entire pipeline end-to-end, which will surface the Tier-2 simplifications
(single yearly CVU mean, aggregate generators, transfer proxies) that are
currently invisible behind the hydro problem. The `all_prices_zero` flag added
in PR-16 is the concrete pass/fail signal.

**Negative.** Any result produced in this state is *not* a validated model
result, and is trivially misreadable as one by anyone who skips the caveats —
which is why the labelling obligation is written into this ADR rather than
left to a handoff note. Publishing a price comparison from this configuration
without the backcast caveat would be misconduct, not just imprecision.

**Risk.** The interim becomes the destination — the model looks plausible
enough that the water-value work is deprivileged. Mitigated by: (1) this ADR
naming its own expected superseding ADR; (2) `KNOWN_LIMITATIONS` carrying the
backcast caveat in every dispatch summary; (3) the generation-mix comparison
being framed as a ballpark check, never as validation.
