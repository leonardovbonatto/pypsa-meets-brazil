<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0010 — Regional hydrological regimes in the SDDP policy graph

- **Status:** Proposed
- **Date:** 2026-11-02
- **Supersedes:** ADR-0009 (decision 3, the single system-wide Markov state, and
  decision 2's analytic transition matrices only; the Markovian policy graph,
  dropping `z`, and the acceptance test all stand)
- **Superseded by:** —

## Context

PR-45 implemented ADR-0009 with one national regime shared by all four
subsystems. Seasonality was already regional, since `mu` and `sigma` are fitted
per month and subsystem. What stayed national is the **anomaly**: whether this
year is running dry or wet for the time of year. A failed wet season in the
North could not be seen apart from the South.

Measured in PR-45 at 4000 iterations:

| | K=3 | K=5 |
|---|---|---|
| acceptance test | fails on N, NE, SE_CO | fails on N alone |
| wet-above-dry grid comparisons | 26 | 12 |
| mean cost on PAR(1) paths, expectation | R$239.9bn | R$238.9bn |
| N month-to-month correlation (PAR(1): 0.88) | 0.48 | 0.57 |
| S month-to-month correlation (PAR(1): 0.66) | 0.47 | 0.58 |

Raising K improves water values but pushes every subsystem towards the same
persistence, about 0.6 even at K=7. One chain cannot carry N's 0.88 and S's 0.66
at once.

The fitted cross-subsystem correlations decide the grouping:

| pair | correlation |
|---|---|
| N-NE | +0.48 |
| NE-SE_CO | +0.39 |
| N-SE_CO | +0.22 |
| S-SE_CO | +0.20 |
| N-S | -0.25 |
| NE-S | -0.26 |

ADR-0009 rejected per-subsystem chains because of `K^4` states against a measured
convergence ceiling. PR-42 removed that ceiling, and PR-45 measured the bound
rising only about 0.3% from iteration 1000 to 4000.

## Decision

1. **Three regions, each with its own regime: N+NE, SE_CO, S, at K=3.** That is
   27 joint states and 324 nodes. N and NE share a label because they move
   together and have similar persistence. S runs opposite to the north, and
   SE_CO dominates storage.
2. **A joint regime is one Markov state.** State 1 is dry in every region and
   state 27 is wet in every region. Julia needs no structural change, because
   SDDP.jl only sees a larger graph.
3. **Transitions and scenarios come from a large simulation of the fitted
   PAR(1), not from analytic integrals.** Each region's regime is read from its
   own standardized, inflow-weighted anomaly. Transition probabilities are
   counted, and scenarios are sampled from the simulated months in each joint
   state. No new estimation enters: the simulation uses PR-28/29's parameters
   unchanged, with each subsystem's own `phi`.
4. **Regions are judged independently in the acceptance test.** Each subsystem
   is compared between its own region dry and its own region wet, with the
   other regions at normal; no comparison moves all regions at once. The
   threshold is ADR-0009's: stage 6, 50% storage, dry >= wet in every
   subsystem and strictly in at least one. A grid over every month, three
   storage levels and every combination of the other regions is reported.
5. **Comparison with K=3 and K=5 national is on the same 1000 PAR(1) paths.**

## First measurements (2026-11-02, before acceptance)

Recorded here because they change what this ADR can claim.

- **Regional regimes do not restore persistence.** Month-to-month log correlation
  of the training scenarios is N 0.46, NE 0.43, S 0.45, SE_CO 0.45, against 0.48,
  0.47, 0.47 and 0.45 for national K=3. The loss comes from drawing each month
  independently within a regime, not from the regime being national. The
  "Context" argument about persistence is therefore wrong; the case for this ADR
  rests on letting the policy see regions diverge.
