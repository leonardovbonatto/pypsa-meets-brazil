<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-20 — Wind/solar capacity-factor coverage gap (consolidation)

**Landed:** no code change. A quantified, documented finding — the first
consolidation-phase PR, chasing PR-19's flagged "utility solar ~1.5x high"
discrepancy to a specific, numeric root cause.

## The finding

`fator_capacidade` (PR-14/15's wind/solar capacity-factor source) only
covers a subset of the nameplate capacity that `capacidade_geracao`
(PR-07's capacity source) lists, and `build_network.py` applies the
former's fleet-average `p_max_pu` to the latter's full nameplate — no
existing code was wrong, but the two datasets were never checked against
each other for population match, the same class of gap already found once
for hydro (PR-17/18) and MMGD (PR-19).

Computed by joining unique `cod_pontoconexao` plant-groups (fator_capacidade)
against active per-plant rows (capacidade_geracao), both mapped through
`_ons.map_subsystems()`:

| | capacidade_geracao (nameplate) | fator_capacidade (tracked) | coverage |
|---|---|---|---|
| solar | 21,312 MW (1,189 plants) | 10,273 MW (44 plant-groups) | 48% |
| wind | 33,721 MW (2,152 plants) | 14,582 MW (70 plant-groups) | 43% |

Per-subsystem, the gap is worst exactly where capacity is concentrated:
NE wind is 30,765 MW nameplate vs 12,210 MW tracked (40%). SE_CO wind is
the extreme case, already known since PR-14: 261 MW nameplate, 0 MW
tracked (documented then as a SE_CO-specific quirk; now understood as the
tail of a general pattern).

`fator_capacidade`'s own `nom_modalidadeoperacao` breakdown shows why:
it's almost entirely `"Conjunto de Usinas"` (grouped connection points),
while `capacidade_geracao` lists individual `TIPO II-C` plants. Same
registry-vs-dispatch mismatch already documented for `geracao_usina`
(PR-17/18) — but there it under-counted *generation*; here it
under-counts *capacity coverage*.

## Why this wasn't fixed here

There's no better per-plant capacity-factor source currently connected —
the same reason CVU (PR-10) aggregates to one number per subsystem rather
than attempting a per-plant join. Two real options exist for a future PR,
neither attempted now because both are judgment calls, not
documentation:

1. Cap wind/solar `p_nom` to the tracked ~43-48% instead of full
   nameplate — physically wrong (real plants exist and can generate) but
   removes the extrapolation.
2. Find a second capacity-factor source (ANEEL, atlite/ERA5 once
   unblocked) covering the untracked plants and blend it in.

Both change the network's behavior, not just its documentation — out of
scope for a consolidation PR whose job is to validate what exists.

## What changed

- `scripts/solve_network.py::KNOWN_LIMITATIONS` — the wind/solar entry
  now states the coverage numbers and names this as the likely cause of
  PR-19's utility-solar overshoot.
- `docs/data-dictionary/ons/fator_capacidade.yaml` — new note
  generalizing the PR-14 SE_CO-wind observation into the full finding,
  with the coverage numbers and methodology so a future session can
  re-derive them.

No test changes: nothing computed here is production code, so nothing to
assert against in CI. If a future PR acts on this (option 1 or 2 above),
that PR should add the population-match check as real code with tests,
the same way PR-18 turned the hydro finding into `MATCHING_MODALIDADES`.

## Next PR needs

- Still open from PR-19: Roraima's Jan-2026 SIN connection (unverified
  in-repo), `meta.yml`'s CI trigger (`pull_request`-only, never fired).
- This finding plus PR-18/19's hydro/MMGD findings together suggest a
  standing lesson worth stating once, generally, rather than re-deriving
  per-dataset: **any two ONS datasets joined by subsystem/technology
  should have their populations checked before assuming one's ratio
  applies to the other's totals.** Worth a short note in `docs/PRIMER.md`
  or `ADR-0001` if a fourth instance of this pattern turns up.
- After consolidation: real water values (SDDP), per the user's agreed
  step 2. See PR-19 handoff for the ENA/EAR open-data preliminary finding.

## Open questions

- Whether ANEEL's own registry (rather than ONS's dispatch-tracking
  datasets) would give better capacity-factor coverage for the untracked
  ~52-57% of wind/solar nameplate — unresearched.
