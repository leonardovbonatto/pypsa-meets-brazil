<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-18 — Hydro backcast profile + first ballpark check

**Landed**

- `scripts/build_hydro_availability.py` — hourly hydro `p_max_pu` per
  subsystem from ONS observed generation (ADR-0007), with the modalidade
  filter that keeps the numerator's plant population matched to
  `capacidade_geracao`'s. **Raises rather than clips** if any ratio exceeds
  1.0, since that would mean the population assumption broke.
- `rules/build.smk::build_hydro_availability_t0`; `build_network_t0` gains a
  sixth input, and `build_network.py` concatenates the wind/solar and hydro
  profiles before `attach_availability()` — no network-side change needed.
- `KNOWN_LIMITATIONS` rewritten to lead with the backcast caveat, as
  ADR-0007 obliges.
- 10 new tests (201 total).

**The model is no longer economically degenerate.** `all_prices_zero`
flipped to `false` — the pass/fail signal PR-16 added specifically for this.

| | before (PR-15) | after (PR-18) |
|---|---|---|
| thermal dispatch | **0.0 MW** | 13,081.6 MW |
| objective | **0 R$** | 49.4 bn R$ |
| marginal price | **0 everywhere** | 591–712 R$/MWh |
| load shedding | 0 | 146,563 MWh |

## The ballpark check

Model dispatch vs ONS observed 2024 generation, mean MW:

| carrier | model | observed | ratio | is this evidence? |
|---|---|---|---|---|
| hydro | 46,067 | 48,760 | 0.94 | **no** — bounded by observed input |
| wind | 12,972 | 12,238 | 1.06 | **weak** — bounded by measured CF |
| solar | 4,816 | 8,360 | 0.58 | **weak** — same |
| nuclear | 1,990 | 1,791 | 1.11 | no — must-run at nameplate |
| **thermal** | **13,082** | **8,161** | **1.60** | **yes — genuine model output** |
| load shedding | 17 | 0 | — | diagnostic |
| **total** | **78,943** | **79,310** | **1.00** | energy balance |

**Verdict: the right order of magnitude, with a structural bias that has an
identified cause — not a mystery.**

- **Total generation matches to 0.5%**, which is the basic sanity check
  passing: the energy balance closes against real demand.
- **Thermal is 60% too high**, and that is the number this configuration
  legitimately produces.
- **Solar is 42% too low**, and this is very likely the direct cause. Brazil's
  observed solar (8,360 MW mean) is dominated by **MMGD / distributed
  generation**, which `capacidade_geracao` does not cover — the model only
  has ~21 GW of ONS-dispatched solar capacity. Observed solar from dispatched
  plants alone is 26 MW. The model is missing tens of GW of real solar, and
  since demand must still be met, thermal fills the gap.
- Hydro also runs ~6% below observed for the same reason (the model's hydro
  is the filtered, dispatched-only subset).

Solar shortfall (3,544 MW) plus hydro shortfall (2,693 MW) ≈ 6,237 MW; the
thermal excess is 4,921 MW. The arithmetic is consistent with "thermal is
covering what the missing distributed generation really supplied".

**This is a useful result.** It says the dispatch machinery, merit order,
interchange and pricing all behave sensibly, and it identifies MMGD as the
largest remaining structural gap — which the roadmap already scopes (Epic 8,
`Brazilian-Grid-in-PyPSA.md` §7 Track 1) but had not previously been shown to
matter quantitatively.

**It is not validation.** Per ADR-0007: hydro dispatch is a model input, so
comparing prices to observed CMO would be partly circular. Nothing here
should be presented as the model predicting anything.

**Verified against reality, not just asserted:**

Every number above was computed from the real 12-month datasets — the
observed mix by aggregating all 6.1M rows of `geracao_usina`, the model mix
off the solved network — not read from the summary or inferred.

**Gotchas**

1. **`Conjunto de Usinas` had to be added to the modalidade filter, and
   finding out why mattered.** The first version used only `TIPO
   I/II-A/II-B/II-C`, following `capacidade_geracao`'s own modalidade
   values. But `geracao_usina` reports most Tipo II-C plants under the
   *aggregation's* name, `Conjunto de Usinas`, instead. Excluding it drops
   real generation from the numerator while its capacity stays in the
   denominator. For hydro the effect is small (S +0.8%, SE_CO +0.5% — only
   59 of 819 hydro plants are Tipo II-C) but for **wind and solar it is
   dominant** (2,104 of 2,152 wind plants; 1,179 of 1,189 solar). Caught
   because the ballpark check's "dispatched only" column showed wind at 185
   MW and solar at 26 MW — obviously wrong, which pointed straight at the
   filter. Fixed before committing.
2. **The same trap will bite any future non-hydro use of this dataset**,
   much harder. The constant carries a comment saying so.
3. **`observed_dispatched_only` is a misleading comparison basis** for
   wind/solar even after the fix, because those columns in the check script
   use a stricter filter than the model does. The all-plants column is the
   honest basis; kept both in the analysis only to make the MMGD gap visible.

**Dead ends**

None, though the first ballpark run was interpreted before the filter bug
was found. The numbers changed only slightly (thermal 13,295 → 13,082, 1.63x
→ 1.60x), so the conclusion held — but that was luck, not method. The lesson
is that a comparison table with an obviously-impossible cell (wind at 185 MW
nationally) is itself a signal worth chasing before reading anything else in
the table.

**Next PR needs**

Per the user's plan, **option (a) — real water values — is now the main
line**. This PR was the ballpark check that decision was waiting on, and it
passed: the machinery works, so the SDDP investment is against a
functioning pipeline rather than a hypothetical.

- **An ADR for the water-value approach before implementation.** PAR(p)
  inflow model → SDDP.jl → Benders cuts → linopy coupling is a multi-PR
  epic with several consequential choices (REE vs individualized reservoirs,
  risk measure and λ/α, cut storage format, how many stages).
- Needs `inewave` for `hidr.dat` and `VAZOES.DAT`, and Julia + SDDP.jl as a
  separate Snakemake stage exchanging Parquet (PRIMER §4.5, §5.10). Both are
  new dependency classes for this project.
- **MMGD is now a quantified gap, not just a listed one** (~3.5 GW mean of
  missing solar, driving a 60% thermal overshoot). Cheaper than SDDP and
  would materially improve the ballpark. Worth considering before or
  alongside the water-value epic, per roadmap Epic 8.
- When water values land, `KNOWN_LIMITATIONS`' backcast entry must be
  replaced, and ADR-0007 marked superseded — it names its own expected
  successor for exactly this reason.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether the ~6% hydro shortfall vs observed should be closed by widening
  the capacity denominator (including small hydro) rather than narrowing the
  generation numerator. Both are defensible; the current choice keeps the
  model's plant population internally consistent, which matters more.
- Load shedding is now nonzero (146,563 MWh/yr, 0.02% of demand). Small, but
  it was zero before — worth checking whether it concentrates in specific
  hours/subsystems once anything downstream depends on it.
