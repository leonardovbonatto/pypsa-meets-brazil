<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0012 — Inter-subsystem transmission in the SDDP subproblem

- **Status:** Proposed
- **Date:** 2026-11-04
- **Supersedes:** — (lifts the "no transmission in SDDP" limitation of
  ADR-0005's stage 1 scope)
- **Superseded by:** —

## Context

The SDDP stage problem has had no transmission since PR-31. Each subsystem
dispatches alone: S cannot import from SE_CO and N cannot export its wet-season
surplus. On the 1000 PAR(1) scoring paths, S carries about 80% of all load
shedding in every run since PR-45, and SE_CO's water at half storage is worth
about R$1/MWh (PR-46). Both look like artefacts of isolation, not of hydrology.
This is step 4 of the source integration plan (`Brazilian-Grid-in-PyPSA.md` §8).

T0 already has the transfer representation, decided in ADR-0006: four real
ONS boundaries (N-NE, N-SE_CO, NE-SE_CO, SE_CO-S), bidirectional, capacity
equal to the largest absolute hourly flow in 2024, a documented lower-bound
proxy (`resources/links_t0.csv`).

SDDP is monthly, so a limit there bounds the **monthly average** flow. Measured
on the 2024 ONS interchange file:

| boundary | hourly max (MW) | max monthly mean (MW) | ratio |
|---|---|---|---|
| N-NE | 6,019 | 3,834 | 0.64 |
| N-SE_CO | 10,492 | 7,068 | 0.67 |
| NE-SE_CO | 8,311 | 5,829 | 0.70 |
| SE_CO-S | 6,902 | 2,435 | 0.35 |

So an hourly maximum used as a monthly-average limit is generous: no month of
2024 came within 30% of it.

## Decision

1. **Add the four T0 boundaries to the SDDP subproblem as transport flows**,
   one free variable per boundary per month, bounded by `links_t0.csv`'s
   `p_nom_mw` in both directions. Each subsystem's demand balance gains its
   net import. No losses, no cost on flow.
2. **The limit is the same `p_nom_mw` as T0**, not a separate monthly figure,
   so SDDP and PyPSA see one network. It is generous at monthly resolution
   (table above), stated in the limitations, and to be revisited with EPE's
   interchange limits (plan step 3).
3. **Applies to whichever policy is current**, the ADR-0011 inflow-state
   model if it beats ADR-0010, else the regional one. Scored on the same 1000
   PAR(1) paths, serial, same seed and iteration limit, so the effect of
   transmission alone is measured.

## Alternatives considered

- **Max observed monthly mean as the limit.** A lower bound from one year of
  data, at most 35% of hourly capacity on SE_CO-S; likely too tight and not
  what T0 uses. Rejected for now.
- **Wait for EPE's interchange limits.** EPE stays local and unlicensed for
  publishing; its numbers are a cross-check (step 3), not a blocker.
- **Hourly or load-block resolution inside each month.** NEWAVE uses load
  blocks; that multiplies the subproblem size and needs a block definition.
  Deferred.

## Consequences

**Positive.** S can import, so shedding should move from "S alone" to "the
system", and water values become comparable across subsystems.

**Negative.** Monthly-average limits ignore peak-hour congestion, so the model
will likely understate transmission scarcity. Water values in connected
subsystems will tend to equalise, which changes how ADR-0010/0011's
own-subsystem acceptance tests behave.

**Risk.** The acceptance tests were designed for isolated subsystems. With
transmission, a dry S may draw on SE_CO's water, so "S's water is worth more
when S is dry" may weaken without anything being wrong. Results are reported
as they come; any change to the tests needs its own decision.
