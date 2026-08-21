<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every pull request adds an entry under `[Unreleased]`. CI fails a PR that touches
code without touching this file, unless it carries the `no-changelog` label.

## [Unreleased]

### Added

- Repository scaffold: README, REUSE-compliant licensing, contribution guide,
  pre-commit hooks, ruff configuration, GitHub PR and issue templates (PR-01).
- ADR-0001 recording repository conventions — Conventional Commits, squash-merge,
  the four-layer change log, and the per-PR session budget (PR-01).
- `docs/decisions/`, `docs/data-dictionary/` and `docs/handoffs/` with their
  templates and usage rules (PR-01).
- Feasibility assessment and staged roadmap for the full programme
  (`Brazilian-Grid-in-PyPSA.md`).
- `docs/PRIMER.md` — technical primer covering power system fundamentals, the
  Brazilian sector, optimization and SDDP, the software stack, engineering practice,
  and how to review agent-authored work.
- `pixi.toml` environment pinned to Python 3.12, with `default` and `dev`
  environments and workflow tasks (`dry`, `smoke`, `test`, `lint`) (PR-02).
- Snakemake workflow skeleton: `Snakefile`, `rules/common.smk` and the
  `write_run_manifest` rule emitting the ADR-0001 §4 run manifest (PR-02).
- Default and smoke configurations under `config/` (PR-02).
- GitHub Actions `lint` and `test` workflows; `test` runs unit tests, resolves the
  DAG, executes the smoke workflow and validates the manifest (PR-02).
- `REUSE.toml` covering generated and format-constrained files (PR-02).
- `docs/handoffs/PR-02-workflow-skeleton.md` recording seven environment gotchas
  found while getting the workflow to run (PR-02).
- `scripts/fetch.py` — the fetch/provenance core: streams a URL to disk and
  writes the `resources/_provenance/<source>/<dataset>.json` record consumed
  by `write_manifest.py`, with a small CLI for standalone use (PR-03).
- `scripts/_inspect.py` — samples a fetched CSV and emits the
  `docs/data-dictionary/` YAML, plus `to_pandera_schema()` to validate a
  later fetch of the same dataset against a committed dictionary (PR-03).
- `scripts/check_meta.py` and `.github/workflows/meta.yml` — CI checks that a
  code PR touches the changelog, every committed provenance record has the
  required keys, and ADR numbers are unique (PR-03).
- `requests` and `pandera` added to `pixi.toml` (PR-03).
- `docs/handoffs/PR-03-fetch-provenance-schema-core.md`.
- First real data connector: `rules/fetch.smk` and `scripts/fetch_dataset.py`
  fetch ONS *Curva de Carga* (hourly verified load per subsystem) into
  `resources/ons/`, writing a committed provenance record per file (PR-04).
- `docs/data-dictionary/ons/curva_carga.yaml` — the first real data
  dictionary, generated from the 2024 file and annotated by hand with ONS's
  own field definitions, the MWmed unit, and the timezone and subsystem-code
  traps (PR-04).
- `sources:` block in `config/config.default.yaml` and a `fetch_all` target,
  deliberately outside `rule all` so CI never reaches the network (PR-04).
- CLI for `scripts/_inspect.py`, so dictionaries can be generated directly
  from a fetched file (PR-04).
- `test/test_data_dictionaries.py` — validates committed dictionaries against
  a real committed slice of upstream data, and requires every dictionary to
  carry per-column descriptions and notes (PR-04).
- `docs/handoffs/PR-04-ons-load-connector.md`.
- `docs/STACK.md` — companion to the primer covering the *tooling* rather than
  the domain: every layer from WSL2 up to this project's own conventions, what
  each tool is for, its engineering equivalent, and which parts are built versus
  still planned. 12 mermaid diagrams.
- `rules/build.smk` and `scripts/build_demand.py`: the T0 tidy demand series,
  `resources/demand_t0.csv`, one row per `(snapshot, subsystem)` in MW. Ready
  for a PyPSA `n.loads_t.p_set` build step to pivot directly (PR-05).
- `scripts/_common.py::snapshot_years()` derives which yearly files to fetch
  and build from `config.snapshots.start`/`end`, replacing a separate `years:`
  list that could silently drift out of sync with the modelled range (PR-05).
- `build_all` Snakemake target, alongside `fetch_all`. Both stay outside `all`
  since they reach the network or its downstream artifacts (PR-05).
- `docs/handoffs/PR-05-t0-demand-series.md`.
- `pypsa` added to `pixi.toml` — the first domain modelling dependency to
  land. `scripts/build_network.py` and `rules/build.smk::build_network_t0`
  build the bare T0 `Network`: one bus per subsystem, snapshots from config,
  the T0 demand series attached as time-varying loads. No generators, no
  lines, no solver yet (PR-06).
