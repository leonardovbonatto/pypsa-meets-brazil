<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0021 — T0 thermal as cost bands of joined plants

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** — (refines PR-10's one averaged cost per subsystem in T0)
- **Superseded by:** —

## Context

T0 has one thermal generator per subsystem at the unweighted mean CVU of
its plants (PR-10): N R$237/MWh, NE 639, S 464, SE_CO 549. Merit order
between subsystems is then set by averages: in the 2024 solve flexible
thermal runs in N (cheapest average) while NE sits at its floor and ONS ran
about 350 MW more there (PR-62). Thermal availability is not modelled
either: ONS's own data shows 17.6 of 21.4 GW available in January 2024.

PR-09 found no join between CVU (`cod_usinaplanejamento`) and the capacity
registry (`ceg`). `geracao_termica_despacho` carries both keys, and
`disponibilidade_usina` carries `ceg` with hourly availability. Measured
2024 coverage (PR-62 handoff): 78 of 81 thermal plants in the availability
data get a CVU, 22.0 GW installed; they produced 4.47 of 6.58 GW of
dispatched thermal.

## Decision

1. **Joined plants** (in `disponibilidade_usina` as UTE, with a 2024 CVU
   through the bridge) are grouped per subsystem into **CVU bands with
   edges 150, 300, 500 and 800 R$/MWh**. Each band is one generator
   `{s} thermal_b{k}`, carrier `thermal`:
   - p_nom: summed installed capacity of its plants;
   - p_max_pu: summed hourly operational availability over p_nom;
   - marginal cost: installed-capacity-weighted mean 2024 CVU (a plant's
     CVU is the mean over its weeks and planning codes);
   - floor: the sum of its plants' ADR-0016 floors (verified generation
     minus merit order above inflexibility), monthly, capped at
     availability.
2. **The residual** `{s} thermal` keeps the registry capacity not covered
   by bands (never below zero), PR-10's averaged CVU, PR-59's commissioning
   scaling, and the part of the subsystem's ADR-0016 floor the bands do not
   carry.
3. SDDP's inputs are unchanged (one thermal per subsystem); SDDP is paused.
4. Band edges are fixed here, before any run; they are round numbers
   spanning 2024's CVU range, not fitted.

## Alternatives considered

- **One generator per plant.** About 80 more generators per hour; bands keep
  the LP small and the merit order nearly as fine.
- **Capacity-weighted cost for the single generator.** Fixes the average,
  not the merit order within a subsystem.

## Consequences

**Positive.** Merit order and outages follow real plants for two-thirds of
dispatched thermal output.

**Negative.** The residual (about 8 GW of registry capacity, 2.1 GW of 2024
output) keeps an averaged cost. A plant's CVU is a 2024 mean, not weekly.
