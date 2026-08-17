<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-31 — The first SDDP policy, real data (ADR-0005 stage 1f)

**Landed:**

- `scripts/prepare_sddp_inputs.py` - joins T0 data (demand, hydro/thermal
  capacity, thermal cost) with PR-30's reservoir capacity and PR-28/29's
  fitted inflow model into Parquet files, including a correlated monthly
  scenario sampler.
- `julia/sddp_first_policy.jl` - a 4-subsystem, 12-stage hydro-thermal
  `SDDP.LinearPolicyGraph`, trained on real Brazilian data for the first
  time in this project.
- `rules/sddp.smk::prepare_sddp_inputs` and `::sddp_first_policy`.
- `test/test_prepare_sddp_inputs.py` (9 tests, including one that
  recovers a known cross-subsystem correlation from a large sample - the
  same discipline as PR-28/29).

This is the step ADR-0005 named as the epic's next stage after PAR(p)
fitting. It landed only after PR-30, which the original ADR-0005 staging
didn't explicitly call out: a hydro-thermal SDDP model needs real
reservoir *capacity*, not just inflow, and PR-30 supplied it rather than
this PR inventing a placeholder.

## The result

Trained cleanly: 0 numeric issues, converged in 50 iterations, 550 cuts
written. Expected annual system cost **R$240.9 million** (varies slightly
run to run - inflow scenarios are randomly sampled, seeded but not
identical between the two verification runs this session).

**The real finding worth understanding, not hiding**: simulating the
trained policy across 100 realizations, mean load shedding is
**18,074 MW-months/year**, and **~95% of it (17,178) is in subsystem S**:

| Subsystem | Mean load shed (MW-months/year) |
|---|---|
| N | 299 |
| NE | 383 |
| S | **17,178** |
| SE_CO | 213 |

**This is very likely the same structural gap PR-11 and PR-13 already
found and solved in the T0 network itself**, from a different angle. PR-11's
handoff: before inter-subsystem transmission existed, "S's own generator
capacity falls 202.6 MW short of S's own peak hourly demand ... while
N/NE/SE_CO all sit on 17,500-41,500 MW of spare capacity they cannot
export without lines." PR-13 added Links and the shortfall resolved to
zero. **This SDDP subproblem deliberately has no inter-subsystem
transmission** (see KNOWN_LIMITATIONS, both in `prepare_sddp_inputs.py`
and `sddp_first_policy.jl`) - PRIMER Sec 4.5's architecture puts real
network coupling in PyPSA/linopy once cuts are consumed there, not in
this reduced hydro-thermal model. So this policy is rediscovering S's
same real vulnerability - a subsystem with comparatively tight
hydro+thermal capacity margin (19,140 MW total vs. ~13,000-15,700 MW
monthly demand) and the weakest, most volatile fitted inflow persistence
of the four subsystems (PR-28: phi 0.34-0.81, vs. N's 0.80-0.98) - from
a genuinely independent model built with different tools, different data
granularity, and no knowledge of the earlier finding baked in.

**Two independently-built models finding the same real physical
constraint is treated as cross-validation here, not a bug to chase down
and eliminate.** Eliminating it would mean adding transmission to this
model - which is real future work (see Next PR needs), not something to
paper over by, say, loosening S's capacity bounds to make the number look
better.

## The units question, worked through carefully

Getting this wrong would have produced a confidently-wrong LP that solves
without complaint. Checked, not assumed: at MONTHLY granularity, three
different-looking units are directly commensurable without conversion:

- **ENA** (inflow) is MWmed - average power over the reporting period.
- **EAR** (storage) is MWmes (MW-month) - a stock expressed as "the
  average power this much stored energy could sustain for one month."
- **Generation/demand/capacity** (MW) - average power dispatched or
  demanded during the month, once T0's hourly series is aggregated to a
  monthly mean (`prepare_sddp_inputs.monthly_demand`).

Because the implicit time unit (one month) is baked into all three, the
storage balance `storage.out == storage.in - hydro_generation - spill +
inflow` is dimensionally correct with no scaling factor - this is
exactly why Brazil's own NEWAVE convention exists in these units. Cross-
checked against PR-30's EAR/ENA unit-discrepancy research: EAR's
dictionary and column name agree on "mwmes" (a stock, where MW-month is a
coherent unit); ENA's disagree (documented "MWmes", column says "mwmed",
a flow, where MW-month is not coherent) - consistent with treating ENA as
MWmed throughout, as PR-27 already inferred.

