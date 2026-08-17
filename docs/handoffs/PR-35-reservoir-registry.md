<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-35 — Reservoir registry connector (ADR-0008 stage 2, part 1)

**Landed:**

- `rules/fetch.smk::fetch_ons_reservatorio` + `config.default.yaml`'s
  `sources.ons.reservatorio` entry - single current snapshot, like
  `capacidade_geracao`.
- `docs/data-dictionary/ons/reservatorio.yaml` - all 24 real columns
  documented, 162 rows.
- `rules/build.smk::build_reservoir_registry` + `scripts/build_reservoir_registry.py`
  - tidy registry + the REE-to-subsystem mapping.
- `test/test_build_reservoir_registry.py` (9 tests), `test/fixtures/ons/reservatorio_sample.csv`.

Split from the `ena_ree`/`ear_ree` connectors ADR-0008 asked for
("go for the REE connectors"): this piece turned out to be independently
significant enough - both for resolving ADR-0008's own named open
question and for a much bigger finding about the epic's eventual
per-plant stage - to land on its own rather than be a preliminary step
buried inside a larger PR.

## What this resolves from ADR-0008

ADR-0008 named the REE-to-subsystem mapping as unconfirmed - "the 12 REE
names are recognizable by domain knowledge... but this is inference, not
a confirmed join key." Found something better while looking for it:
`dataset/reservatorio/RESERVATORIOS.csv`, a real per-reservoir registry
with `id_subsistema` and `nom_ree` on the same row for all 162
reservoirs. Joining them gives a clean, unambiguous 1:1 mapping - now
enforced in code (`build_ree_subsystem_map()` raises if any REE ever
maps to more than one subsystem), not just asserted in a docstring.

**This corrected a real guess from ADR-0008's own drafting**: I inferred
MADEIRA and TELES PIRES (Amazon-basin river names) would map to
subsystem N, going by geography. Checked against the real data instead
of trusting the inference - both actually map to **SE_CO**. Worth
naming plainly: the guess would have been wrong, and ADR-0008 explicitly
said not to trust it without checking - this is that check working as
intended, not a near-miss to be embarrassed about.

## A bigger finding than this PR set out to make

162 reservoirs - matches PRIMER §2.1's own "order 100-170" estimate for
individualized reservoirs almost exactly, a real cross-check that this
is the right population.

More significant: ONS's own dictionary for `val_perda` (head loss) says
plainly, "Estes valores sao os mesmos utilizados pelo programa Newave"
- these are the *same values NEWAVE itself uses*. Combined with this
dataset already covering volume, elevation, and productivity - exactly
the physical characteristics PRIMER and ADR-0008 assumed would require
parsing `hidr.dat` out of NEWAVE decks via `inewave` - this may mean
**full per-plant individualization does not need deck parsing at all**
for the physical cadastre. That was ADR-0008's single biggest named
unknown ("deck access has never been checked in this project").

**Not claimed as resolved, on purpose.** This dataset is real and
overlaps heavily with what `hidr.dat` provides, but nothing here has
checked what, if anything, it's missing relative to the real deck data -
cascade routing/travel-time between upstream and downstream reservoirs
is not obviously present in this file, and PAR(p) inflow fitting at
per-plant resolution still needs an inflow series this dataset doesn't
provide (ENA/EAR only go to REE level so far). Recorded as a real,
significant lead for whichever future ADR takes up full per-plant
individualization - that ADR should investigate this specifically before
assuming deck parsing is required, but this PR does not decide that
question itself.

## Design choices worth knowing

- **Two outputs, not one** - `reservoir_registry.csv` (full 24-column
  tidy table, useful for the future per-plant stage) and
  `ree_subsystem_map.csv` (just the 12-row mapping `ena_ree`/`ear_ree`
  actually need). Same reasoning as PR-30's history/capacity split: every
  consumer of the mapping shouldn't have to re-derive it from the full
  registry.
- **The 1:1 invariant is enforced, not just documented.**
  `build_ree_subsystem_map()` raises if it's ever violated - checked
  directly with a test that deliberately breaks it
  (`test_raises_when_a_ree_maps_to_two_subsystems`), the same discipline
  as PR-27's storable-vs-gross check and PR-30's capacity-vs-verified
  check.
- **Single-snapshot fetch, not year-wildcarded** - this is a registry
  (current state), not a time series, matching `capacidade_geracao`'s
  shape rather than `ena_subsistema`'s.

## Gotchas

- `nom_subsistema` here spells SE_CO as "SUDESTE/CENTRO-OESTE", not the
  plain "SUDESTE" other ONS datasets use - doesn't affect the pipeline
  (`id_subsistema`/"SE" is the real join key), but would confuse anyone
  cross-referencing subsystem names by eye across datasets.
- The `_scratch_cut_fixture.py` script used to build the test fixture hit
  the same `groupby().apply(..., include_groups=True)` error already
  documented in this project's history - fixed with the established
  `sort_values().groupby().head()` pattern, not `apply()`, on the first
  retry.
- Same `python -c` inline-quoting issue as every prior PR - all
  exploratory checks used scratch `.py` files, including the fixture-cutting
  one (a bash `awk` one-liner failed through the
  `PowerShell → wsl.exe -lc` chain first).

## Next PR needs

**`ena_ree` and `ear_ree` connectors** (ADR-0008's originally-requested
scope), using this PR's real mapping to attach a `subsystem` column -
same fetch → dictionary → tidy shape as every ONS connector so far.
Investigate the negative `ear_verif_ree_mwmes` value found for MADEIRA
(ADR-0008's other named open question) as part of that PR, with the full
volume rather than the single sample row that first surfaced it.

## Open questions

- Whether `RESERVATORIOS.csv` substitutes for `hidr.dat` well enough to
  skip deck parsing for the eventual full per-plant individualization ADR
  - a real, promising lead, not yet investigated to a decision.
- Whether cascade routing (which reservoirs feed which downstream) is
  derivable from `nom_bacia`/`nom_rio` alone or needs a separate source -
  unresearched.
