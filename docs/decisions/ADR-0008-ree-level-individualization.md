<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0008 — REE-level individualization (SDDP epic, stage 2)

- **Status:** Accepted
- **Date:** 2026-08-17
- **Supersedes:** ADR-0005 (individualization stage only - ADR-0005's
  inflow-source and coupling-mechanism decisions stand unchanged)
- **Superseded by:** — (expected: a future ADR for full per-plant
  individualization, once NEWAVE deck access is verified - see
  Consequences)

## Context

ADR-0005 built the SDDP epic's first stage at **subsystem** level (4
nodes, matching T0's own granularity) and named its own destination:
PRIMER §4.6, "Get SDDP converging on the aggregated (REE) formulation
before attempting 150+ individualized reservoirs." PR-26 through PR-33
delivered that subsystem-level stage in full - coupling mechanism, real
ENA/EAR data, PAR(1) persistence and spatial correlation, a working
expectation and CVaR policy, real convergence checking. PR-33's own
finding (temporal persistence, not capacity, is the likeliest lever on
S's remaining tail risk) and the plan's own next step both point the same
direction: it is time to decide the individualization stage properly,
not just gesture at it.

**A framing correction, caught before it became a silent scope-skip**:
PRIMER §4.6 says "REE first, individualized second" - **REE**, not
subsystem. ADR-0005's subsystem-level choice was a real, deliberate,
smaller-first simplification (matching T0's granularity, avoiding a new
data source), but it means this project has not yet taken PRIMER's own
named first individualization step. Jumping from subsystem straight to
full per-plant (150-170) individualization would skip REE entirely -
worth naming explicitly rather than let "individualized reservoirs"
quietly mean "go straight to the hardest version."

**What a REE actually is**: a *Reservatório Equivalente de Energia* -
CEPEL/ONS's own real, standard energy-equivalent aggregation of
reservoirs on shared or related basins, used throughout the official
Brazilian planning chain specifically as the intermediate resolution
between subsystem and individual plant (PRIMER §2.4). It is not a
methodology this project would be inventing; it is the one Brazil's own
operator already uses for this exact purpose.

**Checked, not assumed, before deciding**: does ONS publish REE-level
data the same way it publishes subsystem-level ENA/EAR? Yes, found via
the same direct S3-prefix-listing method PR-27/30 used (no CKAN):

- `ena_ree_di`: daily ENA per REE, **12 real REEs** - `BELO MONTE`,
  `IGUACU`, `ITAIPU`, `MADEIRA`, `MANAUS-AMAPA`, `NORDESTE`, `NORTE`,
  `PARANA`, `PARANAPANEMA`, `SUDESTE`, `SUL`, `TELES PIRES`. Same
  columns/shape as `ena_subsistema` (gross/storable × MWmed/%-of-MLT).
  Covers **2016-2026** - real, but a shorter record than
  `ena_subsistema`'s 2000-2025 (PR-27), itself already short of
  `VAZOES.DAT`'s ~95 years (a tradeoff ADR-0005 already accepted once;
  this stage accepts a second, smaller version of the same tradeoff).
- `ear_ree_di`: daily reservoir storage per REE, same shape as
  `ear_subsistema` (`ear_max_ree`, `ear_verif_ree_mwmes`,
  `ear_verif_ree_percentual`).
- **Neither dataset carries a REE-to-subsystem mapping column.** The 12
  REE names are recognizable by domain knowledge (e.g. `BELO MONTE`,
  `MADEIRA`, `TELES PIRES` are Amazon-basin complexes plausibly mapping
  to subsystem N; `IGUACU`, `PARANA`, `PARANAPANEMA` to S/SE_CO; `ITAIPU`
  binational, shared) but this is inference, not a confirmed join key - a
  real, named gap for the connector PR to resolve, not this ADR.
- **A real data quirk found in the first glance at real rows, not
  hidden**: `MADEIRA`'s `ear_verif_ree_mwmes` on 2024-01-01 is **-9.166**
  (negative) - a reservoir cannot physically hold negative stored energy.
  Same general class of "real ONS data needs a real check before use" as
  PR-30's storage-exceeds-capacity clipping, but a different, unexplained
  direction (negative, not over-capacity) - flagged for direct
  investigation in the connector PR, not assumed to be a simple clip.

## Decision

**Stage 2 of the SDDP epic individualizes to REE level (12 reservoirs),
not directly to full per-plant level (150-170).** REE-level data is
real, available, and requires no new access risk (same S3 pattern as
every connector so far). Full per-plant individualization needs
`hidr.dat` (physical cadastre) and ideally `VAZOES.DAT` (95-year inflow)
from NEWAVE decks via `inewave` - **access to those decks has never been
checked in this project**, unlike every other dependency in the SDDP
epic (Julia, ENA, EAR were each verified live before being relied on).
Deciding to go straight to per-plant individualization now would repeat
exactly the mistake ADR-0005 avoided for the epic's first stage:
committing to a destination before checking whether the path there is
open.

