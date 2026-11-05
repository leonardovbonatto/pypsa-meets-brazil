<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0011 — Last month's inflow as an SDDP state (levels PAR(1))

- **Status:** Accepted 2026-11-04
- **Date:** 2026-11-04
- **Supersedes:** — (may supersede ADR-0010 decisions 1-3 if the comparison in
  decision 5 favours it; that would be a separate status change)
- **Superseded by:** —

## Context

The policy forgets how dry it is. SDDP remembers two things from one month to
the next: reservoir storage, and the regime label (dry, normal or wet per
region, ADR-0010). Within a regime each month's inflow is drawn fresh from
that node's 10 scenarios, ignoring last month's amount. So a very dry May is
often followed by a mildly dry June. Measured on the training scenarios, N's
month-to-month correlation of log inflow is 0.46; the fitted PAR(1) and the
2000-2025 history both give 0.88 (PR-45, PR-46).

SDDP allows memory only through state variables that appear in the linear
subproblem. The log-space PAR(1) cannot: `inflow = exp(mu + sigma*z)` is
nonlinear, so a `z` state got zero cut coefficients (PR-40). A levels-space
PAR(1) is linear and can enter the water balance directly.

**How NEWAVE does it** (CEPEL's model for the Brazilian system): PAR(p) in
levels, with the last p inflows as SDDP states alongside storage, and
three-parameter lognormal residuals for skewness and to avoid negative
inflows. The lognormal's floor depends on past inflows, which makes the model
strictly nonlinear; NEWAVE's cuts use the linear PAR(p) slopes as an
approximation. Sources: Melo, Maceira et al., SBA 2023 (CEPEL/UERJ); PUC-Rio
thesis 15500 sec. 2.2.4, citing Maceira & Mercio (1997), Marcato (2002),
Finardi et al. (2009). CEPEL's PAR(p)-A adds a term for the mean of the past
12 months to improve persistence (CEPEL report 1274/2021, cited, not read).
SDDP.jl's maintainer endorses lagged inflow states with the noise fixed in
`parameterize`, and links the package's PAR tutorial (Julia Discourse thread
135757).

**ADR-0009 rejected levels space on a negative-inflow rate that does not
reproduce.** It reported 19.3% (N), 14.7% (NE), 6.7% (S), 0.016% (SE_CO) of
simulated months negative with Gaussian noise. Its code was not kept.
Refitting a standard levels PAR(1) on the same data (standardised per month,
shocks scaled by `sqrt(1 - phi^2)`), 20,000 simulated years per subsystem:

| subsystem | model | negative months | lag-1 log corr | annual sd (MWmed) |
|---|---|---|---|---|
| N | history, 26 years | 0 | 0.882 | 32,841 |
| N | log PAR(1) (current fit) | 0 | 0.880 | 31,796 |
| N | levels, Gaussian noise | 1.53% | 0.758 | 34,114 |
| N | levels, 3-parameter lognormal noise | 1.21% | 0.774 | 34,213 |
| NE | history | 0 | 0.784 | 20,469 |
| NE | levels, lognormal noise | 0.89% | 0.660 | 20,730 |
| S | history | 0 | 0.649 | 39,521 |
| S | levels, Gaussian noise | 6.44% | 0.410 | 38,433 |
| S | levels, lognormal noise | 3.69% | 0.454 | 38,408 |
| SE_CO | history | 0 | 0.654 | 54,541 |
| SE_CO | levels, lognormal noise | 0.007% | 0.597 | 52,942 |

