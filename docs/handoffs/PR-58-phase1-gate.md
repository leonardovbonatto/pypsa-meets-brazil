<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-58 — The Phase 1 gate, scored: fails

`check_phase1_gate` (ADR-0020, criterion committed first in `dd98b20`)
scores the solved T0 network against ONS's 2024 generation per plant and
interchange. Target: `results/<run>/phase1_gate/report.json`; the report is
always written and `passed` is the verdict.

## Result (run t0-292abfaa): fails

| national mean, MW | model | ONS | ratio | |
|---|---|---|---|---|
| wind | 12,971 | 12,238 | 1.060 | fail |
| utility solar | 4,789 | 3,234 | 1.481 | fail |
| nuclear | 1,990 | 1,791 | 1.111 | fail |
| thermal | 8,468 | 8,161 | 1.038 | pass |
| hydro (backcast, not scored) | 45,602 | 48,760 | 0.935 | |
| MMGD (backcast, not scored) | 5,123 | 5,126 | 0.999 | |

| boundary | model mean | ONS mean | error / capacity | hourly corr. |
|---|---|---|---|---|
| N-NE | +1,169 | −1,467 | 0.44 | 0.76 |
| N-SE_CO | +1,728 | +3,150 | 0.14 | 0.73 |
| NE-SE_CO | +6,921 | +3,775 | 0.38 | 0.55 |
| SE_CO-S | +725 | +209 | 0.075 | 0.90 |

## Causes found

1. **Capacity is today's registry, not 2024's.** `build_generators` keeps
   every plant without a deactivation date, including ones that entered
   operation in 2025-26 (latest entry 2026-08-04). Operating capacity
   averaged over 2024 is 63.5% of the registry for solar, 89% for wind, 92%
   for thermal. Solar scaled by 0.635 lands at about −6% of ONS.
2. **Nuclear has no outages.** Angra runs at 1,990 MW all year; ONS shows
   refuelling (961 MW in November, 1,034 in December).
3. **Hydro under-runs its backcast ceiling** (0.935): with water, wind and
   solar all at zero cost, the solver curtails hydro to fit surplus solar.
   The same kind of tie as PR-56's.
4. NE's surplus solar flows out, so N-NE reverses and NE-SE_CO doubles.

## Next PR needs

- Capacity per month from `dat_entradaoperacao` (cause 1), then re-score.
  Then nuclear availability and the hydro/renewables tie, one at a time.
