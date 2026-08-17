<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-34 — ADR-0008: REE-level individualization (SDDP epic, stage 2)

**Landed:** no code. `docs/decisions/ADR-0008-ree-level-individualization.md`,
plus a precise (not blanket) update to ADR-0005's "Superseded by" field.

## The framing correction this ADR opens with

PRIMER §4.6 literally says "REE first, individualized second." ADR-0005
built the epic's first stage at **subsystem** level (4 nodes), which is
coarser than REE - a real, deliberate simplification at the time (match
T0's granularity, no new data source), but it meant this project had not
actually taken PRIMER's own named first individualization step. Caught
this while drafting the ADR, before it became a silent "individualized
reservoirs now means skip straight to 150+ plants" scope creep.

## What was checked before deciding, not assumed

Same discipline ADR-0005 applied to Julia and ENA: live-checked whether
ONS publishes REE-level data before deciding to build on it.

- `ena_ree_di` / `ear_ree_di` are real, found via the same
  S3-prefix-listing method as PR-27/30 (no CKAN). **12 real REEs**:
  BELO MONTE, IGUACU, ITAIPU, MADEIRA, MANAUS-AMAPA, NORDESTE, NORTE,
  PARANA, PARANAPANEMA, SUDESTE, SUL, TELES PIRES.
- ENA-per-REE covers 2016-2026 - shorter than subsystem-level's
  2000-2025 (PR-27), a second, smaller instance of the same
  record-length tradeoff ADR-0005 already accepted once.
- **No REE-to-subsystem mapping column in either dataset.** The names are
  domain-recognizable (Amazon-basin complexes vs. S/SE_CO river names)
  but this is inference, not a confirmed join key - named as the
  connector PR's first job, not resolved here.
- **A real, unexplained data quirk, found in the first sample rows**:
  MADEIRA's `ear_verif_ree_mwmes` on 2024-01-01 is **-9.166** - negative
  stored energy, which cannot be physical. Different failure mode from
  PR-30's subsystem-level EAR quirk (storage *exceeding* capacity, not
  going negative) - flagged for direct investigation, not assumed to
  clip the same way PR-30's did.

## Why not go straight to full per-plant individualization

The real reason, not just "smaller is safer": full individualization
needs `hidr.dat` and `VAZOES.DAT` from NEWAVE decks via `inewave`, and
**deck access has never been checked in this project** - unlike Julia
(PR-26), ENA (PR-27), and EAR (PR-30), each of which was verified live
before being relied on. Committing to per-plant individualization now
would repeat exactly the mistake the epic has avoided everywhere else:
building toward a destination before confirming the path there is open.
ADR-0008 says so explicitly and gates the eventual per-plant ADR on
checking deck access first.

## Key files

- `docs/decisions/ADR-0008-ree-level-individualization.md` - the decision.
- `docs/decisions/ADR-0005-inflow-model-formulation.md` - "Superseded by"
  field updated precisely: only the individualization-stage part of
  ADR-0005 is superseded. Its inflow-data-source choice (ENA over
  VAZOES.DAT) and PR-26's coupling mechanism are unaffected and remain
  the active decision - not a blanket "Superseded" status, which would
  have incorrectly implied the whole ADR was invalidated.
- `docs/decisions/README.md` - index updated.

## Gotchas

- ADRs are immutable once accepted (this project's own README says so).
  Editing ADR-0005's "Superseded by" field is the sanctioned exception,
  not a violation - the README's own template says exactly this field
  gets updated when a real superseding ADR lands. Left every other
  section of ADR-0005 untouched.

## Next PR needs

1. **REE connectors** (`ena_ree`, `ear_ree`) - same fetch → dictionary →
   tidy shape as every ONS connector so far. Resolve the REE-to-subsystem
   mapping and investigate the negative-EAR quirk as part of this PR.
2. **Refit PAR(1) persistence and spatial correlation at REE level**
   (12×12 correlation matrix) - PR-28/29's subsystem-level work does not
   carry over automatically.
3. **A REE-level SDDP policy** with an explicit REE→subsystem allocation
   for the demand balance, since demand and thermal stay at subsystem
   level while hydro moves to REE level - a real new modelling seam.
4. Independently: **temporal persistence inside the policy** (PR-33's own
   flagged next step) can land before or after REE individualization -
   the two are not sequenced by this ADR.

## Open questions

- Whether the negative EAR quirk is a MADEIRA-specific one-off or common
  across REEs - unknown until the connector PR pulls the full volume.
- Where an authoritative REE-to-subsystem mapping actually lives (an ONS
  technical publication, inferred from geography, or ANEEL's registry) -
  unresearched beyond the domain-name inference above.
