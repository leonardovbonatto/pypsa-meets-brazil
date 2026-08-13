<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-04 — ONS load connector

**Landed**

- `rules/fetch.smk` with `fetch_ons_curva_carga`, wildcarded over `{year}`, plus
  `scripts/fetch_dataset.py` as the thin Snakemake entry point onto `fetch.py`.
- `sources:` block in `config/config.default.yaml` holding the URL template and
  the years to fetch.
- `fetch_all` target in the `Snakefile`, **deliberately not an input of `all`**.
  Fetch rules touch the network; `all` and the smoke config must stay runnable
  offline. Verified: the default and smoke DAGs contain no fetch job.
- `docs/data-dictionary/ons/curva_carga.yaml` — first real dictionary.
- `test/test_data_dictionaries.py` — 7 tests, including that the committed
  dictionary's pandera schema validates a real committed slice of the data.
- `_inspect.py` gained a CLI.

**Key files:** `rules/fetch.smk`, `docs/data-dictionary/ons/curva_carga.yaml`,
`scripts/fetch_dataset.py`.

**Data dictionaries added:** `docs/data-dictionary/ons/curva_carga.yaml`.

**The dataset.** ONS *Curva de Carga* — hourly verified load, per subsystem, one
CSV per calendar year from 2000, at a stable URL:
`https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/curva-carga-ho/CURVA_CARGA_{year}.csv`.
Also published as XLSX and PARQUET. CC-BY. Discovered via the portal's CKAN API
(`https://dados.ons.org.br/api/3/action/package_list` and `package_show?id=curva-carga`) —
that API is the reliable way to find real slugs and resource URLs, and it is far
cheaper than scraping the portal. Note the *dataset* slug is `curva-carga` while
its S3 prefix is `curva-carga-ho`; they do not match, so do not infer one from
the other.

**What was verified against reality, not just asserted:**

- 2024 has 35,136 rows = 4 subsystems x 8784 h (366-day leap year), and 8784
  distinct timestamps with all four subsystems present at each. No gaps, no
  duplicates.
- Timestamps are Brasilia local time (UTC-3). Established empirically: mean SIN
  load peaks at 19h and troughs at 04h. Under UTC the peak would sit at 22h.
- Mean SIN load across 2024 is ~78,900 MWmed, i.e. ~693 TWh for the year, which
  is the right order of magnitude for Brazil.
- Running the Snakemake rule reproduced the sha256 of the earlier manual fetch
  byte-for-byte, and the run manifest now embeds that provenance record — the
  fetch -> provenance -> manifest chain from PR-02/PR-03 is closed and working.

**Gotchas**

1. **`SE` is not `SE_CO`.** ONS labels the subsystem `SE` / `SUDESTE`, but it is
   the combined Southeast/Centre-West subsystem, which `config.default.yaml`
   calls `SE_CO`. A build step must map `id_subsistema` onto the config labels;
   joining on the raw code will silently drop the largest subsystem in Brazil.
   **This mapping is deliberately not implemented here** — see "Next PR needs".
2. **Hand-writing the dictionary YAML produced invalid YAML.** A description
   containing `2024: N, NE, ...` parsed as a nested mapping. The tests caught it.
   Fill in `description`/`notes` by building the dict in Python and dumping via
   `_inspect.write_dictionary()`, not by editing the file inline.
3. **Regenerating a dictionary destroys the hand-written prose.** `_inspect.py`
   emits `unit`/`description` as null and `notes` as empty by design, so a
   straight regeneration on the next fetch wipes exactly the fields that matter
   most. Right now the only defence is the test that fails if they are empty.
   A merge-preserving regeneration mode is worth a small PR.
4. **`schema_hash` is pandas-major-version sensitive.** Under pandas 3.0.5,
   string columns report dtype `str`; pandas 2.x reported `object`. So the
   committed hash tracks the environment as well as upstream. `pixi.lock` pins
   pandas, so this is contained — but on a pandas upgrade expect every
   `schema_hash` to change and re-verify rather than assuming upstream drift.
5. **`pandera` is imported as `pandera.pandas`** in the 0.32 line.
6. **No PDF tooling in the environment.** ONS ships the authoritative field
   definitions as a PDF, but also as JSON at the same S3 prefix
   (`DicionarioDados_CurvaCarga.json`) — that JSON is not listed as a CKAN
   resource for this dataset, but it exists. Try the `.json` sibling before
   reaching for a PDF parser.
7. **Licensing:** committed ONS-derived files are now attributed to ONS in
   `REUSE.toml`, not to this project. CC-BY's actual requirement is attribution,
   so claiming our own copyright over their bytes was wrong. CKAN reports the
   licence as generic `cc-by` (`license_title` "Creative Commons Attribution")
   without a version; we record it as CC-BY-4.0, which is what `LICENSES/`
   carries. If the exact version ever matters legally, confirm it with ONS.

**Dead ends**

- Guessed slugs `curva-carga-ho` and `carga-energia-di` against the CKAN API —
  both 404. Those strings are S3 path segments, not dataset ids. Use
  `package_list` and search it.
- `carga-energia-verificada` looks like the obvious load dataset but exposes
  only a PDF/JSON dictionary and a Swagger API, no bulk CSV. `curva-carga` is
  the one with downloadable per-year files.

**Next PR needs (PR-05: build the T0 load series)**

- Transform `resources/ons/CURVA_CARGA_{year}.csv` into a tidy, model-ready
  artifact indexed by `(snapshot, subsystem)`. This is where the `SE` -> `SE_CO`
  mapping belongs, and it should be an explicit, tested lookup rather than a
  string manipulation.
- Parse `din_instante` explicitly (it arrives as a string) and decide how
  timezone is represented downstream — the data is UTC-3 wall-clock with no DST
  from 2019 on. Recommend keeping it tz-naive local and documenting that, since
  PyPSA snapshots are naive; make that choice deliberately, not by accident.
- Validate the fetched frame against the committed dictionary via
  `_inspect.to_pandera_schema()` at the start of the build step — the machinery
  exists and is tested, but nothing calls it in the workflow yet.
- The config currently fetches only `years: [2024]`. `config.default.yaml`'s
  `snapshots` range is also 2024, so the two need to stay consistent; consider
  deriving the fetch years from the snapshot range instead of listing them.

**Open questions**

- Whether to fetch the PARQUET rather than the CSV. It is ~4x smaller and
  carries dtypes, which removes the string-timestamp parsing step. The CSV was
  chosen here only because the data dictionary's `delimiter`/`decimal` fields
  describe a text format. Worth revisiting before many years are fetched.
- Still no CI run against real GitHub Actions for any workflow (`lint`, `test`,
  `meta`) — unchanged since PR-02.
