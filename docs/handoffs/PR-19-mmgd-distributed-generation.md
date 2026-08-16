<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-19 — MMGD distributed generation

**Landed**

- `scripts/build_mmgd.py` — MMGD capacity and hourly availability per
  subsystem, from observed generation already in `geracao_usina`. No new
  connector needed.
- `rules/build.smk::build_mmgd_t0`; `build_network.py` concatenates MMGD
  into the existing generator and availability frames, so
  `attach_generators()` and `attach_availability()` are **unchanged**.
- 9 new tests (210 total).

## The result

PR-18 predicted this would close the thermal gap. It did, almost exactly.

| | before | after | observed | |
|---|---|---|---|---|
| **thermal** | 13,082 | **7,977** | 8,161 | 1.60× → **0.98×** |
| load shedding | 146,563 MWh | **0** | 0 | |
| price, N/NE/SE_CO | 591 | 453 | | |
| price, S | 712 | 456 | | |
| S premium | 121 | **3** | | |
| total generation | 78,943 | 78,943 | 79,310 | 1.00× |

**Thermal is now within 2.3% of observed**, from 60% high. MMGD came in at
5,126 MW mean against a 4,921 MW thermal excess — the arithmetic PR-18
predicted.

Two secondary effects worth noting, both explainable:

- **Load shedding fell to exactly zero.** It was 146,563 MWh, concentrated
  where local supply was short. 12.9 GW of MMGD peak in `SE_CO` and 5.9 GW
  in `S` removed the shortfall.
- **The S price premium collapsed from 121 to 3 R$/MWh.** That premium was
  the signature of a congested `SE_CO`–`S` link (PR-16's reading of the
  duals). With `S` supplying 5.9 GW locally, the link stops binding and
  prices converge — which is the dual behaving exactly as PRIMER §3.4 says
  it should.

## Two modelling choices, neither inferable from the data

1. **`p_nom` = peak observed output**, not installed capacity. Real
   installed MMGD is substantially higher — a distributed fleet spread
   across a continent never peaks simultaneously. Peak-observed is the
   smallest capacity consistent with the data, which is the honest choice
   when the true figure isn't in this dataset. ANEEL's MMGD registry has
   real installed capacity if a later PR wants it.
2. **Carrier is `solar_mmgd`, distinct from `solar`.** Utility-scale and
   behind-the-meter PV differ in siting, profile and who dispatches them.
   Collapsing them would hide that and make comparison against ONS's own
   breakdown harder.

Both are backcasts under ADR-0007's principle: MMGD output is a model
input, not a model result. It could reasonably have had its own ADR;
recorded here and in the module docstring instead, since it applies an
existing decision rather than making a new one. Worth promoting to an ADR
if MMGD ever moves off the backcast.

## The critical check that came first

**Is verified load gross or net of MMGD?** PRIMER §2.8 says MMGD "appears
as reduced load", which would mean `curva_carga` is *net* — and adding MMGD
as generation would double-count 5 GW.

Checked rather than assumed:

```
mean verified load (curva_carga):      78,943 MW
mean total generation (all plants):    79,310 MW
difference:                               366 MW
mean MMGD generation:                   5,126 MW
```

If load were net of MMGD, `generation − load` would be ≈5,126 MW. It's 366.
So load and total generation share a basis, and adding MMGD is correct.
**This was the single highest-risk step in the PR** and it took one script.

## Gotchas

1. **The gross/net question above.** Any future distributed-generation work
   must re-ask it rather than inheriting this answer, because the answer
   depends on which load series is used, not on MMGD.
2. **MMGD is 100% `FOTOVOLTAICA`** in 2024 — but `filter_mmgd()` filters on
   *modalidade*, not technology, so it won't silently drop MMGD wind or
   biogas if ONS starts reporting it.
3. **The committed `geracao_usina` fixture has no MMGD rows**, so
   `test_build_mmgd.py` builds its data inline rather than carving a
   fixture. Deliberate: the arithmetic needs to be checkable by eye, and a
   real fixture would have made the assertions opaque.

## What this exposed next

**Utility solar is now the largest remaining discrepancy**, and it points
the other way:

- Model utility `solar`: 4,816 MW
- Observed total solar: 8,360 MW, of which MMGD is 5,126 → **utility ≈ 3,234 MW**
- Model is roughly **1.5× high** on utility solar

That's new information. It suggests `capacidade_geracao`'s ~21 GW of solar
capacity is larger than the fleet `fator_capacidade` actually measures
capacity factors for — so applying those factors to that capacity
over-generates. Worth checking before it's mistaken for a modelling error
elsewhere. Hydro remains ~5.5% under observed for the known
modalidade-filter reason (PR-18).

These partly offset, which is why the total still matches to 0.5% — worth
knowing, because offsetting errors look like accuracy.

## Next PR needs

- **Consolidation** was the agreed next step after MMGD (option 3 of the
  PR-18 decision list): no new capability, validate what exists. The
  utility-solar discrepancy above is now the obvious first target.
- Then **water values** (SDDP). One finding from a preliminary
  investigation, worth recording: **ONS publishes ENA and EAR as open
  CC-BY data** — `ena-diario-por-subsistema` covers **2000–2026** (27
  years, daily) and `ena-diario-por-ree` / `ear-diario-por-ree` cover
  2016–2026. That means a REE-level SDDP may not be blocked on NEWAVE deck
  availability or `inewave` at all. 27 years is far short of `VAZOES.DAT`'s
  ~95, which matters for drought persistence (PRIMER §4.7) — a real
  tradeoff for that epic's ADR, not a decision to make here.

## Open questions

- **Roraima is now connected to the SIN (January 2026)** — reported by the
  project owner. This finally closes an eight-handoff open question, but as
  a *time-dependent* answer: correctly out of scope for the 2024 reference
  year, in scope from 2026 data onward. Unverified in-repo; worth
  confirming whether ONS gives it its own `id_subsistema` or folds it into
  `N`, since every connector currently assumes exactly four codes and would
  fail loudly on a fifth.
- Whether `p_nom` for MMGD should come from ANEEL's registry rather than
  observed peak, once anything depends on MMGD headroom rather than its
  output.
