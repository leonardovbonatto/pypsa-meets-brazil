<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-03 — Fetch/provenance/schema core

**Landed**

- `scripts/fetch.py` — `download()` streams a URL to disk; `build_record()` +
  `write_record()` produce the `resources/_provenance/<source>/<dataset>.json`
  record `write_manifest.collect_provenance()` already reads. `fetch()` is the
  one call a connector script needs; a small argparse CLI exists for
  standalone/manual fetches.
- `scripts/_inspect.py` — `inspect_csv()` + `build_dictionary()` sample a
  fetched file and produce the dict described in
  `docs/data-dictionary/README.md`. `to_pandera_schema()` turns a committed
  dictionary into a `pandera.DataFrameSchema` (`strict=True`) so a later
  fetch of the same dataset can be validated against it — column drift raises
  `pandera.errors.SchemaError` instead of passing silently downstream.
- `scripts/check_meta.py` + `.github/workflows/meta.yml` — the `meta.yml`
  CI job ADR-0001 promised: changelog-touched check (skippable via the
  `no-changelog` PR label), provenance-record shape validation, ADR filename
  numbering uniqueness.
- `requests` and `pandera` added to `pixi.toml`; `pixi.lock` regenerated.
- 25 new unit tests (42 total), all against fixtures/mocks — no network.

**Key files:** `scripts/fetch.py`, `scripts/_inspect.py`, `scripts/check_meta.py`.

**Data dictionaries added/changed:** none. This PR ships the *tool*, not a
dataset. The first connector PR that calls `_inspect.py` for real is where a
`docs/data-dictionary/<source>/<dataset>.yaml` first lands, with `unit` and
`description` filled in by hand.

**Gotchas** — each of these cost real time:

1. **Default-argument capture bug.** `write_record(..., provenance_dir: Path =
   PROVENANCE_DIR)` binds the module global at *def* time, not call time —
   `monkeypatch.setattr(fetch, "PROVENANCE_DIR", tmp_path)` silently had no
   effect on it. Fixed by defaulting to `None` and resolving `provenance_dir
   or PROVENANCE_DIR` inside the function body, the same pattern
   `write_manifest.collect_provenance()` already used correctly. Watch for
   this pattern anywhere a module-level path constant is meant to be
   test-overridable.
2. **`ruff` disagrees with the `rules/common.smk` precedent on `noqa: E402`.**
   `rules/common.smk` carries `# noqa: E402,F401` after a `sys.path.insert`.
   The identical pattern in `check_meta.py` (importing from `fetch` after
   inserting `scripts/` onto `sys.path`) triggered `RUF100: unused noqa` —
   ruff did not consider that import a real E402 violation here. Removed the
   `E402` half; kept the pattern (path insert, then import) since it is still
   needed for the import to resolve at all when the script is loaded outside
   its own directory (e.g. by `importlib` in tests).
3. **`wsl.exe -e bash -lc "..."` from PowerShell needs single-quoted PS
   strings.** Double-quoted PowerShell strings interpolate `$`, mangling
   `$HOME`/`$PATH` before bash ever sees them. Always wrap the bash command in
   PowerShell single quotes when driving WSL from a Windows-side tool.
4. **`export PATH=... && cmd &` scopes the export to the backgrounded job
   only.** `A=... && long_running_cmd &` backgrounds the whole `&&` chain as
   one job; a PATH change inside it does not survive for whatever comes after
   the `&` in the same `bash -lc` invocation. Use `;` to make the export its
   own top-level statement, then background only the long-running command.
5. **pixi is not the interactive shell's PATH by default even inside WSL**
   (`~/.pixi/bin` isn't sourced in a non-interactive `bash -lc` login shell in
   this environment) — export it explicitly every time.
6. **`pandera` needs `import pandera.pandas as pa`**, not bare `import
   pandera as pa`, for `DataFrameSchema`/`Column` in the pinned `>=0.20` line.

**Dead ends**

- Tried mapping pandas dtype strings to pandera type aliases
  (`_DTYPE_TO_PANDERA = {"int64": pa.Int64, ...}`) in `to_pandera_schema()`.
  Unnecessary: `pa.Column("int64", ...)` accepts the pandas dtype string
  directly, which is also what `str(series.dtype)` already produces — one
  fewer thing to keep in sync as dtypes are added.

**Next PR needs (first real data connector, e.g. ONS `carga_verificada`)**

- Call `fetch.fetch()` for the real URL, then `_inspect.inspect_csv()` +
  `_inspect.build_dictionary()` + `_inspect.write_dictionary()` to produce
  `docs/data-dictionary/ons/carga_energia_verificada.yaml` — fill `unit` and
  `description` by hand per column before committing.
- No Snakemake rule wraps `fetch.py` yet — this PR deliberately left it as a
  library + CLI since there was no real dataset target to wire a rule around.
  The first connector PR should add the `rule fetch_<source>_<dataset>`
  pattern (likely wildcarded over `source`/`dataset` once there are two or
  three of them, not before).
- `check_meta.py`'s `CODE_PREFIXES` includes `config/` — a config-only change
  currently requires a changelog entry. Confirm that's still wanted once
  tier-specific configs (`config.t1.yaml` etc.) start landing frequently.

**Open questions**

- `_inspect.py` only handles CSV (`inspect_csv`). XLSX (ONS ships both for
  some datasets, with different decimal conventions per the PRIMER's data
  dictionary gotcha) and fixed-width CEPEL decks will need their own
  `inspect_*` functions when a PR actually needs them — not added speculatively.
- `meta.yml` is unverified against real GitHub Actions (same caveat PR-02
  left for `lint.yml`/`test.yml` — no CI run has happened yet against this repo).
