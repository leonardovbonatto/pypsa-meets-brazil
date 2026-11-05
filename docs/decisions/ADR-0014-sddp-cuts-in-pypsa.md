<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0014 — SDDP water values in the PyPSA T0 model

- **Status:** Proposed
- **Date:** 2026-11-04
- **Supersedes:** ADR-0007 for the new `solve_network_sddp` run only; the
  backcast run stays for comparison
- **Superseded by:** —

## Context

T0 hydro is a backcast: it is told what it generated in 2024 (ADR-0007), so
its prices cannot be validated against CMO without circularity. The fix
ADR-0007 named is a water value computed by SDDP and handed to PyPSA. With
transmission (ADR-0012) and net load (ADR-0013), SDDP and T0 now describe
the same system, so the cuts can be coupled. This is plan step 5
(`Brazilian-Grid-in-PyPSA.md` §8; the architecture is §6's
`alpha >= a_k + sum_i pi_ik * SoC_i`).

The cuts are per month and regime, in millions of R$ against MWmes of
storage. SDDP's 12th stage has no cuts.

## Decision

1. **One reservoir per subsystem.** Each `{s} hydro` generator becomes a
   StorageUnit with the same `p_nom`, energy capacity `ear_max_mwmes`,
   observed 2024 daily gross inflow held for each hour, and observed storage
   on 2023-12-31 as its start. No pumping, free spill.
2. **Monthly rolling solve.** Each calendar month is one hourly solve. Its
   objective gains `alpha` (R$), bounded below by every cut of the SDDP node
   (month, regime) evaluated at the reservoirs' storage in the month's last
   hour. The ending storage starts the next month.
3. **The regime is read from observed 2024 inflow**, with the same
   standardisation and regional labelling as the SDDP training years.
4. **Units:** 1 MWmes = 730 MWh for every month, the convention the SDDP
   model already uses.
5. **December carries no water value**, because SDDP's last stage has none.
   Reported as an end effect, not fixed here.
6. **Cuts from the regional expectation policy** (ADR-0010), the current one.

## Alternatives considered

- **One annual solve with cuts at every month boundary.** Wrong: the cuts at
  month m already price the optimal future from m+1, which the same solve
  would also optimise, counting the future twice.
- **Water value as a fixed marginal cost on hydro.** Simpler, but a single
  slope ignores that the value falls as storage fills; the cuts carry that.
- **Individual plants and cascades.** Needs Phase 3's hydro physics; T0 is
  aggregate on both sides.
- **A cyclic SDDP graph so December has a value.** Better, and the obvious
  next step for the end effect; it changes the SDDP model, not this coupling.

## Consequences

**Positive.** Hydro becomes a decision, so prices are an output the 2024
backtest (plan step 6) can test against CMO without ADR-0007's circularity.

**Negative.** Each month sees its own hourly inflow and demand perfectly.
Storage is aggregate per subsystem. December will tend to draw reservoirs down.

**Risk.** The coupled run inherits every SDDP simplification (no minimum
outflows, gross inflow, monthly-average transmission limits). If prices come
out far from CMO, the cause may sit in SDDP, not the coupling; the backtest
reports EAR trajectories alongside prices to tell the two apart.

## Outcome (PR-51/52, 2026-11-05)

Cuts from the regional expectation policy with transmission, net load and
the thermal floor (converged at 200 iterations). The first coupled run hit a
degenerate tie: where the cuts value water at zero, spilling and storing cost
the same, and SE_CO spilled 36.8 GW in January while drawing its storage down,
empty by April. A spill cost of R$0.01/MWh (`SPILL_COST`) breaks the tie and
was added; both runs are reported in the PR-52 handoff. With it, storage
tracks 2024 from January to May and then drains far faster than observed
(SE_CO 22% in August against 56%); prices are zero in ten of eleven months
and spike to R$500 in October (observed R$516). Water is valued too low.