- `docs/handoffs/PR-06-bare-t0-network.md`.
- Second real data connector: `rules/fetch.smk::fetch_ons_capacidade_geracao`
  fetches ONS installed generating capacity (per generating unit, 5631 rows,
  current snapshot). `docs/data-dictionary/ons/capacidade_geracao.yaml` — the
  second real data dictionary, annotated with ONS's own field definitions and
  a documented finding: the `PY` subsystem code is the Paraguay-frequency
  (50 Hz) side of the binational Itaipu plant, not part of Brazil's 60 Hz SIN
  (PR-07).
- `docs/handoffs/PR-07-ons-capacity-connector.md`.
- `scripts/build_generators.py` and `rules/build.smk::build_generators_t0`:
  aggregate ONS installed capacity to `resources/generators_t0.csv`, one row
  per `(subsystem, technology)`, filtering to active units and excluding `PY`
  (Itaipu 50 Hz — not part of Brazil's SIN). `build_network.py::attach_generators()`
  attaches these to the T0 network as one `Generator` per row. Capacity and
  topology only — no marginal cost, no availability profile, `n.optimize()`
  still not callable (PR-08).
- `docs/handoffs/PR-08-t0-generator-capacity.md`.
- Third real data connector: `rules/fetch.smk::fetch_ons_cvu_usina_termica`
  fetches ONS thermal-plant variable cost (CVU), weekly per plant, one file
  per year (4881 rows for 2024). `docs/data-dictionary/ons/cvu_usina_termica.yaml`
  — records the R$/MWh unit, that CVU genuinely varies week to week (not
  noise), and that this dataset's plant IDs/names do not join cleanly against
  `capacidade_geracao`'s (PR-09).
- `docs/handoffs/PR-09-ons-cvu-connector.md`.
- `scripts/build_costs.py` and `rules/build.smk::build_costs_t0`: reduce
  weekly per-plant CVU to one R$/MWh value per subsystem (mean across all
  plants and weeks, real zero-cost plants included).
  `build_network.py::attach_marginal_costs()` sets this on the T0 network's
  thermal generators, and an explicit documented `0.0` default (not an
  accidental one) on hydro/wind/solar/nuclear. Still no lines, no
  availability profile, no solver — `n.optimize()` still not callable
  (PR-10).
- `docs/handoffs/PR-10-t0-marginal-cost.md`.
- `highspy` (HiGHS) added to `pixi.toml` as an explicit dependency — the
  first solver this project can actually call. `scripts/solve_network.py`
  runs `n.optimize()` and writes a dispatch summary that always carries a
  `known_limitations` list, so a result can't be read without it.
  `build_network.py::attach_load_shedding()` adds an always-available,
  high-cost slack generator per bus, discovered to be necessary because the
  `S` subsystem's own capacity falls short of its own peak demand in 2 of
  8784 hours (267 MWh/year) — with no transmission lines yet, that made the
  network genuinely infeasible without one. Its dispatch is the honest,
  quantified signal for exactly that gap (PR-11).
- `rules/solve.smk::solve_network_t0` and a `solve_all` target, kept outside
  `all` like `fetch_all`/`build_all` (PR-11).
- `docs/handoffs/PR-11-t0-solve.md`.
- `docs/decisions/ADR-0006-t0-transfer-representation.md` — T0 models
  inter-subsystem connections as PyPSA `Link`s (a transport model), not
  `Line`s: real impedances need DESSEM/ANAREDE deck parsing (ADR-0003, T3
  only). Topology and a transfer-capacity proxy both come from real data,
  not assumption.
- Fourth real data connector: `rules/fetch.smk::fetch_ons_intercambio_nacional`
  fetches ONS real hourly inter-subsystem interchange (signed, MWmed).
  `docs/data-dictionary/ons/intercambio_nacional.yaml` — confirms the SIN's
  real T0-relevant topology is exactly four boundaries (`N-NE`, `N-SE`,
  `NE-SE`, `SE-S`; no direct `N-S` or `NE-S`), and records the sign
  convention and the ONS-dictionary/data mismatch pattern seen again here
  (PR-12).
- `docs/handoffs/PR-12-ons-interchange-connector.md`.
- `scripts/build_links.py` and `rules/build.smk::build_links_t0`: reduce the
  real interchange series to one transfer-capacity row per real boundary
  (`p_nom = max(abs(flow))`, per ADR-0006). `build_network.py::attach_links()`
  attaches these as bidirectional PyPSA `Link`s. Re-solving after this
  resolves PR-11's `S` infeasibility completely (`load_shedding_mwh_by_bus`
  goes to `{}`) — and reveals a new, real finding: with subsystems now able
  to trade power, national free-generation capacity so comfortably exceeds
  even peak demand that thermal generation dispatches at exactly 0 MW for
  every hour of 2024. A genuine consequence of the still-open "no
  availability profile" gap, not a bug (PR-13).
