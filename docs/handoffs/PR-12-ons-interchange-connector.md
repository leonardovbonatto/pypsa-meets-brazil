<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-12 — ONS interchange connector + ADR-0006

**Landed**

- `docs/decisions/ADR-0006-t0-transfer-representation.md` — the modelling
  decision this PR exists to support: T0 gets PyPSA `Link` components
  (transport model), not `Line`s, with topology and a transfer-capacity
  proxy both sourced from real ONS interchange data rather than assumed.
  Real impedances stay assigned to ADR-0003, T3 only.
- `rules/fetch.smk::fetch_ons_intercambio_nacional` — a fourth connector,
  reusing `scripts/fetch.py` unchanged, year-wildcarded like `curva_carga`
  and `cvu_usina_termica`.
- `docs/data-dictionary/ons/intercambio_nacional.yaml` — real dictionary
  from the real 35,136-row 2024 file.
- `test/fixtures/ons/intercambio_nacional_sample.csv` — 96 real rows (24h
  × 4 boundaries), both flow directions represented.
- 8 new tests (138 total).

**This PR stops at fetch + dictionary + the modelling decision itself.**
Turning the interchange data into actual `Link` capacity values and
attaching them to `resources/networks/t0.nc` is PR-13 — same fetch-then-build
split as PR-07/08 (capacity) and PR-09/10 (cost).

**Key files:** `docs/decisions/ADR-0006-t0-transfer-representation.md`,
`docs/data-dictionary/ons/intercambio_nacional.yaml`.

**Data dictionaries added:** `docs/data-dictionary/ons/intercambio_nacional.yaml`.

**Verified against reality, not just asserted:**

- Fetched via the actual Snakemake rule; sha256 matched an earlier direct
  download byte-for-byte (fifth confirmation of stable, deterministic ONS
  fetches this project, after PR-04/06/07/09).
- **The topology claim in ADR-0006 is read from the data, not assumed.**
  Grouped the real 2024 file by `(id_subsistema_origem, id_subsistema_destino)`
  and got exactly four pairs with data: `N-NE`, `N-SE`, `NE-SE`, `SE-S`. No
  `N-S`, no `NE-S`. This is the actual reason PR-13 will build four `Link`s,
  not six (a complete graph) or some other count picked for convenience.
- Confirmed the sign convention empirically rather than trusting the field
  name alone: each boundary's `val_intercambiomwmed` takes both positive and
  negative values across the year (e.g. `N-SE` ranges −4812 to +10492
  MWmed), confirming it really is signed net flow, not an unsigned
  magnitude — material for PR-13, which must take `max(abs(min), abs(max))`
  per boundary, not `max(value)` alone, or it would understate the capacity
  needed in the less-common flow direction.

**Gotchas**

1. **ONS's own dictionary JSON lists a field, `val_intercambioprogmwmed`
   (scheduled/programmed interchange), that is not a column in the actual
   CSV.** Third time this exact pattern has appeared (`capacidade_geracao`
   had `id_ons`, PR-07; this one has this) — ONS's published data
   dictionaries are not fully reliable against the real files often enough
   that it's now an expected check, not a surprising one. Keep building
   schemas from the real file, never from the dictionary text.
2. **The topology is not a complete graph, and that's real, not a data
   gap.** It would have been easy to assume all six subsystem pairs should
   get a `Link` "for completeness." The data says otherwise, and ADR-0006's
   alternatives-considered section records rejecting that explicitly.

**Dead ends**

None. `intercambio-nacional` matched on the first `package_list` search
(`intercambio` as the search term) — PRIMER §2.4 already named "Subsystem
interchange" as a known-available dataset, so this was a confirmation
search, not a blind one.

**Next PR needs (PR-13: T0 transfer links)**

- `scripts/build_links.py`: reduce the real interchange series to one
  `(bus0, bus1, p_nom)` row per boundary — `p_nom = max(abs(min), abs(max))`
  of `val_intercambiomwmed` over the fetched year(s), per ADR-0006. Map
  `SE` → `SE_CO` (reuse `scripts/_ons.py`, applied to both
  `id_subsistema_origem` and `id_subsistema_destino`).
- `build_network.py::attach_links()`: `n.add("Link", ..., bus0=..., bus1=...,
  p_nom=..., p_min_pu=-1, p_max_pu=1)` per row, plus registering whatever
  carrier is used for the links (probably `"AC"`, reusing the existing bus
  carrier, or a dedicated `"transfer"` carrier — worth a real decision, not
  a default, given the PR-06/PR-11 pattern of carrier-registration gotchas).
- **Re-run the PR-11 solve after attaching links and check `S`'s
  `load_shedding` drops to (near) zero.** `SE_CO-S`'s capacity proxy
  (6902.4 MW, from ADR-0006's own numbers) is far larger than `S`'s 202.6 MW
  shortfall, so this should resolve cleanly — worth confirming rather than
  assuming, same discipline as every other PR this session.
- Also worth checking after linking: does `N`'s stranded hydro (PR-11's
  other finding — 65% of `N`'s hydro capacity unused) get exported now that
  `N-NE` and `N-SE` links exist? This is the more interesting question,
  since `N`'s capacity is genuinely enormous relative to its own demand.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- The ADR index's "Planned (PR-NN)" annotations for ADR-0002/0003/0004/0005
  reference the *original* 43-PR roadmap numbering from `Brazilian-Grid-in-PyPSA.md`
  (written before any implementation), which has now diverged from this
  session's actual PR-01…PR-12 sequence. Not reconciled in this PR — noting
  it so nobody is confused why "ADR-0003, Planned PR-07" doesn't match this
  session's actual PR-07 (which was the capacity connector, unrelated to
  transmission impedance).
