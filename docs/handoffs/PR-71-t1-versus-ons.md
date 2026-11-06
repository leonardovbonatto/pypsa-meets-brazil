<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-71 — T1 against ONS, reported as post hoc

`check_t1_gate`'s report gains a `post_hoc` section: ADR-0020's generation
check (national wind, utility solar, nuclear, thermal within 5% of ONS)
applied to T1. It was written after PR-70's numbers were seen, so it is
labelled `post_hoc: true`, carries no `passed` key, and the report's
verdict is still ADR-0022's pre-registered one (fails: T1 does not match
T0 within 1%, because T1 curtails and T0 cannot).

## Result

| source | T1 MW | ONS MW | ratio |
|---|---|---|---|
| wind | 12,414 | 12,238 | 1.014 |
| utility solar | 3,243 | 3,234 | 1.003 |
| nuclear | 1,787 | 1,791 | 0.998 |
| thermal | 8,052 | 8,161 | 0.987 |

With PR-70's interchange (all four boundaries within 5% of capacity), T1
meets ADR-0020's whole criterion. Read as: T1 reproduces 2024's energy
balance and interchange; read with: hydro, MMGD, small plants and the
thermal floor are backcasts, and this check was not fixed in advance.

## Next PR needs

- If T1 is to carry a formal gate, a new ADR fixing it before the next
  model change is scored (e.g. 2025 data, or T1 with its own changes).
