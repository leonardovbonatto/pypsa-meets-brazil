<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-05 — T0 demand series

**Landed**

- `scripts/build_demand.py` — `load_raw()` (reads and concatenates yearly ONS
  files), `validate_against_dictionary()` (pandera check at the boundary,
  before any transformation), `map_subsystems()` (ONS code -> config label,
  raises on anything unmapped), `parse_timestamps()` (tz-naive, deliberately —
  see Gotchas), `build_tidy_demand()` (produces `(snapshot, subsystem,
  load_mw)`, checked for duplicate/missing hours per subsystem).
- `rules/build.smk` with `build_demand_t0` and a `build_all` convenience
  target, mirroring `fetch_all`. Neither is a dependency of `all` — same
  reasoning as PR-04: these need real fetched data, which CI never has.
- `scripts/_common.py::snapshot_years()` replaces the `sources.ons.curva_carga.years`
  config list. Both `fetch_all` and `build_demand_t0` now derive which yearly
  files they need from `config.snapshots.start`/`end`, closing the
  consistency risk the PR-04 handoff flagged.
- 14 new tests (63 total).

**Key files:** `scripts/build_demand.py`, `rules/build.smk`.

**Data dictionaries added/changed:** none — this PR consumes
`docs/data-dictionary/ons/curva_carga.yaml`, doesn't add one.

**Verified against reality, not just asserted:**

Ran `snakemake -j2 build_all` from a clean slate (raw file and provenance
record both deleted first), which correctly triggered the fetch rule
automatically before building. The output — `resources/demand_t0.csv`,
35,136 rows — reproduces exactly the numbers hand-verified in the PR-04
handoff: 4 subsystems x 8784 hours, no gaps, no duplicates, mean SIN load
78,943 MWmed, 693.4 TWh for the year. The re-fetch also reproduced the
original sha256 byte-for-byte (second confirmation of this, after PR-04) —
only the `retrieved` timestamp in the provenance record differed, which was
reverted before committing since it wasn't a real change worth carrying.

**Gotchas**

1. **Timestamps are parsed tz-naive on purpose, not by oversight.** ONS's
   `din_instante` is Brasilia local time (UTC-3, no DST from 2019). PyPSA
   `n.snapshots` is conventionally a naive `DatetimeIndex`. Attaching a
   timezone here would only mean stripping it again in the build-network
   step. Documented in `parse_timestamps()`'s docstring so nobody
   "corrects" this later without reading why.
2. **The two failure-check layers in `build_tidy_demand()` are not
   redundant even though they look it.** `counts.nunique() != 1` catches
   subsystems missing different *totals* of hours cheaply, but two
   subsystems can share a total while one has a duplicate the other has a
   gap balancing out — the per-subsystem hourly-delta check catches that
   case. Both are cheap on 35k rows; kept both rather than trusting the
   faster one alone.
3. **`load_raw()` reuses `_inspect.inspect_csv()`** rather than calling
   `pd.read_csv()` directly, so the exact same parsing path that produced
   the committed dictionary also produces the data being validated against
   it — one fewer place for delimiter/encoding to silently diverge.
4. **Snakemake's automatic dependency resolution across rule files worked
   without any explicit wiring** — `build_demand_t0`'s `input.raw` pattern
   matches `fetch_ons_curva_carga`'s `output.raw` pattern, so asking for the
   built artifact transparently triggers the fetch first. No special-casing
   needed in `build.smk` at all. Worth remembering when adding the next
   fetch -> build pair (generation, next).

**Dead ends**

- Considered pinning the output snapshot range against
  `config.snapshots.start`/`end` exactly (e.g. asserting the tidy frame
  covers precisely that calendar range). Dropped it: `end: "2024-12-31"`
  with no time component is ambiguous — does it mean through the last hour
  of Dec 31, or up to but excluding it? Rather than silently resolving that
  ambiguity, `build_tidy_demand()` only checks *internal* consistency (no
  gaps, no dupes, every subsystem has the same hours) and leaves the
  calendar-range question for whoever writes the actual PyPSA snapshot
  builder, where it has to be resolved anyway.

**Next PR needs**

- The obvious next connector is generation (ONS *Geração por Usina em Base
  Horária* — per-plant hourly output) or CVU (thermal variable cost), per
  the roadmap's Epic 2 data inventory. Both should follow the exact same
  fetch -> dictionary -> build shape this PR and PR-04 established.
- Nothing in this repository has installed PyPSA yet (`docs/STACK.md`'s
  Layer 5 is still entirely PLANNED). The first PR that does should stay
  narrowly scoped to standing up a `Network` with buses and the T0 load
  already built here — not generators, not the solver — given the
  session-budget dependency limit (≤3 new deps: `pypsa` alone pulls in
  `linopy`, `xarray`, and others as transitive, which will eat most of that
  budget on its own).
- `resources/demand_t0.csv` is CSV for now, matching the raw format. Once a
  build-network step consumes it, reconsider Parquet (smaller, preserves
  the `snapshot` dtype instead of re-parsing a string on every read) — flagged
  in the PR-04 handoff for the raw fetch too, same tradeoff.

**Open questions**

- Should `build_demand_t0` validate against the dictionary once per input
  file or once on the concatenated frame? Currently once on the
  concatenation (schema is identical across years by construction, and it
  halves the number of full-file reads compared to validating each year
  individually). Revisit if a future year genuinely changes schema
  mid-range — the error will point at the whole multi-year frame rather
  than the specific offending file.
