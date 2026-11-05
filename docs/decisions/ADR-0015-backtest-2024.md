<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0015 — The 2024 backtest and its pass criterion

- **Status:** Proposed
- **Date:** 2026-11-04
- **Supersedes:** —
- **Superseded by:** —

## Context

The roadmap's Phase 7 gate is a backtest against ONS CMO and EAR
trajectories (`Brazilian-Grid-in-PyPSA.md` §8, plan step 6). ADR-0014 makes
2024 hydro a decision valued by SDDP cuts, so for the first time a match with
observed prices would not be circular (ADR-0007). The targets exist: monthly
CMO from half-hourly data (PR-47) and daily EAR per subsystem (PR-30).

2024 had a clear shape. SE_CO's monthly CMO stayed under R$10/MWh from January
to May, then rose to R$516 in October with the drought, and fell to R$14 by
December (PR-47). Reservoirs filled in the wet season and drew down after.

SDDP still has gross inflow, no minimum outflows and monthly-average
transmission limits, which move price and storage **levels** before they
change **shapes**. A level test would mostly measure those known gaps.

This criterion is written and committed before any coupled run finishes.

## Decision

1. **Window: January to November 2024.** December carries ADR-0014's end
   effect (no water value after the last stage).
2. **Storage passes** if the Pearson correlation between model and observed
   end-of-month EAR (% of capacity) is at least 0.6 in at least 3 of the 4
   subsystems.
3. **Price passes** if the Spearman rank correlation between the model's
   monthly mean price and observed monthly mean CMO in SE_CO is at least 0.5.
   SE_CO sets most of the system's price and carries most of its storage.
4. **The backtest passes only if both pass.** Levels (mean price against
   mean CMO, storage error in percentage points) are reported for every
   subsystem and decide nothing.
5. `scripts/backtest_2024.py` implements this; its thresholds are module
   constants. Changing them needs a new decision, made before rerunning.

## Alternatives considered

- **Level-based thresholds (e.g. CMO within 20%).** Rejected for now: they
  would fail on the known SDDP simplifications before testing anything else.
  The right second gate once those are fixed.
- **All four subsystems on price.** N and NE prices are mostly SE_CO's through
  transmission; one market test plus four storage tests is less redundant.
- **Weekly CMO.** Monthly matches SDDP's resolution and the coupling's.

## Consequences

**Positive.** A clear, pre-registered answer to "does the coupled model get
2024's shape?", tested on data the model did not see as dispatch.

**Negative.** Eleven points per subsystem: correlation thresholds on 11
months are loose, and one month can swing them.

**Risk.** Passing on shape with levels far off would still leave the model
unfit for price forecasting. The report keeps levels visible for that reason.
