<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-15 — T0 availability profile

**Landed**

- `scripts/build_availability.py::build_availability()` — aggregates the
  real capacity-factor data to one hourly `p_max_pu` per `(subsystem,
  technology)`, as `sum(generation) / sum(capacity)` (algebraically a
  capacity-weighted mean, written that way so a 5 MW plant-group can never
  get the same vote as a 500 MW one), clipped to `[0, 1]`.
- `scripts/build_network.py::attach_availability()` — sets `p_max_pu` on
  matching generators. Anything uncovered keeps PyPSA's 1.0 default; the
  only such generator is `SE_CO wind`, documented rather than silent.
- `rules/build.smk::build_availability_t0`; `build_network_t0` now takes a
  fifth input.
- `scripts/solve_network.py::KNOWN_LIMITATIONS` rewritten (see below).
- 16 new tests (179 total).

**Key files:** `scripts/build_availability.py`,
`build_network.attach_availability()`, `scripts/solve_network.py`.

**The main finding: the obvious hypothesis was wrong, and checking a
specific number rather than re-guessing is what settled it.**

PR-13 ended with thermal dispatching at exactly 0 MW for every hour of
2024, and named "no availability profile" as the cause — every generator
assumed at 100% uptime. This PR added *real measured* hourly availability
for wind and solar. It worked exactly as intended: wind's mean dispatch
fell 12,655 → 8,855 MW, solar's 9,865 → 3,705 MW, both now physically
constrained by measured output rather than nameplate.

**And thermal stayed at exactly 0 MW.** Rather than assume a second
explanation, compared the specific capacities against demand:

- National **hydro nameplate alone**: 102,678 MW.
- National **peak demand across all of 2024**: 102,086 MW.
- Hours where national demand exceeds national hydro nameplate: **0 of
  8,784.**

So free, unconstrained hydro can cover every hour of Brazilian demand by
itself, regardless of what wind and solar do. Hydro is untouched by this PR
because `fator_capacidade` is a **wind/solar-only dataset** — hydro is
absent by design, not omission — and PR-14's handoff had already flagged
that hydro's real limit is water availability, not a weather-derived
capacity factor. Verified further at the extremes: at the single
lowest-wind/solar-availability hour of the year (2024-03-01 03:00, mean
availability 0.185), hydro still covers 75,478 MW of 77,946 MW demand with
thermal at 0.

**What this means:** the model cannot say anything meaningful about thermal
dispatch, merit order, or prices until hydro is constrained. That is not
another data connector — it is the water-value problem (PRIMER §4,
SDDP.jl), the hardest single piece of this project.

**Verified against reality, not just asserted:**

Ran `snakemake solve_all` from a clean slate. `resources/availability_t0.csv`
is 43,920 rows (5 real `(subsystem, technology)` pairs × 8,784 hours).
Every number quoted above was read off the solved network directly
(`n.generators_t.p`, `n.generators.p_nom`, `n.loads_t.p_set`), not inferred
from the summary. Hydro utilisation by bus (0.379 NE to 0.721 S) confirms
hydro is doing the work everywhere, not just in one subsystem.

**Gotchas**

1. **A single-month data dictionary was wrong for the full year, and
   pandera caught it.** The PR-14 dictionary was built from January 2024
   alone, where `val_latitudesecoletora` has no nulls — so the derived
   schema marked it non-nullable. The real 12-month frame has 16,848 nulls
   in that column, and `build_availability_t0` failed validation on the
   first real run. Regenerated the dictionary from all 12 months (1,917,720
   rows). **Generalized rule, now in the dictionary's own notes: build a
   dictionary from the same data volume that will actually be validated
   against it.** Worth applying retroactively if any earlier connector's
   dictionary was built from a subset — `curva_carga`, `cvu_usina_termica`
   and `intercambio_nacional` were all built from a full year, so only this
   one was exposed.
2. **`KNOWN_LIMITATIONS` had gone stale and was actively misleading.** Two
   of its five entries claimed "no transmission lines exist yet" (fixed in
   PR-13) and "no availability profile exists yet" (fixed in this PR). A
   caveat naming an already-solved problem is as bad as a missing one — it
   directs attention at the wrong thing. Rewritten to lead with the real
   dominant caveat, and `solve_network.py`'s module docstring now says
   explicitly to keep it current as gaps close.
3. **This dataset's technology spelling differs from `capacidade_geracao`'s**
   (`"Eólica"`/`"Solar"` vs `"EOLIÉTRICA"`/`"FOTOVOLTAICA"`), so
   `build_availability.TECHNOLOGY_MAP` is deliberately its own map rather
   than a reuse of `build_generators.TECHNOLOGY_MAP`. Noted in the code so
   a future refactor doesn't "helpfully" merge them.

**Dead ends**

None, but note the near-miss: it would have been easy to accept "wind and
solar are now constrained, dispatch changed, done" and move on without
noticing thermal never moved. The check that caught it was simply looking
at whether the *intended* effect (thermal becoming economically relevant)
actually happened, not just whether *an* effect happened.

**Next PR needs**

- **Hydro's water value is now the single blocking issue** for any
  economically meaningful T0 result, and it is a large one. PRIMER §4 and
  the roadmap both scope it as PAR(p) inflow modelling + SDDP.jl producing
  Benders cuts, coupled into PyPSA via linopy — a multi-PR epic, not a
  connector. Worth an ADR before implementation starts.
- A **much cheaper interim** worth considering first, and explicitly a
  simplification rather than a solution: constrain hydro with a real
  observed profile the same way wind/solar now are. ONS publishes hourly
  generation per plant (`geracao-usina-2`, seen during PR-07's search),
  which for hydro would give a realized-output profile — that would make
  thermal dispatch nonzero and the model's merit order at least
  directionally sensible, while being explicitly *backcasting* (using
  observed output as an input) rather than *optimising* water use. If
  taken, this must be documented very clearly as such, since using observed
  generation as a constraint and then validating against observed prices
  edges toward the self-validation failure mode PRIMER §7.2 warns about.
- Either way, `n.buses_t.marginal_price` remains meaningless until hydro is
  constrained: with a zero-cost generator setting the margin in every hour,
  every subsystem's price is 0.

**Open questions**

- Still open from PR-06/08/10/11: isolated systems (Roraima).
- Whether `SE_CO wind` (~261 MW, 0.3% of `SE_CO` capacity, no data in this
  dataset) should stay at `p_max_pu = 1.0` or borrow another subsystem's
  wind profile. Left at 1.0 deliberately for now — it is small enough not
  to matter, and borrowing a profile from a different wind regime would be
  inventing data rather than defaulting transparently.
