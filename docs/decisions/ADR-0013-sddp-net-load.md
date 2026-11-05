<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0013 — Net load in the SDDP subproblem

- **Status:** Proposed
- **Date:** 2026-11-04
- **Supersedes:** — (lifts the "wind, solar and nuclear excluded" limitation
  of ADR-0005's stage 1 scope)
- **Superseded by:** —

## Context

SDDP serves all demand with hydro and thermal. PyPSA's T0 network, which will
consume the cuts (plan step 5), also has wind, solar, rooftop solar (MMGD) and
nuclear. Measured from `resources/networks/t0.nc` (`p_max_pu * p_nom`, monthly
means of 2024), those carriers make up about 25 GW on average across the
system: N 0.6, NE 15.3, S 1.8, SE_CO 7.1 GW. NE's monthly net load is negative
from May to December (down to -6.1 GW in September), and it is negative in 69%
of NE's hours.

Cuts trained without them describe a system that needs far more water and
thermal than the one PyPSA solves, so their water values would be wrong for
it. This is the second half of plan step 4 (`Brazilian-Grid-in-PyPSA.md` §8).

## Decision

1. **Renewables and nuclear are given, not dispatched.** Each subsystem-month
   gets the mean available MW of `wind`, `solar`, `solar_mmgd` and `nuclear`,
   computed by `prepare_sddp_inputs.network_renewables` from the built T0
   network, so SDDP and PyPSA use the same availability.
2. **Free curtailment**, bounded by the available MW, so negative net load is
   exported (ADR-0012) or curtailed, never forced into the balance.
3. **Same 2024 profile every year.** No renewable uncertainty in SDDP yet.
4. **Applies to whichever policy is current**, scored as before on the same
   1000 PAR(1) paths.

## Alternatives considered

- **Subtract renewables from demand outright.** Same thing when net load is
  positive; with NE negative it would need curtailment anyway, and a
  separate variable reports it.
- **Renewable scenarios in SDDP** (correlated wind/hydro, as NEWAVE now does).
  Deferred: needs a wind model; one fixed profile is the step before.
- **Add ONS constrained-off curtailment back to the capacity factors** before
  averaging, since `fator_capacidade` is measured after curtailment. Planned
  separately (plan step 4, second clause); this ADR only uses what T0 uses.

## Consequences

**Positive.** SDDP and PyPSA describe one system, which cut coupling needs.
Water values and costs fall to the scale of a system with 25 GW of
renewables and nuclear.

**Negative.** Monthly means hide solar's daily shape and wind lulls, so SDDP
sees no evening ramp. Availability is one year, 2024.

**Risk.** With this much free energy, hydro nameplate covers most residual
demand, so costs may now be understated: SDDP has no minimum outflows,
run-of-river limits or storable-vs-gross inflow distinction. A cost far
below real 2024 thermal spending points there, not at this ADR.