S and SE_CO match ADR-0009 under correct scaling; N and NE do not under
either scaling (unscaled shocks give N 15.3%, NE 7.3%). For N the rate is
about 1.5%, not 19.3%. The lag-1 log correlation of levels models is lowered
by the negative months (clipped to 1 MWmed for the log), so it understates
their memory; their correlation in levels matches the fit by construction.
The lognormal here has a fixed floor per month (moments-fitted to the
residuals' skewness), so the recursion stays linear; it roughly halves S's
negative rate but does not remove it, because negatives come from runs of
low months, not one large shock.

The measuring script is committed with the implementation, so this table can
be rerun; ADR-0009's could not.

## Decision

1. **Add last month's inflow per subsystem as four SDDP states**, linked by
   `inflow_t = mu_m + Phi_m * (inflow_{t-1} - mu_{m-1}) + sd_m * sqrt(1 -
   phi_m^2) * e_t`, with `Phi_m = phi_m * sd_m / sd_{m-1}`. The cuts then carry
   a coefficient on each subsystem's last inflow: memory per subsystem, more
   regional than ADR-0010's three regions.
2. **Noise `e_t`: three-parameter lognormal per subsystem and month, fitted by
   moments to the levels residuals, with a fixed floor.** Spatial correlation
   enters through the underlying normals, using the pooled matrix method of
   PR-29. Where a month's residual skewness is at or below 0.05, use Gaussian
   noise.
3. **Negative inflow is absorbed by a penalised slack** in the water balance,
   costed above load shedding so it is never chosen for its own sake. Its
   frequency and cost are reported in `summary.json`; a run where the slack
   carries more than 1% of S's inflow energy is a failure to investigate.
4. **The acceptance test asks the same question with the new memory:** at stage
   6 and 50% storage, water value with a subsystem's own last inflow at its
   10th percentile must be at least the value at its 90th percentile, others
   at their mean, in every subsystem and strictly in one. The grid report is
   kept.
5. **Measured against ADR-0010 before replacing anything.** First build this on
   a linear policy graph (12 nodes, storage plus inflow states), scored on the
   same 1000 log-PAR(1) paths, serial training, same seed and iteration limit.
   Keep whichever has lower cost on those paths; combining both is a later
   option, not this ADR.
6. **The 1000 scoring paths stay log-PAR(1).** They are the stand-in for real
   rivers, so every design is judged on the same water.

## Alternatives considered

- **More regime bins per region.** Narrows the gap within a bin but nodes grow
  as K^3; 0.62 at K=7 nationally (PR-45). Rejected as the main route.
- **NEWAVE's state-dependent floor.** Guarantees positive inflow but is
  nonlinear; NEWAVE approximates the cut slopes. Kept as a refinement if the
  slack in decision 3 binds too often.
- **PAR(p)-A (last-12-month mean term).** Adds persistence beyond lag 1, at the
  cost of 12 more states per subsystem or a running-mean state. Deferred until
  lag 1 is measured.
- **Keep ADR-0010 as is.** Leaves N at 0.46 against 0.88.

## Consequences

**Positive.** The policy can tell a deep drought from a mild one. The regime
graph may become unnecessary, which would cut nodes from 324 to 12 and
training time with it.

**Negative.** Four more states make cuts harder to converge. Negative inflows
remain at about 1-4% of months for N, NE and S and must be absorbed. Training
on levels and scoring on log paths keeps a smaller version of the mismatch
this ADR addresses. Levels noise is fitted on 26 values per month, so
skewness estimates are noisy.

**Risk.** Scoring on fixed paths needs `SDDP.Historical` to accept noise values
recovered from each path, which may fall outside the fitted support; if it
does not, scoring needs another route. The 1% slack threshold in decision 3
is a judgement set before any run.

## Outcome (PR-48, 2026-11-04): built, not adopted

Serial, seed 0, 4000 iterations, same 1000 log-PAR(1) scoring paths:

| | ADR-0010 regional | ADR-0011 inflow state |
|---|---|---|
| cost on PAR(1) paths | R$233.78bn | R$233.76bn |
| mean / P90 load shed (MW-months) | 22,438 / 46,129 | 22,520 / 45,699 |
| acceptance test | fails (SE_CO) | **fails**: dry = wet in all four subsystems |
| grid comparisons backwards | 164 of 1,188 (14%) | 21 of 3,564 (0.6%) |
| grid comparisons tied | 52 (4%) | 2,109 (59%) |
| S deficit share (limit 1%) | — | 0.98% |
| training time | 2 h 31 | 13 min |

The cost difference (0.01%) is below what reseeding the training noise would
move, so decision 5's "lower cost" is not a result. The acceptance test fails:
at stage 6 and 50% storage the same cut is active after a P10 and a P90 month,
so last month's inflow shifts the level of future cost (S: 54,633 vs 3,185)
but not its slope in storage. Across the grid the memory moves water values
the right way in 40% of comparisons and the wrong way in 0.6%.

The project owner's rule for this test was to keep the method only if results
got better. They did not, so ADR-0010 stays the policy and this one is kept
as tested code for later. Open questions for that later:

- Why storage and last inflow enter the cuts almost additively. Likely the
  isolated subsystems: without transmission each subsystem's water value sits
  on its own thermal plateau or shedding cap, and memory only changes how
  often it gets there. Re-run after ADR-0012's transmission.
- S's deficit share sits just under the 1% limit; NEWAVE's state-dependent
  floor would remove it.
- Whether one reference point is the right test for a model whose water value
  is flat in last inflow over wide regions.
