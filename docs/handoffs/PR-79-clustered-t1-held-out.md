<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-79 — Clustered T1 on the held-out years (ADR-0027)

ADR-0027 was committed (`934beb4`) before either run. Result: **fail**.
2025 decides and passed 4 of 8, equal to the DLR T1, not more. 2023
passed 5 of 8, equal to DLR. Full table in ADR-0027's Outcome.

Run: `snakemake -j1 <targets> --configfile config/config.<year>.yaml`.
Targets go **before** `--configfile`, which takes several files and
otherwise swallows the targets. About 8 min and 13 GB per year, from T0
through T3 energy, clustering and the year solve. No data fixes needed.

## Pattern over three years (2024 post hoc, 2023 and 2025 held out)

- **N-NE passes every year** (0.6-4.3% of capacity). DLR failed it in both
  held-out years: the real grid around the North fixes this one.
- **N-SE_CO fails every year**, always too high (8.5-14.9%). Belo Monte's
  HVDC is free and two-way; PR-78 saw a pole run backwards.
- **NE-SE_CO fails both held-out years**, in opposite directions (2025 too
  high, 2023 too low), so not one simple bias.
- **Wind and solar on 2025** are 16% and 20% above ONS. The model curtails
  only for congestion; ONS's 2025 curtailment was mostly energy surplus.

## Next PR needs

Nothing changed after seeing these numbers. Candidates, each to be
pre-registered before a run on a year not used to choose it (2022 is
still untouched): how ONS operates Belo Monte's poles; curtailment for
energy surplus (ADR-0025's switch failed on 2023 for another reason).
