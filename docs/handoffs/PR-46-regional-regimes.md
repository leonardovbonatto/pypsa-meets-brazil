<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-46 — Regional hydrological regimes (ADR-0010, proposed)

**Landed:**

- `docs/decisions/ADR-0010-regional-hydrological-regimes.md`, **Proposed**:
  waits for the project owner to accept it.
- `scripts/prepare_sddp_inputs.py` — `simulate_par1_anomalies`,
  `regional_states`, `joint_transitions`, `sample_regional_scenarios`;
  `sample_par1_paths` takes `regions`. ADR-0009's analytic national functions
  (`system_phi_by_month`, `transition_matrices`, `sample_markov_scenarios`)
  are removed.
- `rules/sddp.smk` — `SDDP_REGIONS` (N+NE, SE_CO, S), `SDDP_MARKOV_STATES = 3`
  per region, `n_simulated_years = 200000`.
- `scripts/check_sddp_regimes.py` — `regional_report`: each subsystem against
  its own region, others at normal. The all-dry vs all-wet comparison is gone.
- `julia/sddp_first_policy.jl` — `SDDP.Threaded()` when started with
  `--threads`; limitations updated. No structural change: a joint regime is a
  node index.
- Tests: 25 in `test_prepare_sddp_inputs.py`, 15 in `test_check_sddp_regimes.py`.

## Why

Direction set by the project owner: Brazil's regions have different rain, so
the policy must see them independently. One national label could not show N
wet while S is dry. N+NE share a label (+0.48 correlated); S runs opposite to
the north (-0.25, -0.26); SE_CO dominates storage.

## Results (threaded, same 1000 PAR(1) paths as PR-45)

| | national K=3 | national K=5 | regional |
|---|---|---|---|
| expectation cost | R$239.9bn | R$238.9bn | **R$233.7bn** |
| CVaR λ=0.5 cost | R$246.0bn | R$249.0bn | **R$240.3bn** |
| expectation, acceptance | fail | fail | **pass** |

Regional expectation, own region dry / wet (R$ million per MWmes, June, 50%):
N 0.186 / 0.177, NE 0.482 / 0.475, S 6.44 / 4.67, SE_CO 0.0046 / 0.0029.
Grid: 146 of 1,188 comparisons backwards, so the pass at the reference point
is not clean across the year. The N and NE gaps are small; S carries the
signal.

## Serial results reverse both verdicts

Serial, 4000 iterations, through Snakemake (2026-11-03):

| | cost on PAR(1) paths | test | backwards grid points |
|---|---|---|---|
| expectation | R$233.8bn | **fail** on SE_CO | 164 |
| CVaR λ=0.5 | R$240.5bn | pass | 97 |

Expectation, own region dry / wet: N 0.182 / 0.176, NE 0.509 / 0.477,
S 6.46 / 4.69, SE_CO **0.00087 / 0.00106**. CVaR: N 0.184 / 0.177,
NE 0.521 / 0.504, S 7.30 / 7.02, SE_CO 0.0148 / 0.0118.

Costs reproduce the threaded runs within 0.1%; the verdicts do not. SE_CO's
water value at the reference point is about R$1/MWh in both regimes, so the
sign of its gap there is close to noise. The pass criterion was fixed in
advance and is not relaxed here: whether the test should skip a subsystem
whose water is nearly free, or move to a lower storage fraction, is the
project owner's decision, and it belongs in ADR-0010 before acceptance.

## What did not work

- **Regions do not restore persistence.** N's month-to-month correlation in
  training scenarios is 0.46 regional vs 0.48 national; PAR(1) says 0.88.
  The loss is from drawing each month independently within a regime. Still
  open.
- **The first acceptance test asked the national question.** It compared
  joint state 1 (all dry) with 27 (all wet). The project owner caught it;
  the test now holds the other regions at normal.

## CVaR: the λ=0.5 failure was run variation

| λ | cost | test | backwards grid points |
|---|---|---|---|
| 0 | R$233.5bn | pass | 134 |
| 0.25 | R$233.9bn | pass | 73 |
| 0.5 (run 1) | R$240.3bn | **fail** | 147 |
| 0.5 (run 2) | R$240.3bn | pass | 104 |
| 0.75 | R$256.6bn | pass | 69 |

λ=0 matched the expectation policy exactly in a serial 200-iteration check.
The two λ=0.5 runs have identical cost but N's dry value went 0.18 -> 7.44:
CVaR's value at one point jumps between the thermal plateau and the
load-shed cap. Cost is stable; single-point slopes are not.

## Gotchas

- Threaded runs are about 9x faster and vary about 0.5% in cost. Explore with
  threads, record serially.
- 1.19M cuts, 6.6 GB peak RAM at 4000 iterations; WSL has 15 GB. Two
  regional runs at once would be tight.
- Joint state numbering: first region most significant, state 1 = all dry.
  `check_sddp_regimes.joint_state` must match `regional_states`.

## Next PR needs

- **A decision on SE_CO in the acceptance test** (see "Serial results"),
  before ADR-0010 is accepted.
- **Within-regime persistence** is the open modelling gap; ideas include more
  bins per region or conditioning draws on the previous month.
- Then step 4 of the plan: net load, transmission and curtailment in SDDP.
