<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0016 — A thermal floor from ONS dispatch reasons

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes:** —
- **Superseded by:** —

## Context

With transmission and net load (ADR-0012, ADR-0013), SDDP's expected annual
cost on the 1000 PAR(1) paths fell to R$0.47bn (inflow-state model), with no
shedding: hydro covered all residual demand and thermal barely ran. In 2024
Brazil ran about 6.6 GW of thermal on average, measured from ONS's
`geracao_termica_despacho` (hourly, per plant, by dispatch reason): 64% of it
by declared inflexibility, about 0.3 GW for electrical reasons, and merit
order only rising in the September-October drought. ONS's monthly cost
bulletins put inflexibility at 67-90% of the thermal bill in 2025-2026.

That generation runs whatever the price, so a model that treats all thermal
as a free decision misses most of it.

## Decision

1. **Floor = total verified thermal minus merit-order generation above the
   inflexibility** (`val_verifgeracao - val_verifordemdemeritoacimadainflex`),
   summed over plants per hour and averaged per subsystem-month in the
   reference year. Everything that ran for reasons other than price.
2. **Capped at T0 thermal capacity** (no cap was needed in 2024).
3. **Applied in both models**: `p_min_pu` on `{s} thermal` in T0, held for
   each hour of the month; a lower bound on `thermal_generation` in SDDP.
4. **Same 2024 floor in every SDDP year.** Declared inflexibility follows
   contracts and is fairly stable; varying it is out of scope.

## Alternatives considered

- **Declared inflexibility only.** Leaves out electrical-reason and other
  out-of-merit dispatch, which also ignore price.
- **Per-plant minimums from CVU data.** T0 aggregates thermal per subsystem,
  so per-plant data would be averaged anyway.
- **No floor; fix SDDP's hydro instead** (storable inflow, minimum outflows).
  Needed too, but does not explain thermal that ran with water to spare.

## Consequences

**Positive.** System cost and prices come from the thermal that actually
had to run. Smoke run, inflow-state model at 200 iterations: R$22.5bn a year
on the PAR(1) paths, against R$0.47bn without the floor.

**Negative.** The floor is observed 2024 dispatch, so 2024 results are partly
an input again (narrower than ADR-0007: only the non-price part). Forward
years reuse 2024's floor.

**Risk.** In September-October 2024 part of the inflexibility ran inside the
merit order; counting it in the floor is right for 2024 but would double up
if merit dispatch were also imposed.