- `docs/handoffs/PR-13-t0-transfer-links.md`.
- Fifth real data connector: `rules/fetch.smk::fetch_ons_fator_capacidade`
  fetches ONS real hourly wind/solar capacity factor, per plant-group, one
  file per (year, month) since this dataset is large (~37-40 MB/month).
  `scripts/_common.py::snapshot_year_months()` derives which (year, month)
  pairs to fetch, the month-level analogue of `snapshot_years()`.
  `docs/data-dictionary/ons/fator_capacidade.yaml` — records that
  `val_fatorcapacidade` is exactly PyPSA's `p_max_pu` definition, that a
  small fraction of real values exceed 1.0 (must be clipped), and a real,
  verified gap: `SE_CO` has zero wind rows in this dataset in every month
  checked, despite having ~261 MW of registered wind capacity (PR-14).
- `docs/handoffs/PR-14-ons-capacity-factor-connector.md`.
- `scripts/build_availability.py` and `rules/build.smk::build_availability_t0`:
  aggregate the real capacity-factor data into an hourly `p_max_pu` per
  `(subsystem, technology)` — the aggregate fleet capacity factor
  (sum generation / sum capacity), clipped to `[0, 1]`.
  `build_network.py::attach_availability()` sets it on the matching
  generators; anything uncovered (only `SE_CO wind`) keeps PyPSA's 1.0
  default, explicitly documented rather than silent. Wind's mean dispatch
  duly falls from 12,655 to 8,855 MW — but thermal dispatch stays at
  exactly 0 MW, and isolating why produced the more important finding
  below (PR-15).
- `docs/handoffs/PR-15-t0-availability-profile.md`.
- `scripts/solve_network.py::summarize_prices()` — records mean
  `marginal_price` per bus (R$/MWh, the CMO validation target) in the
  dispatch summary, plus an explicit `all_prices_zero` flag and a runtime
  warning for the *economically degenerate* case where a zero-cost
  generator always has headroom so nothing scarce ever sets a price. That
  is the current state, and it was previously invisible without manually
  inspecting the solved network (PR-16).
- `docs/handoffs/PR-16-report-marginal-prices.md`.
- `docs/decisions/ADR-0007-hydro-backcast-interim.md` — constrain T0 hydro
  with observed generation as an explicitly-labelled **interim backcast**
  while the water-value work proceeds separately. Records what such a model
  can and cannot legitimately claim, since validating prices against
  observed CMO from this configuration would be partly circular.
- Sixth real data connector: `rules/fetch.smk::fetch_ons_geracao_usina`
  fetches ONS hourly verified generation per plant (~66 MB/month, 6.1M rows
  for 2024 — the largest dataset this project fetches).
  `docs/data-dictionary/ons/geracao_usina.yaml` records the load-bearing
  finding: this dataset covers Tipo III and MMGD plants that
  `capacidade_geracao` does not, so an unfiltered capacity-factor ratio
  reaches 1.021 for `S` — filter to matching modalidades, don't clip
  (PR-17).
- `docs/handoffs/PR-17-ons-generation-connector.md`.
- `scripts/build_hydro_availability.py` and
  `rules/build.smk::build_hydro_availability_t0`: hourly hydro `p_max_pu`
  per subsystem from observed generation (ADR-0007). **The model is no
  longer economically degenerate** — thermal dispatch goes from 0 to 13,082
  MW mean, the objective from 0 to 49.4 bn R$, and marginal prices from 0
  to 591–712 R$/MWh. First ballpark check against ONS's observed 2024 mix:
  total generation matches to 0.5%, but thermal runs 60% high because the
  model lacks Brazil's MMGD distributed solar (observed solar 8,360 MW
  mean vs the model's 4,816). Not validation — see ADR-0007 (PR-18).
- `docs/handoffs/PR-18-hydro-backcast-and-ballpark-check.md`.
- `scripts/build_mmgd.py` and `rules/build.smk::build_mmgd_t0`: adds MMGD
  (distributed rooftop PV, 5,126 MW mean) as a `solar_mmgd` carrier, from
  observed generation — a backcast on ADR-0007's principle. Closes the gap
  PR-18 quantified: **thermal dispatch falls 13,082 → 7,977 MW against
  8,161 observed (1.60× → 0.98×)**, load shedding goes to zero, and the S
  price premium collapses from 121 to 3 R$/MWh. Reuses `attach_generators`
  and `attach_availability` unchanged (PR-19).
- `docs/handoffs/PR-19-mmgd-distributed-generation.md`.
- `docs/decisions/ADR-0005-inflow-model-formulation.md`: fills the epic's
  reserved ADR slot, deciding how the SDDP water-value epic starts (the
  user's agreed step 2, after ADR-0007's backcast). Starts with ONS's own
  open ENA data (CC-BY, no credential blocker, confirmed live this
  session) at REE/subsystem level, not the NEWAVE-deck route
  (`VAZOES.DAT` via `inewave`) - matching PRIMER Sec 4.6's "REE first"
  guidance and this project's established cheap-real-interim pattern
  (ADR-0007, PR-19/MMGD). Also confirmed Julia 1.12.7 is installable via
  conda-forge - no blocker of the Gurobi/atlite kind. No code lands with
  this ADR; it authorizes the epic's staged order, starting with a
  Julia/SDDP.jl environment feasibility smoke test before any Brazilian
  data (PR-25).
