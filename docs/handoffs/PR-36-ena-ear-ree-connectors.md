<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-36 — `ena_ree` and `ear_ree` connectors (ADR-0008 stage 2, part 2)

**Landed:**

- `rules/fetch.smk::fetch_ons_ena_ree`/`fetch_ons_ear_ree` +
  `config.default.yaml` entries - 2016-2025, same year-range pattern as
  `ena_subsistema`/`ear_subsistema`.
- `docs/data-dictionary/ons/ena_ree.yaml` / `ear_ree.yaml` - full
  volume, 41,649 and 39,366 rows.
- `scripts/build_inflow_ree.py` / `build_reservoir_ree.py` +
  `rules/build.smk::build_inflow_ree`/`build_reservoir_ree`.
- `test/test_build_inflow_ree.py` (11 tests), `test/test_build_reservoir_ree.py`
  (10 tests), two real fixture samples.

This is what ADR-0008 originally asked for ("go for the REE connectors"),
built on PR-35's real registry and mapping. Every real-data check in this
PR found something worth understanding before writing the build logic -
none of the four findings below were assumed; each changed what the code
actually does.

## Four real findings, each changed the code, none assumed

1. **3 REEs don't have full history** - IGUACU, MANAUS-AMAPA,
   PARANAPANEMA only exist as separately-tracked units from 2017-12-30
   onward (2,924 rows vs. others' 3,653). A genuine REE-structure
   revision, not a gap. `build_inflow_ree.py`/`build_reservoir_ree.py`
   deliberately do NOT require every REE to share the same date count -
   unlike `build_inflow.py`/`build_reservoir.py`'s subsystem-level
   equivalents, which validly can (the 4 subsystems have always existed
   as such).

2. **ITAIPU's EAR reporting stops entirely on 2019-10-13** - 1,382 of an
   expected ~3,653 rows, all in 2016-2019. `ear_max_ree = 0.0` for
   ITAIPU explains why: a run-of-river binational plant with essentially
   no reservoir to report. `latest_capacity()` had to be changed from a
   single global "most recent date" (PR-30's subsystem-level version) to
   each REE's OWN most recent date - otherwise ITAIPU would either be
   silently dropped or given a stale/wrong value.

3. **TELES PIRES has a real 13-day EAR gap - starting the exact same
   date ITAIPU's reporting stops.** Two REEs' data changing on the same
   day is not a coincidence; it strongly suggests a real ONS
   system/methodology event around mid-October 2019 (not investigated
   further - what the event was is unknown). Recorded as a known,
   specific, already-investigated exception (`REPORTING_GAPS`) that
   prints a warning rather than failing the build - a genuinely new,
   different gap in a future re-fetch still raises.

4. **Storable ENA exceeds gross ENA for the first time in this
   project** (346/41,649 rows) - `ena_subsistema`'s equivalent check
   (PR-27) never triggered. Investigated with the full volume rather
   than assumed to be one phenomenon: 6 of 7 affected REEs show ~1e-14
   differences (pure floating-point noise around spill=0), but **PARANA
   is different and real** - 164 rows, mean +7.0%, max +40.5%,
   unexplained. Both clipped the same way (storable cannot physically
   exceed gross by definition), but recorded as two distinct causes in
   the data dictionary, not lumped together.

Also (mirroring PR-30's precedent, extended): verified storage clipped
in **both** directions now, not just over-capacity - 73 rows below zero,
547 rows above capacity, both concentrated in the REEs with the smallest
absolute `ear_max_ree` (BELO MONTE 22-28, MADEIRA 290-317, MANAUS-AMAPA
773-786 MWmes - the three smallest of all 12). The pattern that explains
both directions: the same absolute measurement noise that's negligible
for a huge reservoir (SUDESTE, hundreds of thousands of MWmes) is a much
larger relative swing for a tiny one.

## Design choices worth knowing

- **No uniform-date-count check at REE level** - the single biggest
  structural difference from the subsystem-level connectors. Each REE's
  own series is still validated gap-free within its own actual coverage
  window; REEs are just allowed to have different windows.
- **`REPORTING_GAPS` is a real, specific, documented exception list**,
  not a blanket relaxation of the gap check - a general invariant
  (no unexpected gaps) stays protective for anything not already
  investigated and recorded.
- **Both boundary directions clipped in `build_reservoir_ree.py`**,
  where `build_reservoir.py` (PR-30, subsystem level) only needed one -
  because REE-level data genuinely has both, not because the code was
  written more defensively for its own sake.

## Gotchas

- Same `python -c` inline-quoting issue as every prior PR - all
  exploratory checks used scratch `.py` files.
- A real bug introduced and caught while writing this PR itself, not by
  a later run: `attach_subsystem()`'s first draft had a dead
  `if False else` ternary artifact left over from an edit - caught on
  read-through before it was ever tested, not by a failing run.
- Ruff caught a real import-ordering slip (`REPORTING_GAPS` placed
  between `sys.path.insert` and the sibling-module import it enables) -
  fixed before commit, not a substantive bug, but a reminder that this
  project's established "sys.path.insert, then sibling imports" pattern
  is easy to break when adding a new module-level constant nearby.

## Next PR needs

Per ADR-0008: refit PAR(1) persistence and spatial correlation at REE
level (12x12 correlation matrix), using `resources/inflow_ena_ree.csv`.
PR-28/29's subsystem-level fitting code does not carry over automatically
- new fitting at the new granularity, following the same validation
discipline (recover known parameters from synthetic data, check
persistence/correlation are plausibly reproduced).

Then: a REE-level SDDP policy with an explicit REE-to-subsystem
allocation for the demand balance (demand and thermal stay at subsystem
level; hydro moves to REE level) - a real new modelling seam PRIMER's
architecture doesn't specify in detail.

## Open questions

- What actually happened to ONS's EAR-per-REE reporting around
  2019-10-13 - real, connected, unexplained.
- Why PARANA specifically shows a real, substantial storable-exceeds-gross
  pattern that no other REE does - unexplained, worth investigating
  before PAR(1) fitting trusts PARANA's storable column for anything.