- **Cost on the same 1000 PAR(1) paths is lower** (threaded training, which
  varies by about 0.5% between same-seed runs, so not yet confirmed serially):

  | | national K=3 | national K=5 | regional |
  |---|---|---|---|
  | expectation | R$239.9bn | R$238.9bn | R$233.7bn |
  | CVaR | R$246.0bn | R$249.0bn | R$240.3bn |

- **The acceptance test, with regions judged independently** (water value,
  millions of R$ per MWmes, own region dry vs wet, others normal):

  | | N | NE | S | SE_CO | result |
  |---|---|---|---|---|---|
  | expectation | 0.1857 / 0.1773 | 0.4819 / 0.4747 | 6.4409 / 4.6683 | 0.0046 / 0.0029 | **passes** |
  | CVaR | 0.1817 / 0.1817 | 0.4757 / 0.5531 | 7.2949 / 7.0103 | 0.0007 / 0.0006 | fails on N+NE |

  Grid: expectation 1002 dry above wet, 40 tied, 146 wet above dry; CVaR
  923 / 118 / 147. CVaR's N tie sits on its thermal plateau. **A rerun of the
  same CVaR settings passed** at identical cost (R$240.3bn), with N's dry
  value at 7.44 instead of 0.18: CVaR's single-point water values are not
  stable between threaded runs, so the CVaR verdict waits on a serial run.
- **CVaR lambda sweep** (threaded): lambda=0 matches the expectation policy
  exactly (serial check); cost R$233.5bn at 0, 233.9 at 0.25, 240.3 at 0.5,
  256.6 at 0.75; the acceptance test passes at 0, 0.25 and 0.75. An earlier draft
  compared "dry everywhere" with "wet everywhere", which is the national
  question again; it failed on NE and is not the test this ADR adopts.
- **Serial runs reverse both verdicts.** Expectation R$233.8bn, **fails on
  SE_CO** (0.00087 dry / 0.00106 wet, others pass); CVaR lambda=0.5
  R$240.5bn, passes. SE_CO's water value there is about R$1/MWh, so its sign
  is close to noise. Open before acceptance: whether the test should exempt a
  subsystem whose water is nearly free, or use a lower storage fraction.
- **Cost of the larger graph**: 1.19 million cuts, 6.6 GB peak RAM, about 13
  minutes with 12 threads against 2 h 31 serial.

## Alternatives considered

- **Keep raising K on one national chain.** Rejected on the table above: it
  flattens persistence towards one value.
- **S versus the rest (108 nodes).** Kept as the fallback if three regions are
  too slow. It leaves SE_CO and the north sharing a label despite different
  persistence.
- **Pairing N+NE and S+SE_CO.** Rejected: S-SE_CO is only +0.20.
- **Four regions (K=2: 192 nodes; K=3: 972 nodes).** K=2 cannot express normal
  years, and K=3 is three times the size of this decision for one more split of
  two subsystems that move together.
- **Analytic joint transitions.** Rejected: integrating correlated bins in three
  dimensions adds real code and failure modes for what a seeded simulation
  answers directly.

## Consequences

**Positive.** Each region gets its own persistence and can diverge, so the policy
can see N wet while S is dry. Scenario sampling becomes simpler and preserves
cross-region correlation by construction.

**Negative.** Nodes rise ninefold from K=3 national, and cuts per iteration rise
to 297. At 4000 iterations that is about 1.2 million cuts against 15 GB of RAM in
WSL, so memory may bind before time does. Training may need fewer iterations,
`SDDP.Threaded()`, or cut selection. Threaded training is experimental upstream
and may break same-seed repeatability. Transition probabilities and scenarios now
carry sampling noise, which must be kept small.

**Risk.** Regional regimes may not lower cost much. On PAR(1) paths S carries
about 80% of shedding in every PR-45 run, which fits SDDP having no transmission
and no renewables. Those are separate work. Months within a regime also remain
independent of each other, so some persistence stays lost, and the PAR(1) test
measures how much. N may keep failing because its value sits on its thermal
plateau. If so, that gets reported, and any change to the criterion needs its
own decision.