## Design choices worth knowing

- **Scenarios are i.i.d. per month, not autocorrelated month-to-month
  within the policy.** PAR(1)'s fitted phi (PR-28, real and validated) is
  NOT yet wired into SDDP's state. Doing so needs state augmentation -
  carrying the previous month's standardized shock as an extra state
  variable per subsystem - a real, separately-scoped follow-up, not
  attempted here. Named explicitly, not silently dropped: this is the
  single most important simplification in this PR, since it's a step back
  from PR-28/29's careful persistence work specifically for the SDDP
  policy (the fitted parameters and validation remain real and unaffected
  - only their use *inside SDDP* is simplified for this first cut).
- **12 monthly stages, one annual cycle** - not the infinite-horizon
  cyclic policy graph SDDP.jl also supports and Brazil's real planning
  uses.
- **No CVaR** - expectation-only, exactly ADR-0005's named scope for this
  stage.
- **`LOAD_SHED_COST = 10,000`** reused directly from
  `scripts/build_network.py`, not a new invented number - same reasoning
  as T0's own slack: a dispatch of last resort, never competitive in
  merit order, that keeps every monthly subproblem feasible regardless of
  how a bad-water scenario plays out.
- **Hydro/thermal capacity bounds are nameplate MW**, applied to a
  monthly-average dispatch variable - rarely binding at this timescale
  (the real limit on hydro is the storage balance itself, not nameplate);
  a simplification of within-month unit commitment, named in
  KNOWN_LIMITATIONS.
- **10 equally-likely scenarios per month** - a real, named simplification;
  unequal historically-weighted probabilities are a possible refinement.
- **Wind, solar and nuclear excluded** - not part of the reservoir-storage
  decision SDDP solves; PyPSA handles them directly once cuts are coupled
  in, per PRIMER's architecture.

## Gotchas

- Same `python -c` inline-quoting issue as every prior PR through
  `PowerShell → wsl.exe -lc` - every exploratory check used a scratch
  `.py` file.
- First version of the Julia summary-writing code hand-rolled JSON via
  string interpolation and `replace()` calls - fragile and unnecessary,
  since `SDDP.JSON` (already loaded, used for reading cuts) has a
  `JSON.print(io, obj, indent)` writer. Fixed before it ever ran for
  real, not found as a bug - but worth remembering the library was
  already in scope.

## Next PR needs

Per ADR-0005's order: **CVaR risk aversion**, next. After that,
**individualized reservoirs** (a future ADR, superseding ADR-0005).
Separately, two real follow-ups this PR's own findings point at directly,
neither blocking the ADR-0005 sequence but both worth prioritizing:

1. **Temporal persistence inside the policy** (state-augmented AR
   inflow) - the gap this handoff calls out as the most significant
   remaining simplification.
2. **Inter-subsystem transmission in the SDDP subproblem**, or an
   explicit decision that this stays PyPSA's job permanently (per
   PRIMER's architecture) rather than SDDP's - worth a deliberate
   decision, not a default, given how large and structurally-explained
   S's load-shedding number turned out to be.

## Open questions

- Whether coupling these real cuts into the actual T0 PyPSA network
  (replacing ADR-0007's backcast) is the next major milestone, or whether
  CVaR/individualization should come first, per the ADR's literal
  ordering - worth revisiting with the project owner rather than assumed.