- `docs/handoffs/PR-25-sddp-inflow-model-adr.md`.
- `julia/` subproject and `rules/sddp.smk::sddp_smoke_test` (ADR-0005 stage
  1): trains SDDP.jl's own textbook hydro-thermal example - no Brazilian
  data - and writes the resulting Benders cuts to Parquet. Proves the
  Snakemake -> Julia -> Parquet -> Python coupling PRIMER Sec 4.5/5.10
  describes actually works, checked end-to-end this session rather than
  assumed: Julia 1.12.7 + SDDP.jl + HiGHS.jl install and precompile
  cleanly, the trained policy converges to a sensible bound, and
  `pandas`/`pyarrow` reads the 40 resulting cuts back with the right
  shape. Deliberately not part of `all` - needs the new `sddp` pixi
  environment (Julia, ~170 MiB), isolated in its own solve-group so a
  plain `pixi install -e dev` never fetches it. New deps: `julia` (`sddp`
  env only), `pyarrow` (`dev` only, to read the Parquet cuts back) (PR-26).
- `test/test_sddp_cuts.py` and `test/fixtures/sddp/cuts_sample.parquet` (a
  real, unmodified output of the smoke test): tests the Python-side half
  of the coupling without needing Julia in CI, the same reason
  `fetch_all` never runs there either (PR-26).
- `docs/handoffs/PR-26-sddp-smoke-test.md`.
- Seventh ONS connector: `ena_subsistema` (ADR-0005, SDDP epic stage 1) -
  daily Energia Natural Afluente per subsystem, 2000-2025 (26 years,
  `inflow_history_years()` in `scripts/_common.py`, deliberately NOT
  derived from `snapshots.start/end` like every other connector - PAR(p)
  needs decades of history, not the T0 reference year). Found the real S3
  URL directly (`ons-aws-prod-opendata.s3.amazonaws.com/dataset/ena_subsistema_di/`),
  bypassing the CKAN search API that rate-limited during PR-26's research.
  `scripts/build_inflow.py` tidies to (date, subsystem) with all four
  published ENA figures (gross/storable x MWmed/% of long-term average) -
  deliberately keeps all four rather than picking one, since which figure
  PAR(p) fits on is the next PR's decision. `docs/data-dictionary/ons/ena_subsistema.yaml`
  built from the complete 26-year, 37,988-row volume (no nulls anywhere),
  and records a real, unresolved discrepancy: ONS's own published
  dictionary states the unit as "MWmes" while the column name says
  "mwmed" - documented as an inference (MWmed), not silently picked (PR-27).
- `docs/handoffs/PR-27-ena-connector.md`.
- `rules/sddp.smk::fit_inflow_par1` + `scripts/fit_inflow_par1.py` (ADR-0005
  stage 1c: persistence): fits a PAR(1) inflow model per subsystem from
  `resources/inflow_ena.csv` - month-specific mu/sigma of log gross ENA
  and a lag-1 autocorrelation phi, the Brazilian-standard periodic
  autoregressive formulation (PRIMER Sec 4.7), on the simplest defensible
  order (1, not AIC/PACF-selected). Validates persistence - the first of
  PRIMER Sec 4.7's two required properties - by simulating 200 realizations
  per subsystem and checking where the real historical drought-run length
  falls within that distribution: N 0.16, NE 0.365, S 0.81, SE_CO 0.55, all
  comfortably inside the model's own range rather than an outlier. Real
  phi values found, not assumed: N 0.80-0.98 (strong, matching the
  Amazon's predictable seasonality), S 0.34-0.81 (weaker, matching its
  less ENSO-correlated rainfall). **Spatial correlation across subsystems
  - PRIMER Sec 4.7's second required property - is deliberately NOT
  preserved here**, named as a real gap in `KNOWN_LIMITATIONS`, not an
  oversight: each subsystem is fit and simulated independently (PR-28).
- `docs/handoffs/PR-28-sddp-par1-persistence.md`.
- `scripts/fit_inflow_par1.py::compute_residuals/residual_correlation_matrix/simulate_par1_correlated/validate_spatial_correlation`
  (ADR-0005 stage 1d: spatial correlation) - the second of PRIMER Sec 4.7's
  two required properties, closing the gap PR-28 named explicitly.
  Correlates same-(year, month) residuals across all 4 subsystems into a
  single matrix (pooled across calendar months - a documented
  simplification, see `KNOWN_LIMITATIONS`), then simulates jointly via
  Cholesky decomposition rather than independently per subsystem. Real,
  scientifically plausible finding on the actual data: N and S are
  *negatively* correlated (-0.25), consistent with known Brazilian
  ENSO-driven rainfall dynamics; N-NE positively correlated (+0.48).
  Validated by re-estimating correlation from the simulator's OWN output
  (not just checking the input matrix survived) - every pair recovered
  within 0.03 of its historical value. Real bug found and fixed:
  `corr_matrix.stack().reset_index()` collided because `.corr()` leaves
  both axes named "subsystem" - now a regression test. `resources/inflow_par1_correlation.csv`
  is the new output; `results/inflow_par1_validation.json` gained a
  `spatial_correlation_by_subsystem_pair` section (PR-29).
