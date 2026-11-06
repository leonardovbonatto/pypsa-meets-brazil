<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0019 — Minimum operating storage (VminOp) as a soft constraint

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes:** —
- **Superseded by:** —

## Context

After PR-56 the coupled 2024 run passes the backtest on storage (3 of 4)
and fails on price: prices are near zero all year. SDDP's cost-to-go does
not depend on storage. From 2024's 60-90% storage, a one-year horizon
almost never runs short, so water is worth almost nothing at the margin.

ONS's own models do not let reservoirs run down freely. NEWAVE and DECOMP
enforce VminOp, a minimum operating storage per subsystem, as a penalised
soft constraint (CPAMP; modelled in DECOMP since 2022). It is one of the
two risk-aversion mechanisms in official use, alongside CVaR. Its values
for the 2024 cycle were set by the CPAMP plenary on 31/07/2023: 20% of
maximum storage in the Southeast (with Parana and Paranapanema), 30% in the
South (with Iguacu), 23.3% in the Northeast, and 22.5% in the North, 18% in
December following Tucurui's operating curve. One later source reports
19.1% for the North (NT-ONS DPL 0131-2023); the plenary value is used.

## Decision

1. **SDDP:** every stage has `storage_end + below_minimum >= VminOp *
   max_storage`, with `below_minimum >= 0` priced per MWh in the stage
   objective.
2. **Coupled run:** the same constraint on each reservoir's month-end
   storage, at the same price.
3. **Penalty = 1.1 x the dearest subsystem thermal cost** (R$703/MWh with
   2024 costs), the same in every subsystem and month. All thermal runs
   before the minimum is breached, and breaching it stays cheaper than load
   shedding (R$10,000/MWh). This rule and factor are fixed here, before any
   run; NEWAVE's own penalty values were not found in public sources.
4. Values live in `rules/sddp.smk` (`SDDP_VMINOP`, `SDDP_VMINOP_MONTHS`,
   `SDDP_VMINOP_PENALTY_FACTOR`).
5. The backtest criterion (ADR-0015) is unchanged.

## Alternatives considered

- **CRef, ONS's reference storage curves.** They guide CMSE's out-of-merit
  thermal dispatch rather than the price models, and are published only as
  figures. The thermal floor (ADR-0016) already carries what ONS ran for
  those reasons.
- **A hard constraint.** Infeasible in dry paths; NEWAVE uses a soft one.

## Consequences

**Positive.** Storage near the minimum carries a value of about the dearest
thermal cost, which is the mechanism ONS's prices reflect.

**Negative.** SDDP's reported cost now includes penalties, so it is not
comparable with earlier runs' cost. One minimum per subsystem stands in
for VminOp per REE.
