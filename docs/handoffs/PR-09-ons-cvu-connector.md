<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-09 — ONS CVU (thermal variable cost) connector

**Landed**

- `rules/fetch.smk::fetch_ons_cvu_usina_termica` — year-wildcarded like
  `curva_carga` (one file per year, 2005 onward at a stable URL), reusing
  `scripts/fetch.py`/`scripts/fetch_dataset.py` unchanged.
- `docs/data-dictionary/ons/cvu_usina_termica.yaml` — real dictionary from
  the real 4881-row 2024 file, descriptions from ONS's own dictionary JSON
  (which does give the unit, R$/MWh, explicitly this time — no `id_ons`-style
  mismatch here), plus verified findings not in ONS's documentation.
- `test/fixtures/ons/cvu_usina_termica_sample.csv` — 12 real rows: a handful
  of plants across all four subsystems including zero-CVU ones, plus the
  same plant (`GERAMAR1`) in two different weeks at two different costs, to
  exercise "CVU is genuinely time-varying" rather than assume it.
- 9 new tests (107 total).

**This PR stops at fetch + dictionary**, same shape as PR-04 and PR-07.
Turning this into `marginal_cost` on the T0 network's thermal generators —
deciding how to reduce 52 weeks × 114 plants down to whatever a
subsystem-level aggregate generator needs — is its own PR (PR-10).

**Key files:** `docs/data-dictionary/ons/cvu_usina_termica.yaml`,
`rules/fetch.smk`.

**Data dictionaries added:** `docs/data-dictionary/ons/cvu_usina_termica.yaml`.

**Verified against reality, not just asserted:**

- Fetched via the actual Snakemake rule; sha256 matched an earlier direct
  download byte-for-byte (fourth time this project has confirmed a stable
  ONS dataset fetches deterministically, after PR-04/06/07).
- Read the real weekly series for one real plant (`GERAMAR1`) end to end
  rather than assuming CVU was roughly static: it ranges 983–1198 R$/MWh
  across 2024's 52 weeks, tracking real fuel-cost movement. This is now the
  fixture's second-most-important property (after the zero-cost rows) and
  is asserted directly in `test_data_dictionaries.py`.
- Confirmed `cod_usinaplanejamento`/`nom_usina` in this dataset do **not**
  match `capacidade_geracao`'s CEG codes or plant-name spelling, by
  comparing real sample values side by side — not assumed from the field
  names alone. This is exactly the "plant names differ between registries"
  trap `docs/handoffs/PR-02-workflow-skeleton.md` and
  `docs/handoffs/README.md` both warned about in the abstract; now there's a
  concrete instance of it on record.
- Subsystem mean CVU (2024, nonzero plants): N 346, S 517, SE 650, NE 754
  R$/MWh — NE and SE running the costliest thermal fleets on average is
  directionally consistent with PRIMER §2.1, treated here as a sanity check,
  not a validated result.

**Gotchas**

1. **This dataset's plant identity does not join to `capacidade_geracao`'s.**
   Different ID scheme (`cod_usinaplanejamento`, small integers, vs ANEEL's
   CEG codes) and different name spelling/abbreviation (`GERAMAR1` here vs
   whatever `capacidade_geracao`'s ANEEL-derived `nom_usina` says). **PR-10
   should not attempt a per-plant join** — see Next PR needs.
2. **CVU is per-week, not static** — 52 distinct values per plant per year is
   real signal, not noise (see GERAMAR1 above). A build step that reduces
   this to a single number per subsystem is a genuine simplification and
   should say so explicitly, not present a mean as if it were the actual
   cost.
3. **854 of 4881 rows have `val_cvu = 0.0`.** Real zero-cost plants (some
   biomass/bagasse co-generation, or synchronous-condenser-mode units), not
   missing data — confirmed no nulls exist in the column at all
   (`isna().sum() == 0`). A build step must not treat zero as "no data
   available" and drop or impute it.
4. **ONS's dictionary JSON was accurate this time** (unlike
   `capacidade_geracao`'s `id_ons` mismatch in PR-07) — no fields listed that
   aren't in the CSV, and the unit is stated explicitly. Not every ONS
   dataset has documentation quality issues; worth not over-generalizing
   from PR-07's finding.

**Dead ends**

None. The CKAN slug (`cvu-usitermica`) matched on the first `package_list`
search this time — the PRIMER §2.2 table names this dataset directly
("ONS *CVU das Usinas Térmicas*"), which made searching faster than PR-04's
or PR-07's guess-then-search process.

**Next PR needs (PR-10: attach thermal marginal cost)**

- **Do not join by plant.** Aggregate this dataset to a single representative
  CVU per subsystem (a capacity-weighted or simple mean/median across
  thermal plants, across the year or a chosen reference week — pick one and
  say why) and apply it as `marginal_cost` on the existing `{subsystem}
  thermal` aggregate generator from PR-08. This sidesteps the plant-matching
  problem in Gotcha 1 entirely, at the cost of losing per-plant merit order
  within a subsystem's thermal fleet — an explicit, documented T0
  simplification, not an oversight.
- Hydro still needs a `marginal_cost` too (currently unset / defaults to 0),
  or `n.optimize()` will dispatch hydro and thermal on an arbitrary tie
  rather than hydro-first. PR-08's handoff already flagged treating hydro as
  free/must-run as the pragmatic T0 interim — PR-10 should make that
  decision explicit in code (e.g. a deliberately-low but nonzero
  `marginal_cost`, or `p_min_pu`/must-run treatment) rather than leaving it
  as an accidental default of 0.
- Nuclear and renewables (wind/solar) also default to `marginal_cost = 0`
  currently, which is roughly right for renewables (near-zero true marginal
  cost) but worth stating as a deliberate choice, not silence, in whatever
  PR finally makes `n.optimize()` callable.
- Wildcarding the CVU-and-demand-and-capacity fetch/build rules over
  multiple years (rather than a single reference year) is not needed yet —
  `snapshot_years(config)` already handles it if `config.snapshots` ever
  spans more than 2024, and this connector already reuses that helper.

**Open questions**

- Still open from PR-06/PR-08: isolated systems (Roraima).
- Whether CVU should eventually become genuinely time-varying
  (`marginal_cost_t` per snapshot, since PyPSA supports this) rather than a
  single reduced value, once `n.optimize()` exists and validation against
  observed CMO starts to matter. Deferred past PR-10; premature before a
  solver is even attached.