- `docs/handoffs/PR-29-sddp-par1-spatial-correlation.md`.
- Eighth ONS connector: `ear_subsistema` (ADR-0005 stage 1e) - daily
  reservoir storage per subsystem, 2000-2025, same shape as `ena_subsistema`
  (PR-27). Checked whether ONS publishes real reservoir CAPACITY
  (`ear_max_subsistema`) before assuming a hydro-thermal SDDP policy would
  need a fabricated placeholder number - it does. Real finding: capacity
  genuinely grows over the 26-year record (SE 157,701 -> 204,615 MWmes,
  new reservoirs built), so `scripts/build_reservoir.py::latest_capacity()`
  uses the most recent year, not a historical average, which would
  understate present-day capacity. Real, small, checked quirk: verified
  storage exceeds max capacity in 99 of 37,988 rows (0.26%, all subsystem
  N, mostly year 2000, <=3.66% over) - clipped, not rejected, following
  the same precedent as `fator_capacidade`'s >1.0 rows (PR-14).
  `scripts/_common.py::inflow_history_years()` generalized to take a
  `dataset` parameter, shared by `ena_subsistema` and `ear_subsistema`
  rather than duplicated (PR-30).
- `docs/handoffs/PR-30-ear-connector.md`.
- `scripts/prepare_sddp_inputs.py` + `julia/sddp_first_policy.jl` +
  `rules/sddp.smk::prepare_sddp_inputs/sddp_first_policy` (ADR-0005 stage
  1f): the first expectation-only SDDP policy on real Brazilian data.
  4 subsystems, 12 monthly stages, real demand/hydro/thermal
  capacity/cost (T0), real reservoir capacity (PR-30), real fitted
  seasonal inflow distributions correlated across subsystems (PR-28/29,
  drawn i.i.d. per month - temporal persistence not yet wired into the
  policy, a named limitation). Trains cleanly (0 numeric issues, 550
  cuts, expected annual system cost R$240.9m). Real finding: S subsystem
  accounts for ~95% of all simulated load shedding (17,178 of 18,074
  MW-months/year) - the same structural gap PR-11/13 already found and
  solved with inter-subsystem transmission Links in the T0 network itself;
  this reduced SDDP subproblem deliberately excludes transmission
  (KNOWN_LIMITATIONS), so it rediscovers the identical bottleneck from a
  different model. Two independently-built models finding the same real
  physical constraint is treated as cross-validation, not a bug to chase.
  Reused `LOAD_SHED_COST = 10,000` from `build_network.py` for consistency
  rather than inventing a new slack cost. No new dependencies - `pyarrow`
  and `Parquet2.jl` already landed in PR-26 (PR-31).