This ADR authorizes, in order:

1. **REE connectors** (`ena_ree`, `ear_ree`), same fetch → dictionary →
   tidy shape as every ONS connector so far. Resolve the REE-to-subsystem
   mapping and the negative-EAR quirk as part of this PR, not deferred
   again.
2. **Refit PAR(1) persistence and spatial correlation at REE level**
   (12×12 correlation matrix, not 4×4) - PR-28/29's subsystem-level work
   does not automatically carry over; this is real new fitting, not a
   data swap. Re-run PR-28/29's validation discipline (recover known
   parameters from synthetic data, check historical persistence and
   correlation are plausibly reproduced) at the new granularity.
3. **A REE-level SDDP policy**, structurally the same model PR-31/32/33
   built (hydro-thermal, monthly stages, expectation and CVaR, real
   convergence checking, seeded) but with 12 reservoir states instead of
   4, and an explicit REE→subsystem allocation for how each REE's hydro
   contributes to its subsystem's demand balance - a genuinely new
   modelling seam PRIMER's architecture doesn't specify in detail,
   because demand and thermal stay at subsystem level while hydro moves
   to REE level.
4. Temporal persistence inside the policy (PR-33's own flagged next
   step) can land before or after this stage - the two are independent
   improvements, not sequenced by this ADR.

## Alternatives considered

- **Go straight to full per-plant individualization (150-170
  reservoirs).** Rejected for now, not permanently: PRIMER §4.1's own
  curse-of-dimensionality argument (10 grid points per reservoir over
  150+ reservoirs is 10¹⁵⁰ states) is exactly why REE aggregation exists
  in Brazil's real planning chain in the first place, and §4.6 says so
  explicitly. Compounded by the unverified deck-access risk above -
  attempting the hardest version first, on an unconfirmed data path,
  repeats a mistake this project has specifically avoided everywhere
  else in the epic.
- **Stay at subsystem level indefinitely.** Rejected: leaves real
  within-subsystem hydro diversity uncaptured - the same class of gap
  PR-29 closed once already (independent-subsystem sampling understating
  cross-subsystem risk), one level finer. PRIMER §4.6 names REE as the
  standard next step, not an optional refinement.
- **Invent a different aggregation** (e.g. cluster reservoirs by
  measured correlation rather than use ONS's own REE definitions).
  Rejected: ONS's REEs are the real, standard, operationally-used
  aggregation for exactly this purpose - substituting a self-invented
  clustering would be a fabricated methodology choice with no
  operational grounding, the same failure mode ADR-0007 rejected for a
  fabricated water value.

## Consequences

**Positive.** Follows PRIMER's own named path instead of skipping past
it. Real data confirmed available with no new access risk. Captures real
hydro diversity within today's 4 subsystems that the current model
cannot see. Closer to the resolution Brazil's own operational and
planning tools actually use, which matters for any future comparison
against official CMO/PLD figures.

**Negative.** REE-level ENA/EAR history is shorter (2016-2026, ~10
years) than subsystem-level (2000-2025, ~26 years) - less data for
PAR(1) fitting at exactly the resolution where persistence and
correlation estimates matter more (12×12 correlation entries to estimate
instead of 4×4, from fewer years). The REE-to-subsystem mapping is
unconfirmed and must be resolved from domain knowledge or a
not-yet-located ONS reference, not a clean join key in the data itself.
None of PR-28 through PR-33's subsystem-level fitting/policy work
transfers automatically - this is substantial new engineering at a new
granularity, not a parameter change.

**Risk.** The negative EAR value found in the first real sample (MADEIRA,
-9.166 MWmes) is unexplained - if it turns out to be common rather than a
one-off, it could indicate a real data-quality issue specific to
REE-level EAR that PR-30's subsystem-level connector never encountered
(subsystem EAR's own quirk, PR-30, was values *exceeding* capacity, not
going negative - a different failure mode, not yet understood to have
the same root cause or fix). Must be investigated directly in the
connector PR, not assumed to clip the same way.

**This ADR's own expected successor**: once REE-level is built and
validated, full per-plant individualization (150-170 reservoirs, NEWAVE
decks, `hidr.dat`/`VAZOES.DAT` via `inewave`) is the final named stage in
PRIMER §4.6's progression. Its own ADR must first verify deck access is
actually possible from this environment - the same live check this
project has now applied to every prior dependency in the epic (Julia,
ENA, EAR) - before committing to it as this ADR committed to REE-level
only after confirming REE data was real and reachable.
