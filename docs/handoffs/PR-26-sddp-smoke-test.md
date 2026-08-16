<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-26 — Julia/SDDP.jl feasibility smoke test (ADR-0005, stage 1a)

**Landed:**

- `julia/` subproject: `Project.toml` + `Manifest.toml` (SDDP, HiGHS,
  DataFrames, Parquet2), `smoke_test.jl`.
- `rules/sddp.smk::sddp_smoke_test` - trains SDDP.jl's own textbook
  two-stage hydro-thermal example, writes Benders cuts to Parquet.
- New pixi `sddp` environment/solve-group (`julia`), `pyarrow` added to
  `dev` (to read the cuts back).
- `test/test_sddp_cuts.py` + `test/fixtures/sddp/cuts_sample.parquet` (a
  real, unmodified smoke-test output, not synthesized).

## Why this PR, and why no Brazilian data in it

ADR-0005 named three real unknowns for the SDDP epic, deliberately staged
so they're debugged one at a time: (1) does Julia/SDDP.jl actually work
in this environment, (2) is ONS's ENA data what prior research assumed,
(3) does a REE-aggregated policy converge at all. This PR resolves
unknown (1) only, on purpose - using SDDP.jl's own tutorial example means
any bug found is unambiguously a coupling-mechanism bug, not a data or
formulation bug. Mixing those two kinds of risk in one PR is exactly what
this project's discipline (ADR-0007, PR-19/20) has learned not to do.

## What was actually checked, not assumed

- `pixi install -e sddp` fetched Julia 1.12.7 cleanly - no credential
  wall like Gurobi/atlite.
- `Pkg.add(["SDDP", "HiGHS"])` and `Pkg.add(["DataFrames", "Parquet2"])`
  both installed and precompiled without incident (~60s + ~55s).
- The trained policy converged: bound rose from 3,437 to 8,333.33 over 20
  iterations, `status: iteration_limit`, `numeric issues: 0` - a real,
  sane result for the textbook problem, not a crash or a degenerate zero.
- `pandas`/`pyarrow` read the resulting 40-row Parquet file back with
  correct dtypes and real (non-placeholder) cut data.
- Ran the whole thing twice: once directly via `julia --project=julia
  julia/smoke_test.jl`, once through `snakemake -j1 sddp_smoke_test` -
  both produced the same shape of output.

## Design choices worth knowing

- **`sddp` is its own pixi environment and solve-group**, not folded into
  `dev`. Julia is ~170 MiB; isolating it means `pixi install -e dev`
  (everyone's common case, and CI's) never fetches it. `pyarrow` went
  into `dev` instead, since reading Parquet is a lightweight, generally
  useful capability, not Julia-specific.
- **`sddp_smoke_test` is not part of `all` or `solve_all`** - same reason
  `fetch_all` isn't: it needs an environment CI doesn't install. Request
  it explicitly.
- **Cuts are flattened to one row per cut**, not left as SDDP.jl's native
  nested JSON (`SDDP.write_cuts_to_file`) - `node`, `intercept`,
  `state_variable`, `coefficient` (comma-joined for multi-state cuts).
  This is the shape a future linopy constraint-builder actually wants to
  loop over; the nested JSON is an intermediate step, written to a temp
  file and deleted, not committed anywhere.
- **Output path is `results/sddp_smoke_test/cuts.parquet`, not
  RUN_ID-scoped** like the T0 pipeline - this doesn't depend on
  `config.default.yaml` at all, so a run-id namespace would be misleading.

## Gotchas

- `SDDP.train`'s `log_file` kwarg **defaults to `"SDDP.log"` in the
  current working directory** - would have littered the repo root on
  every run (found by actually running it, not by reading docs first).
  Set explicitly to `/dev/null`; Snakemake's own `{log}` redirect already
  captures full training output.
- Nested quoting through `PowerShell → wsl.exe -lc → julia -e "..."`
  breaks the same way it does for `python -c "..."` (recorded in
  `wsl-windows-tooling` memory already) - write a `.jl` script file
  instead of an inline `-e` string. Cost real time twice this session
  before the pattern was applied consistently.
- Julia's `Project.toml` accepts a leading `#`-comment SPDX header exactly
  like `pixi.toml` does (verified: `Pkg.add`/`Pkg.instantiate` still work
  after adding it). `Manifest.toml` cannot - same as `pixi.lock` -
  exempted in `REUSE.toml`.

## Next PR needs

**PR-27 (or next): the ENA connector.** Same fetch → real data dictionary
→ tidy table shape as the six existing ONS connectors. Per ADR-0005's
recorded gotcha: target `ons-aws-prod-opendata.s3.amazonaws.com` directly
once the exact resource URL is known, not the CKAN search/show API, which
rate-limited after one successful call this session (from both WSL and
Windows-side network paths - not WSL-specific).

After that, in ADR-0005's order: PAR(p) fitting (validated against
persistence + spatial correlation, PRIMER Sec 4.7), a first
expectation-only SDDP policy on real ENA data, then CVaR, then
individualized reservoirs (a future ADR).

## Open questions

- None new on the coupling mechanism itself - that's what this PR
  resolved. ADR-0005's other two flagged unknowns (ENA data shape, REE
  convergence) are unchanged and still open.