- `docs/handoffs/PR-31-sddp-first-policy.md`.
- `julia/sddp_first_policy.jl` now takes a risk-measure argument
  (ADR-0005 stage 1g: PRIMER Sec 4.4's CVaR); `rules/sddp.smk::sddp_cvar_policy`
  trains it alongside the existing expectation-only policy for
  comparison. Real convention mismatch found and translated explicitly,
  not assumed: SDDP.jl's `EAVaR(lambda, beta)` weights `lambda` on
  *expectation*, the opposite of PRIMER's `(1-lambda)*E + lambda*CVaR_alpha`,
  where `lambda` weights CVaR. Real, honest finding from actually running
  both: at the original `iteration_limit=50`, load shedding was
  materially understated for BOTH policies - bumped to 300 (checked
  directly, not guessed) after confirming numbers kept moving between the
  two. Even at 300, the expectation-vs-CVaR comparison isn't fully clean
  (CVaR's mean simulated cost was sometimes lower than expectation's own,
  which shouldn't happen if both were perfectly converged) - reported
  honestly as a real open question (fixed iteration count, not a
  convergence-gap stopping rule; only 100 Monte Carlo simulation
  realizations), not smoothed into a tidier story than the numbers
  support (PR-32).
- `docs/handoffs/PR-32-sddp-cvar.md`.
- `julia/sddp_first_policy.jl`: `SDDP.SimulationStoppingRule()` (SDDP.jl's
  own recommended default) replaces PR-32's fixed `iteration_limit=300`,
  and `Random.seed!` fixes SDDP.jl's own internal RNG (previously only
  `prepare_sddp_inputs.py`'s scenario sampling was seeded) - reproducibility
  verified directly: two identical-seed runs produce byte-identical
  `summary.json`. Real, checked-not-hidden finding: the stopping rule does
  NOT actually trigger within a 1000-iteration safety cap - training still
  hits the cap in practice, and numeric issues rise to 57 (0 at 50
  iterations, low single digits at 300), a real signal about this model's
  LP conditioning worth investigating rather than raising the cap
  indefinitely. A more useful finding fell out of the better-converged,
  reproducible comparison this enabled: at 1000 iterations with a fixed
  seed, expectation and CVaR policies converge to nearly IDENTICAL tail
  outcomes (P90 load shed: 30,090.5 for both). First hypothesis tried and
  refuted by checking, not left standing: S's own hydro+thermal capacity
  (19,141 MW) comfortably exceeds its peak monthly demand (15,666 MW), so
  this is not a physically-forced capacity shortfall. The better-supported
  explanation ties directly to PR-31's own most significant named
  limitation: inflow scenarios are i.i.d. per month, so the policy has no
  signal that a dry month is more likely to follow another one, even
  though the real fitted PAR(1) process (phi up to 0.81 for S) genuinely
  has that structure - a concrete symptom of persistence's absence, not
  just an abstract caveat (PR-33).
- `docs/handoffs/PR-33-sddp-convergence-and-seeding.md`.
- `docs/decisions/ADR-0008-ree-level-individualization.md`: the SDDP
  epic's next individualization stage - REE (Reservatório Equivalente de
  Energia, CEPEL/ONS's own real intermediate aggregation), not straight
  to full per-plant (150-170 reservoirs). A framing correction caught
  before it became a silent scope-skip: PRIMER Sec 4.6 says "REE first,
  individualized second" - ADR-0005 actually built at subsystem level
  (coarser than REE), so this project had not yet taken PRIMER's own
  named first individualization step. Checked, not assumed: ONS publishes
  real REE-level ENA/EAR data (12 REEs, 2016-2026, same S3-prefix-listing
  method as PR-27/30, no CKAN) - confirmed available before deciding to
  build on it, the same discipline ADR-0005 applied to Julia/ENA. Two
  real findings from that check, named for the connector PR rather than
  smoothed over: neither dataset carries a REE-to-subsystem mapping
  column (the 12 names are inferable but unconfirmed), and one REE
  (MADEIRA) showed a negative `ear_verif_ree_mwmes` in the first sample
  row - a different, unexplained failure mode from PR-30's
  storage-exceeds-capacity quirk. Full per-plant individualization
  (`hidr.dat`/`VAZOES.DAT` via `inewave`, NEWAVE decks) remains the named
  further destination, explicitly gated on verifying deck access first -
  unlike every other epic dependency so far, it has never been checked.
  `.codespellignore` gained `parana` (a real REE/river name, not a typo
  for "piranha") (PR-34).
- Ninth ONS connector: `reservatorio` (ADR-0008 stage 2) - per-reservoir
  physical registry, 162 real reservoirs (matching PRIMER Sec 2.1's own
  "order 100-170" estimate almost exactly), current snapshot like
  `capacidade_geracao`. Resolves ADR-0008's named open question with real
  data instead of domain-name inference: `id_subsistema` and `nom_ree`
  sit on the same row for every reservoir, giving a clean, checked 1:1
  REE-to-subsystem mapping (`scripts/build_reservoir_registry.py::build_ree_subsystem_map()`
  raises if that invariant is ever violated, not just documented as true).
  Corrected a domain-name guess made while drafting ADR-0008: MADEIRA and
  TELES PIRES (Amazon-basin river names) actually map to subsystem
  SE_CO, not N as their geography would suggest - exactly why this was
  checked against real data. A significant secondary finding: ONS's own
  dictionary states `val_perda` "sao os mesmos utilizados pelo programa
  Newave" (are the same values NEWAVE uses) - this dataset may
  substantially de-risk ADR-0008's biggest named unknown (whether full
  per-plant individualization needs NEWAVE deck parsing via `inewave` at
  all), flagged for real investigation in that future ADR, not assumed
  to fully replace `hidr.dat` (PR-35).
- `docs/handoffs/PR-35-reservoir-registry.md`.
- Tenth and eleventh ONS connectors: `ena_ree` and `ear_ree` (ADR-0008
  stage 2) - REE-level counterparts of `ena_subsistema`/`ear_subsistema`
  (PR-27/30), 12 real REEs, 2016-2025, using PR-35's real
  REE-to-subsystem mapping instead of domain-name inference. Real
  findings from the full-volume check, each investigated rather than
  assumed: 3 REEs (IGUACU, MANAUS-AMAPA, PARANAPANEMA) only exist as
  separately-tracked units from 2017-12-30 onward (a genuine REE-structure
  revision, not a data gap - `build_inflow_ree.py`/`build_reservoir_ree.py`
  deliberately don't require uniform date counts across REEs, unlike
  their subsystem-level equivalents); ITAIPU's EAR reporting stops
  entirely on 2019-10-13 (a run-of-river plant with `ear_max_ree = 0.0`);
  TELES PIRES has a real 13-day EAR gap starting the SAME date ITAIPU's
  reporting stops - not a coincidence, strongly suggesting a real ONS
  system/methodology event around then (recorded as a known,
  non-fatal-warning gap, `REPORTING_GAPS`). Storable-exceeds-gross ENA
  triggers for the first time in this project (346/41,649 rows) - mostly
  floating-point noise (~1e-14) but a real, unexplained, substantial
  pattern (mean +7%, max +40%) specific to PARANA, documented distinctly
  rather than lumped in with the noise. Verified storage clipped in both
  directions (below 0 and above capacity), both concentrated in the
  smallest-capacity REEs (PR-36).
- `docs/handoffs/PR-36-ena-ear-ree-connectors.md`.
- `.gitignore` stopped excluding `julia/Manifest.toml`, found while
  staging this PR: it's Julia's exact equivalent of `pixi.lock` (resolved
  package versions), which this project commits for reproducibility - the
  old exclusion (present since PR-01, before `julia/` existed) contradicted
  that stated principle the moment `julia/` became real. `.codespellignore`
  gained `missings` (a real Julia package name in the committed manifest,
  not a typo) (PR-26).
- `docs/decisions/README.md`'s index: ADR-0005's slot resolved from
  "Planned (PR-34)" to Accepted; found while updating it that 0002 and
  0004 carried the same fragile future-PR-number guesses fixed elsewhere
  in PR-23 (the real numbering has never matched early guesses) - stripped
  to plain "Planned" (PR-25).
- `docs/PRIMER.md` Sec 4.6: removed a reference to "Gate D in the plan" -
  the roadmap uses numbered phases (0-9), no such gate exists anywhere;
  another instance of PR-23's stale-forward-reference pattern, found while
  researching this ADR (PR-25).
- `scripts/fit_inflow_par1_ree.py` + `rules/sddp.smk::fit_inflow_par1_ree`
  (ADR-0008 stage 2): PAR(1) persistence and a 12x12 spatial correlation
  matrix fit per REE, the REE-level counterpart of `fit_inflow_par1.py`
  (PR-28/29). A real finding from fitting on the full 2016-2025 volume:
  TELES PIRES reports `ena_bruta_mwmed == 0.0` for its first 213 days
  (2016-01-01 to 2016-07-31) before real values start - a "not yet
  tracked" placeholder (same underlying phenomenon as PR-36's 3
  later-starting REEs, just represented as zero rows instead of missing
  ones) that would otherwise corrupt that month's log-space mu to -inf;
  dropped before fitting via a general rule (`drop_pre_tracking_zeros`),
  not a REE-specific exception. Despite the much shorter, more ragged
  record (9-10 years per REE vs. the subsystem-level fit's 26), both
  validations held up well against the real data: no REE's historical
  drought run exceeded the 90.5th percentile of its own simulated
  distribution (well under the understated-persistence warning
  threshold), and the Cholesky-correlated simulator reproduced every one
  of the 66 REE-pair correlations within 0.06 of the historical value
  (PR-37).
- `docs/handoffs/PR-37-par1-ree-refit.md`.
- **Temporal persistence wired into the SDDP policy** (`julia/sddp_first_policy.jl`,
  `scripts/prepare_sddp_inputs.py`) - PR-31/33's own most-implicated gap:
  inflow scenarios were i.i.d. per month, so the policy could never see a
  drought coming from consecutive dry months. Now a state-augmented AR(1)
  log-inflow anomaly (`z`) carries persistence month-to-month, using the
  real fitted phi (PR-28/29). SDDP.jl's experimental `add_objective_state`
  mechanism was investigated first and REJECTED - its own docs require the
  price/objective state to never appear in a `@constraint`, and `inflow`
  must (the storage balance). Verified instead, via a real standalone
  Julia smoke test, that an ordinary `SDDP.State`'s incoming value is
  queryable via `JuMP.fix_value` inside `parameterize`, letting the AR(1)
  recursion and `exp(mu+sigma*z)` transform run in plain Julia (not a
  nonlinear JuMP expression) and then `fix()` both `z.out` and the real
  `inflow` variable. Two real bugs caught and fixed while verifying end to
  end against real data, neither left as silent workarounds: (1) SDDP.jl's
  pre-training `numerical_stability_report` probes `parameterize` without
  the real state-fixing sequence, crashing on `fix_value` - fixed by
  disabling that specific (purely informational) report, which doesn't
  affect the separately-tracked per-iteration numeric-issue count; (2) the
  AR(1) shock was missing its `sqrt(1-phi^2)` variance-normalizing scale
  (present in the Python fit's own simulator but omitted here), which
  first showed up as implausibly large cost/load-shed numbers before being
  traced to the real cause and fixed, not accepted as a genuine result.
  `prepare_sddp_inputs.py`'s `sample_month_scenarios` is renamed
  `sample_month_shocks` and now emits raw correlated standardized shocks,
  not pre-computed inflow levels. Trained and compared against real data:
  expected annual cost and P90 load shed both roughly doubled versus the
  i.i.d. baseline (PR-31/33) - plausible, since consecutive-dry-month
  years are now representable for the first time, not fully confirmed
  beyond direct verification. Expectation and CVaR are no longer
  near-identical (resolving PR-33's own headline finding), but CVaR's P90
  load shed came out HIGHER than expectation's - backwards from theory,
  the same direction PR-32 found and PR-33 only partly resolved by raising
  iterations; untested here whether more iterations closes it, named as a
  real next step rather than chased in this PR (PR-38).
- `docs/handoffs/PR-38-sddp-temporal-persistence.md`.

### Changed

- `REUSE.toml` now attributes ONS-derived files (fixtures, data dictionaries)
  to ONS rather than to this project. Their data is CC-BY, and attribution is
  what that licence requires (PR-04).
- Renamed `test/fixtures/ons_carga_sample.csv` to `synthetic_load_sample.csv`:
  it is invented data, and the old name implied otherwise now that real ONS
  fixtures sit beside it (PR-04).
- `config.default.yaml`: removed `sources.ons.curva_carga.years`, now derived
  from `snapshots` instead of listed separately (PR-05).
- `scripts/build_demand.py`'s subsystem mapping moved to the new shared
  `scripts/_ons.py`, since `build_generators.py` needs the identical mapping
  (PR-08).
- `docs/data-dictionary/ons/fator_capacidade.yaml` regenerated from all 12
  months of 2024 rather than January alone. A January-only sample had no
  nulls in `val_latitudesecoletora`, so the derived schema marked it
  non-nullable and pandera then rejected the real full-year frame (16,848
  nulls). Generalized lesson recorded in the dictionary's notes: build a
  dictionary from the same data volume that will be validated against it
  (PR-15).
- `scripts/solve_network.py::KNOWN_LIMITATIONS` rewritten: the old entries
  claimed "no transmission lines" and "no availability profile", both since
  fixed. It now leads with the real dominant caveat — hydro is unconstrained
  and free — because a stale caveat naming an already-fixed problem is as
  misleading as a missing one (PR-15).
- `scripts/solve_network.py::KNOWN_LIMITATIONS` and
  `docs/data-dictionary/ons/fator_capacidade.yaml`: quantified the root
  cause of PR-19's "utility solar ~1.5x high" finding. `fator_capacidade`
  (PR-14/15's wind/solar capacity-factor source) tracks only 48% of
  national solar nameplate capacity and 43% of wind (concentrated
  ONS-dispatched plant-groups vs `capacidade_geracao`'s full per-plant
  registry) — the same registry-vs-dispatch population mismatch already
  found for hydro (PR-17/18), here inflating dispatch rather than deflating
  it. No code change: no better per-plant capacity-factor source is
  currently connected (PR-20).
- `docs/handoffs/PR-20-wind-solar-coverage-gap.md`.
- `README.md` and `docs/STACK.md`: `julia/` was marked "planned, not yet
  created" in PR-24 and is real as of this PR - updated both, and added a
  note to STACK.md's SDDP.jl section recording what PR-26's smoke test
  actually proved vs what's still PLANNED (PR-26).

### Fixed

- `.github/workflows/meta.yml` now also triggers on push to `main`, not only
  `pull_request`. This project pushes straight to `main` (ADR-0001) rather
  than opening PRs, so the meta checks (changelog, provenance schema, ADR
  numbering) had never actually run in CI since PR-02 introduced them — only
  ever locally. `META_BASE_REF` diffs against `github.event.before` on a
  push, the commit before the push, rather than a PR's base branch (PR-21).
- `docs/STACK.md` brought current through PR-21: it still described hydro as
  "unconstrained and free" (fixed PR-17/18), CI as "never yet executed"
  (running on every push since PR-03/04), and 49 tests (now 210). Updated
  the intro caveat, the PyPSA/hydro narrative, the GitHub Actions and pytest
  sections, the pinned-dependency list (`pypsa`/`highspy` were missing), the
  two pipeline diagrams, and the file map to name the newer build scripts
  (PR-22).
- `docs/PRIMER.md`: two stale forward-references to specific future PR
  numbers (`PR-19`, `PR-23`) that no longer mean what they meant when
  written - the real PR-19 turned out to be MMGD, and there is no PR-23 yet.
  Replaced with honest "still PLANNED" notes. The illustrative Snakemake
  rule in Sec 5.3 didn't match any real rule (`carga_verificada.parquet`,
  a `{tier}` wildcard that doesn't exist yet); replaced with the real
  `build_demand_t0` rule. `rules/build.smk`'s `build_generators_t0` and
  `build_network_t0` docstrings also updated - both still described
  pre-PR-09/14/17 state (PR-23).
- `README.md`: the status banner said "pre-alpha, nothing here solves a
  network yet" - false since PR-11, and actively misleading for the most
  visible doc in the repo. Replaced with an accurate summary of what T0
  actually does today and its main caveat (hydro backcast, ADR-0007). The
  `Layout` section also listed `data/` and `julia/` as if they existed;
  neither has been created yet - split them out and marked planned (PR-24).

[Unreleased]: https://github.com/leonardovbonatto/pypsa-meets-brazil/commits/main
