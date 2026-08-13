<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-07 — ONS installed-capacity connector

**Landed**

- `rules/fetch.smk::fetch_ons_capacidade_geracao` — a second connector,
  reusing `scripts/fetch.py`/`scripts/fetch_dataset.py` unchanged. Unlike
  `curva_carga`, this dataset is a single current file, not year-split, so
  the rule carries no wildcard.
- `docs/data-dictionary/ons/capacidade_geracao.yaml` — real dictionary from
  the real 5631-row file, descriptions taken from ONS's own published
  dictionary JSON, plus verified findings (below) that aren't in ONS's
  documentation at all.
- `test/fixtures/ons/capacidade_geracao_sample.csv` — 17 real rows: one per
  (subsystem, technology) combination actually present, plus one real
  decommissioned unit and the `PY` edge case (see Gotchas). Real bytes, not
  synthesised.
- 8 new tests (80 total), extending `test_data_dictionaries.py`'s existing
  parametrized-over-all-dictionaries checks to this one automatically.

**This PR deliberately stops at fetch + dictionary.** Turning this into
per-subsystem generator capacity for the PyPSA network — aggregation,
technology mapping, the `PY` exclusion decision, attaching to
`resources/networks/t0.nc` — is scoped as its own PR (PR-08) so this one
stays a single concern, matching the PR-04 precedent exactly.

**Key files:** `docs/data-dictionary/ons/capacidade_geracao.yaml`,
`rules/fetch.smk`.

**Data dictionaries added:** `docs/data-dictionary/ons/capacidade_geracao.yaml`.

**Verified against reality, not just asserted:**

- Fetched via the actual Snakemake rule (not just a manual `curl`), and its
  sha256 matched an earlier direct download byte-for-byte — the dataset is
  stable and the fetch is deterministic, same finding as PR-04/06.
- `dat_desativacao` NULL meaning "active" is ONS's own stated convention
  (their dictionary JSON says so explicitly), not an assumption on this
  project's part.
- Read every distinct `id_subsistema` value in the real file rather than
  assuming the four SIN subsystems were the only ones present — found a
  fifth, `PY` (see Gotchas), which would have been silently wrong to miss.
- National active capacity (excluding `PY`) sums to ~192 GW, hydro alone
  ~110 GW — right order of magnitude and shape for Brazil, consistent with
  PRIMER §2.3's "hydro dominates" framing.

**Gotchas**

1. **`id_subsistema` has a fifth value, `PY`, not documented anywhere in
   ONS's own dictionary.** Every `PY` row is the same plant, `ITAIPU 50 HZ`,
   totalling 7.0 GW. This is the Paraguay-frequency (50 Hz) side of the
   binational Itaipu plant — it feeds Paraguay's grid, not Brazil's 60 Hz
   SIN. Brazil's own 60 Hz share of Itaipu is a separate set of rows already
   counted under `SE`. Confirmed by the plant naming itself, not just
   inferred from the code. **Any future code that maps `id_subsistema` onto
   this project's four config subsystems must treat `PY` as
   known-and-excluded, not as unmapped/erroneous data** — raising on it
   would break a legitimate fetch; silently including it would double-count
   or misattribute 7 GW.
2. **ONS's own dictionary JSON lists a field, `id_ons`, that is not actually
   a column in the CSV.** Their documentation and their data disagree. Built
   the schema from the real CSV columns as always (`_inspect.py` samples the
   actual file, never the dictionary text) — worth knowing this kind of
   mismatch exists in ONS's own metadata, not just in the data itself.
3. **This dataset is unit-generator granularity** (one row per turbine/unit,
   not per plant) — a single `usina` like XINGO has multiple rows. Any
   aggregation (PR-08) needs to sum, not count rows, and needs to group by
   plant or subsystem+technology deliberately rather than assume one row
   equals one plant.

**Dead ends**

- Guessed dataset slugs before searching properly (`geracao-usina-2` looked
  plausible for capacity but is actually hourly generation output, a
  different dataset entirely). Went back to the CKAN `package_list` search
  and matched by name/notes rather than guessing further — same lesson as
  PR-04's dead ends, worth repeating: always search, never guess a slug.

**Next PR needs (PR-08: T0 generator capacity)**

- Aggregate `capacidade_geracao` to `(subsystem, technology)` using
  `nom_tipousina` (5 clean categories: hydro/wind/solar/thermal/nuclear) —
  not `nom_combustivel` (13 fuel-level categories), which is finer than this
  PR's scope needs and is really about marginal cost, not capacity/topology.
- Filter `dat_desativacao.isna()` before aggregating (decommissioned units
  must not count toward installed capacity).
- Exclude `PY` explicitly and by name, with the reasoning from Gotcha 1
  carried into the code as a comment, not just this handoff.
- The `SUBSYSTEM_MAP` (`SE` → `SE_CO` etc.) already exists in
  `scripts/build_demand.py` — factor it out to a shared module
  (`scripts/_ons.py` or similar) rather than duplicating it, since this PR
  needs the exact same mapping.
- No marginal cost, no availability profile (`p_max_pu`) in that PR either —
  those need CVU (thermal) and atlite/ERA5 (renewables), both still
  `PLANNED` in `docs/STACK.md`. Capacity and topology only; `n.optimize()`
  still won't be callable after PR-08.

**Open questions**

- None carried over beyond what's already in PR-06's handoff (the isolated
  systems / Roraima question, still undecided).
