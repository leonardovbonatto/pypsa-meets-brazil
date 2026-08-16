<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-17 — ONS per-plant generation connector + ADR-0007

**Landed**

- `docs/decisions/ADR-0007-hydro-backcast-interim.md` — the decision this
  connector exists to serve: constrain hydro with observed generation as an
  **explicitly-labelled interim backcast**, while real water values (SDDP)
  proceed separately. Written *before* the data is used, because what the
  resulting model may and may not claim is the whole point.
- `rules/fetch.smk::fetch_ons_geracao_usina` — sixth connector, year+month
  wildcarded like `fator_capacidade`, reusing `scripts/fetch.py` unchanged.
- `docs/data-dictionary/ons/geracao_usina.yaml` — built from all 12 months
  (6,089,616 rows), following PR-15's lesson.
- `test/fixtures/ons/geracao_usina_sample.csv` — 48 real rows spanning all
  four subsystems, both matching and non-matching modalidades, a thermal
  row, and a real null.
- All 12 months of 2024 fetched for real (760 MB, ~77s).
- 9 new tests (191 total).

**Key files:** `docs/decisions/ADR-0007-hydro-backcast-interim.md`,
`docs/data-dictionary/ons/geracao_usina.yaml`.

**The load-bearing finding: population mismatch, caught by a sanity check
rather than by trusting the ratio.**

The obvious way to constrain hydro is `p_max_pu = observed generation /
installed capacity`. Computing that naively for January 2024 gives
subsystem `S` a ratio of **1.021** — physically impossible, and the kind of
number that clipping to 1.0 would have silently hidden.

The cause is not measurement noise (unlike `fator_capacidade`'s ~1.02, which
genuinely is). It is that **the numerator covers more plants than the
denominator**: this dataset includes `Pequenas Usinas (Tipo III)`, `TIPO
III` and `Pequenas Usinas (MMGD)`, while `capacidade_geracao` (PR-07)
covers only ONS-dispatched `TIPO I`/`II-A`/`II-B`/`II-C`.

Filtering the generation side to the same four modalidades brings every
subsystem below 1.0, verified across all four:

| subsystem | unfiltered ratio | filtered ratio |
|---|---|---|
| N | 0.467 | 0.465 |
| NE | 0.619 | 0.609 |
| S | **1.021** | 0.931 |
| SE_CO | 0.849 | 0.816 |

**Filter, do not clip.** Clipping would have produced a plausible-looking
profile that quietly overstated `S`'s hydro availability all year.

**Verified against reality, not just asserted:**

- Fetched all 12 months via the actual Snakemake rule; January's sha256
  matched an earlier direct download byte-for-byte (seventh confirmation of
  deterministic ONS fetches).
- The modalidade table above was computed from real January data across all
  four subsystems, not inferred from the field description.
- `val_geracao` has real nulls (1,488 in January, all `NUCLEAR`; 0.29% over
  the full year) — checked rather than assumed to be zero-filled.

**Gotchas**

1. **Three ONS datasets now use two different technology spellings.**
   `geracao_usina` and `capacidade_geracao` say `HIDROELÉTRICA`/`TÉRMICA`;
   `fator_capacidade` says `Eólica`/`Solar`. There is now a test pinning
   this specific dataset's spelling, so a future "let's share one
   `TECHNOLOGY_MAP`" refactor cannot silently assume they agree.
2. **Nulls are genuinely missing, not zero.** All observed nulls are
   `NUCLEAR` rows. PR-18 must decide explicitly — for hydro specifically
   there were none, so it does not block the immediate work.
3. **Raw values use scientific notation** (`0E-8`); pandas handles it, but
   don't be alarmed reading the CSV directly.
4. **760 MB for one year.** Fine, but this and `fator_capacidade` (445 MB)
   mean `resources/ons/` is now over 1.2 GB. All gitignored; only the 12
   provenance records are committed.

**Dead ends**

None. `geracao-usina-2` was already noted during PR-07's search, so this
was a confirmation lookup. One transient HTTP 403 from the CKAN API
resolved by sending a normal User-Agent header — worth knowing if the API
starts refusing scripted calls.

**Next PR needs (PR-18: hydro backcast profile + ballpark check)**

- `scripts/build_hydro_availability.py` (or extend `build_availability.py`
  — probably separate, since the filtering rule and source dataset differ):
  filter to `HIDROELÉTRICA` **and** matching modalidades, sum generation per
  `(subsystem, hour)`, divide by `generators_t0.csv`'s hydro `p_nom`, and
  emit the same `(snapshot, subsystem, carrier, p_max_pu)` shape
  `attach_availability()` already consumes. It should slot straight into the
  existing `attach_availability()` with no network-side change.
- **Add the backcast caveat to `KNOWN_LIMITATIONS`** — ADR-0007 makes this
  an obligation, not a nicety.
- **The pass/fail signal is `all_prices_zero` flipping to `false`** (PR-16).
  If it stays `true`, hydro is still not binding and something is wrong.
- **Then the actual ballpark check the user asked for:** compare resulting
  annual generation share by carrier against ONS's own published 2024 mix.
  This is a fair test *because* the comparison target (annual aggregate) is
  far coarser than the input (hourly per-subsystem hydro profile), and
  thermal/wind/solar dispatch remain genuine model outputs. Expect thermal
  to be the interesting number — Brazil's real 2024 thermal share is the
  thing this model has been unable to say anything about at all.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether the same observed-generation approach should also replace
  `fator_capacidade` for wind/solar. Probably not: `fator_capacidade` is a
  purpose-built capacity-factor dataset with the denominator already
  matched, whereas this one needs the modalidade filter to be trustworthy.
  Two sources, two purposes — but worth revisiting if they disagree
  materially for wind/solar.
