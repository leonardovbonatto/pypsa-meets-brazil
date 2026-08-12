<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-02 — Environment and workflow skeleton

**Landed**

- `pixi.toml` pinned to Python 3.12, environments `default` and `dev` sharing one
  solve group. Verified: Python 3.12.13, Snakemake 9.25.1.
- `Snakefile` + `rules/common.smk` + `scripts/write_manifest.py` — one real rule
  (`write_run_manifest`) that emits the ADR-0001 §4 run manifest.
- `config/config.default.yaml` and `config/test/config.smoke.yaml`.
- `.github/workflows/lint.yml` and `test.yml`.
- 13 unit tests, all passing. Smoke workflow runs end to end.

**Key files:** `Snakefile`, `scripts/_common.py`, `scripts/write_manifest.py`.

**Gotchas** — each of these cost real time:

1. **`snakemake-minimal` is on bioconda, not conda-forge.** `pixi install` fails with
   "No candidates were found" until bioconda is added to `channels`. conda-forge
   stays first so it wins for everything else.

2. **Snakemake `script:` files must not use `from __future__ import ...`.**
   Snakemake prepends a preamble to inject the `snakemake` object, which pushes the
   future import out of first position → `SyntaxError`. Unnecessary on 3.12 anyway.
   There is a comment in `write_manifest.py` guarding this.

3. **Editing WSL files from Windows via `\\wsl.localhost\...` creates root-owned
   files.** They are readable but not writable by the normal user, so pre-commit
   fails with `PermissionError`. Fixed once with `sudo chown -R`. **Write files from
   inside WSL**, not through the UNC path.

4. **`pre-commit run --all-files` only sees git-tracked files.** Untracked new code
   shows as "no files to check" — which reads like a pass. `git add` first.

5. **Recent ruff formats Python code blocks embedded in Markdown.** It rewrote an
   example in `docs/PRIMER.md`. `*.md` is now in `extend-exclude`.

6. **REUSE needs the licence text present, not just referenced.** `LICENSES/` must
   contain every identifier actually used. `reuse` is not in the dev environment
   (it lives in pre-commit's venv), so `LICENSES/CC-BY-4.0.txt` was fetched from the
   SPDX license-list-data repo. Add `ODbL-1.0.txt` only when OSM-derived output
   actually appears — REUSE flags unused licences.

7. **codespell false-positives on sector vocabulary** — `ANEEL` → "ANNEAL",
   `esy` → "easy". `.codespellignore` handles these; expect more Portuguese terms
   to need adding as data connectors land.

**Dead ends**

- Putting `config_hash`/`run_id` in `rules/common.smk` — Python cannot import `.smk`,
  so they were untestable. Logic now lives in `scripts/_common.py`, with the `.smk`
  file only re-exporting into the workflow namespace. Follow this pattern: rule files
  hold rules, modules hold logic.

**Next PR needs (PR-03: fetch/provenance/schema core)**

- `resources/_provenance/` is already read by `write_manifest.collect_provenance()`
  and embedded into the manifest — PR-03 only needs to *write* records there in the
  documented shape.
- `_inspect.py` must emit the data-dictionary YAML described in
  `docs/data-dictionary/README.md`, filling `unit` and `notes` by hand after
  inspection. Those two fields cause the most real bugs and cannot be inferred.
- Add `requests` (or `httpx`) and `pandera` to `pixi.toml` at that point.

**Open questions**

- `meta.yml` (changelog-entry check, provenance schema validation, ADR numbering) is
  specified in the plan but not yet written. Fold into PR-03.
- CI has not run yet — the workflows are unverified against real Actions runners.
