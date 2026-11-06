<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0023 — Wind and solar availability before curtailment

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** — (refines PR-15's availability)
- **Superseded by:** —

## Context

T0's wind and solar p_max_pu come from `fator_capacidade`, built from
verified output, which is net of ONS's constrained-off. 2024 curtailment
was large: wind NE 10.4% of potential output, solar NE 17.7% and SE_CO
10.7% (April-December), up to 18-23% in September. A model given
post-curtailment availability cannot curtail for itself, and in T1 it
curtails on top (PR-69: RN solar).

ONS's constrained-off detail (`restricao_coff_eolica_detail_tm`,
`restricao_coff_fotovoltaica_detail_tm`) gives per plant and half hour the
verified output, an estimate from wind speed or irradiance, and a
restriction flag.

## Decision

1. Wind and solar p_max_pu are scaled per (hour, subsystem) by
   (verified + unrealised) / verified, capped at p_max_pu 1, where
   unrealised is the estimate above verified **in restricted periods
   only**, so the estimator's bias in free hours does not enter.
2. Solar has no detail before April 2024: factor 1 there.
3. `uncurtailed` in `build_network_t0` switches it (default on).

## Outcome (PR-70)

| | before | after |
|---|---|---|
| T0 wind / solar vs ONS | 0.977 / 0.971 | 1.071 / 0.963 |
| T0 boundaries passing (ADR-0020) | 2 of 4 | 1 of 4 |
| T1 wind / solar vs ONS | 0.976 / 0.960 | 1.014 / 1.003 |
| T1 boundaries passing (ADR-0020's criterion) | 2 of 4 | **4 of 4** |
| T1 generation within 1% of T0 (ADR-0022) | fails (solar) | fails (wind 0.947, solar 1.041, hydro 1.012) |

T1 reproduces ONS's curtailment and interchange from state-level
congestion alone; nothing was fitted to 2024 curtailment. T0, with no
congestion inside subsystems, over-produces wind. ADR-0022's T0-equivalence
check was written for a split that cannot change dispatch; with
curtailment left to the model, it no longer can be met, and that is
reported as a failure rather than redefined.

## Consequences

**Positive.** Curtailment becomes a model result, testable against ONS.

**Negative.** T0's gate gets worse; the estimate is ONS's, not ours.
