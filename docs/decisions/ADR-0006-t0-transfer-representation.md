<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0006 — T0 inter-subsystem transfer representation

- **Status:** Accepted
- **Date:** 2026-08-13
- **Supersedes:** —
- **Superseded by:** —

## Context

PR-11's first real solve against the 2024 T0 network was infeasible: the `S`
subsystem's own generator capacity falls 202.6 MW short of its own peak hourly
demand, in 2 of 8784 hours, and `N`/`NE` sit on 17,500–41,500 MW of generation
capacity they have no way to use beyond local demand. Both are the same root
cause — the four subsystems are electrically disconnected in the model — and
both are artifacts of that gap, not of the underlying Brazilian grid, which is
obviously interconnected (that is the entire point of the SIN, PRIMER §2.1).

The real fix is transmission. But "real transmission" for a DC-OPF power-flow
model needs line impedances (`x`), and per `Brazilian-Grid-in-PyPSA.md` §2.1
those are **not available in any clean tabular open dataset** — the credible
route is DESSEM/ANAREDE deck parsing, reserved for ADR-0003 (still "Planned,
PR-07" in the index, targeting the T3 nodal tier). That is a multi-week
research task on its own and out of scope for T0.

T0 does not need power flow, though. PRIMER §1.2 draws the relevant
distinction directly: a **transport model** represents regions connected by
transfer limits; a **power flow model** needs real impedances and lets flow
distribute by physics. T0 is explicitly the 4-subsystem zonal tier — a
transport model is the correct level of detail for it, not a compromise.

What is available, and checked directly rather than assumed: ONS publishes
**`intercambio-nacional`** — real hourly interchange between subsystems, MWmed,
signed by direction, 2000–present. Inspecting the real 2024 file shows exactly
four subsystem-pair boundaries with nonzero data: `N-NE`, `N-SE`, `NE-SE`,
`SE-S`. No `N-S` or `NE-S` boundary exists in the data — confirming, rather
than assuming, that the SIN's real topology is a triangle (`N`, `NE`, `SE_CO`
mutually connected) plus a pendant (`SE_CO-S`), not a complete graph. This is
real, current, ground-truth topology, distinct from the capacity question.

What the interchange dataset does **not** give directly is a transfer
*capacity* (a rated limit) — only realized historical *flow* (an outcome).
`ons-aws-prod-opendata`'s dataset list has no dedicated transfer-capacity
resource under an obvious slug (`limite-intercambio` and similar searched,
not found).

## Decision

Model T0 inter-subsystem connections as PyPSA `Link` components, not `Line`
components — a transport model, explicit about not claiming DC power flow.

One `Link` per real observed boundary (four: `N-NE`, `N-SE_CO`, `NE-SE_CO`,
`SE_CO-S`), bidirectional (`p_min_pu = -1`), with `p_nom` set to the maximum
absolute historical flow observed on that boundary in the reference year —
a **documented lower-bound proxy** for true transfer capacity, not the rated
value. If the real grid moved that much power at least once, the true limit
is at least that high; it may well be higher, since 8784 hours may never have
pushed the boundary to its actual limit.

## Alternatives considered

- **Unlimited transfer between all four subsystems.** Rejected: defeats the
  purpose of a zonal model, which exists specifically to represent that
  transfer is constrained. Would also silently paper over the very
  infeasibility that motivated this ADR, rather than resolving it honestly.
- **A fully connected graph (all 6 possible subsystem pairs).** Rejected: the
  real interchange data shows only 4 boundaries carry nonzero flow. Adding
  the other 2 would be inventing topology the grid does not have.
- **A fabricated round-number capacity** (e.g. "5000 MW between every pair").
  Rejected outright: no basis, and this project's own discipline
  (`docs/PRIMER.md` §7) is explicit about not presenting invented numbers as
  if they were researched ones.
- **Wait for a real transfer-capacity dataset or DESSEM impedances before
  adding any interconnection.** Rejected as the default for T0 specifically:
  it would leave the known, understood infeasibility from PR-11 unresolved
  indefinitely, for a nodal-tier data requirement T0 does not actually have.
  Real impedances remain the right choice for T3 and stay assigned to
  ADR-0003.

## Consequences

**Positive.** Resolves the PR-11 infeasibility with a real, checkable,
documented number instead of an open-ended slack. Topology (which subsystems
connect to which) is ground-truth, not assumed. Every number is traceable to
`docs/data-dictionary/ons/intercambio_nacional.yaml` and a specific historical
year.

**Negative.** Capacity is a proxy, not a rating — it can understate real
transfer capability (the grid may support more than it was ever asked to
carry in one year) or, less likely, be tight against a growth trend if newer
years see materially higher exchange. `p_min_pu = -1` bidirectionality
ignores that real transfer limits are sometimes directional and asymmetric.

**Risk.** Anyone reading `n.links` from `resources/networks/t0.nc` without
reading this ADR or the data dictionary could mistake the proxy for a
researched rated capacity. Mitigated by stating it explicitly in the link
build script, the data dictionary's notes, and the relevant handoff — the
same pattern already used for `NON_THERMAL_MARGINAL_COST` (PR-10) and
`LOAD_SHED_COST` (PR-11). Superseding this ADR is the expected outcome once
either a real ONS transfer-capacity dataset is found or T3's impedance work
(ADR-0003) makes a physics-based limit derivable.
