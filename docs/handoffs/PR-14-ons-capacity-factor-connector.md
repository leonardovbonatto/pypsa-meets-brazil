<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-14 — ONS capacity factor connector

**Landed**

- `scripts/_common.py::snapshot_year_months()` — the month-level analogue of
  `snapshot_years()`, since this dataset is split by (year, month), not just
  year. Exported via `rules/common.smk` alongside `snapshot_years`.
- `rules/fetch.smk::fetch_ons_fator_capacidade` — wildcarded over both
  `{year}` and `{month}`, reusing `scripts/fetch.py` unchanged. `fetch_all`
  now expands `snapshot_year_months(config)` into 12 explicit target paths
  for 2024 (a list comprehension, not `expand()`, since year and month are
  paired, not an independent cross-product).
- `docs/data-dictionary/ons/fator_capacidade.yaml` — real dictionary from
  the real January 2024 file.
- `test/fixtures/ons/fator_capacidade_sample.csv` — 28 real rows covering
  every real `(subsystem, technology)` combination actually present, plus a
  real `val_fatorcapacidade > 1.0` row.
- 9 new tests (163 total).
- **Fetched all 12 months of 2024 for real** (445 MB total, ~90s), not just
  enough to prove the mechanism — PR-15 (which builds the actual
  availability profile) needs the whole year, and there was no reason to
  make that PR re-download what this one already proved works.

**This PR stops at fetch + dictionary**, matching the PR-04/07/09/12 shape.
Aggregating this into per-`(subsystem, technology)` hourly `p_max_pu` and
attaching it to the T0 network is PR-15.

**Key files:** `docs/data-dictionary/ons/fator_capacidade.yaml`,
`scripts/_common.py`.

**Data dictionaries added:** `docs/data-dictionary/ons/fator_capacidade.yaml`.

**Why this dataset instead of atlite/ERA5**, since the PR-13 handoff named
atlite as the "next PR needs": **checked, not assumed** — `~/.cdsapirc`
(the Copernicus CDS API credential atlite needs to download ERA5) does not
exist in this environment, and activating it needs the user's university
network, the same category of blocker that deferred Gurobi. Rather than stop
and wait, searched ONS's own catalogue for what PRIMER §2.5 already flagged
as available: "Wind/solar realized capacity factors 🟢". Found it
(`fator-capacidade-2`) on the first search. It measures exactly what
`p_max_pu` needs — realized generation ÷ installed capacity, hourly, per
plant-group — directly, with no weather-model inference or bias-correction
step required. atlite/ERA5 stays `PLANNED` in `docs/STACK.md`, unchanged;
this is a substitution using real data already available, not a lesser
workaround.

**Verified against reality, not just asserted:**

- Fetched via the actual Snakemake rule for all 12 months; January's sha256
  matched an earlier direct download byte-for-byte (sixth confirmation of
  deterministic ONS fetches this project, after PR-04/06/07/09/12).
- **Checked the `SE_CO`-wind gap in two different months, not assumed from
  one.** January 2024 has zero `Eólica` rows for subsystem `SE`; downloaded
  and checked July 2024 independently — also zero. This is a real,
  persistent property of the dataset (this specific ~261 MW of `SE_CO` wind
  capacity is apparently not tracked as ONS-dispatched by this dataset), not
  a one-month anomaly, and it's now asserted directly in
  `test_fixture_covers_every_real_subsystem_technology_combination`.
- Confirmed `val_fatorcapacidade` occasionally exceeds 1.0 by inspecting the
  real distribution (35 of 153,528 January rows, max ≈1.02) rather than
  trusting the field definition alone — real measurement/rounding noise at
  the nameplate boundary, which a `p_max_pu` consumer must clip.
- Confirmed via the real dictionary JSON that, unlike `capacidade_geracao`
  (PR-07) and `intercambio_nacional` (PR-12), this dataset's documented
  fields match its real CSV columns exactly — no phantom-field mismatch
  this time. Worth checking every time, not assuming either way.

**Gotchas**

1. **This dataset is an order of magnitude larger than every previous
   connector**: ~37-40 MB/month vs. 0.4-1.7 MB for a whole year of
   `curva_carga`/`cvu_usina_termica`/`intercambio_nacional`. 445 MB for the
   full 2024 year. Fetched fine (~90s for all 12 months in parallel with
   `-j4`), but worth knowing before assuming every ONS dataset is
   curva_carga-sized.
2. **Month-splitting only applies from 2022 onward** — 2009-2021 is
   published one file per year, per the dataset's own notes. Not relevant to
   this project's 2024 reference year, but a trap for anyone later extending
   `snapshots.start` before 2022: `fetch_ons_fator_capacidade`'s URL pattern
   would silently 404 or need a different rule for those years.
3. **No plant-identity join to `capacidade_geracao` or `cvu_usina_termica`**
   — `nom_usina_conjunto`/`id_ons`/`ceg` here are this dataset's own scheme,
   consistent with the cross-dataset ID mismatch already documented in the
   PR-09 handoff. PR-15 should aggregate by `(subsystem, technology)`
   exactly as `build_generators.py` and `build_costs.py` already do, not
   attempt a per-plant join.

**Dead ends**

None. `fator-capacidade-2` matched on the first CKAN search
(`fator` as the term) — PRIMER §2.5 already named the dataset in the
abstract, so, like PR-12, this was confirmation rather than a blind search.

**Next PR needs (PR-15: T0 availability profile)**

- `scripts/build_availability.py`: for each `(subsystem, technology)` pair
  that exists in `build_generators.py`'s output, compute an hourly
  capacity-weighted mean `val_fatorcapacidade` across that pair's real
  plant-groups, clipped to `[0, 1]`. Output shape: wide, `(snapshot,
  {subsystem}_{technology})` columns, or long `(snapshot, subsystem,
  carrier, p_max_pu)` — pick whichever pivots more naturally into
  `n.generators_t.p_max_pu`, mirroring how `build_network.wide_demand()`
  already does this for loads.
- **`SE_CO wind` has no data to build a profile from** (see Gotchas). Decide
  explicitly rather than let it default silently: leaving it at 1.0
  (today's implicit behaviour) is defensible given it's ~261 MW of 83,792 MW
  installed in `SE_CO` (0.3%), but say so in code, not just here.
- Hydro is **not** covered by this dataset at all (it is wind/solar only,
  per the dataset's own description) and should not be — hydro's real
  constraint is water availability, not a weather-derived capacity factor;
  that stays PRIMER §4/SDDP.jl territory, unrelated to this PR.
- After attaching `p_max_pu`, re-solve and check whether thermal dispatch
  becomes nonzero again somewhere — PR-13's finding was that free capacity
  exceeds demand *assuming 100% renewable availability*; real (lower)
  wind/solar output should let thermal (and possibly load-shedding, in a
  low-wind hour) become economically relevant again in at least some hours.
  Verify this rather than assume it.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether `nom_localizacao` (only populated for Northeast plants, per ONS's
  own field description) or the lat/lon columns are worth anything for T0
  — probably not, since T0 is subsystem-level, not nodal, but noting they
  exist in case a future T1+/T3 PR wants plant siting information from this
  same dataset rather than fetching it separately.
