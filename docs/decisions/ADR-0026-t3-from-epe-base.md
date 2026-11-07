<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# ADR-0026 — T3 nodal network from EPE's G+T base; T1 by clustering it

- **Status:** Proposed
- **Date:** 2026-11-06
- **Supersedes:** ADR-0022's topology source (DLR corridors); ADR-0003's
  open question on where impedances come from
- **Superseded by:** —

## Context

The roadmap's architecture is one source of truth clustered downward,
T3 -> T2 -> T1 -> T0 (`Brazilian-Grid-in-PyPSA.md` §5). PR-66..71 built T1
on DLR's corridors instead, a shortcut the project lead rejected
(2026-11-06): the 27-state tier must come from clustering the nodal network.

EPE's integrated G+T base (`EPE-GOV-BR/BaseDadosGT`, pinned `5168bba0`)
holds the network in PSR's comma-separated `.dat` layout. Measured
2026-11-06 on a local copy:

| file | content |
|---|---|
| `dbus.dat` | 13,188 buses: code, name, system, area, base voltage |
| `dcirc.dat` | 10,836 circuits: buses, R, X, B, rating, emergency rating |
| `dtrans.dat` | 7,365 transformers: buses, R, X, tap limits |
| `ddcbus`, `ddcline`, `dcnvlcc`, `dmtdclink` | HVDC: 66 DC buses, 17 lines, 33 converters |
| `gcbus.dat` | latitude and longitude for 5,905 buses |
| `dload.dat` | 3,471 load points by bus |

The state is in most bus names (`PROSPE-BA230`): 81.7% of buses, 93% of
those at 230 kV and above; 44.8% have coordinates; 4% have neither (mostly
generator terminals at 13.8-34.5 kV, connected to a named bus through a
transformer). `System` maps onto subsystems (1 SE/CO, 2 S, 3 NE, 4 N, 6
Acre-Rondonia, 7 Manaus-Amapa-Roraima, others small). Impedances read as %
on 100 MVA (a typical 500 kV line X = 1.2%, about 30 ohm); this is checked,
not assumed, in the loader. Line lengths are all zero; some ratings are the
99999 placeholder.

The base has no licence file (memory `epe-base-gt`): the project's rule is
that EPE data stays local - raw, parsed or derived - and only code and
provenance are committed.

## Decision

1. **T3 is EPE's base**, read from the local copy at the pinned commit. All
   EPE-derived outputs (tidy tables, networks, clustered networks, results)
   live under git-ignored `resources/epe/` and `results/`; only code,
   provenance (URL, commit, hashes) and aggregate findings in handoffs are
   committed. CI uses synthetic fixtures in the same layout.
2. **Bus state**, in order: the name's `-UF###` suffix; else the state of
   the bus it shares a transformer with (repeated until stable); else the
   coordinates (point in state polygon, a later step). Remaining buses are
   reported, never guessed.
3. **Bus subsystem** from `System`, through an explicit, checked map.
4. **T1 is T3 clustered to (state, subsystem) nodes** (ADR-0022's node
   rule kept), with PyPSA's clustering; DLR becomes a benchmark only.
5. This deck is a planning base built from 2025 data, not a 2024 record;
   its `Existing` flag is read and reported before any year is modelled.

## Consequences

**Positive.** One network for every tier; real impedances and ratings;
HVDC explicit (Belo Monte, Madeira, Itaipu), which the N-boundary failures
point at.

**Negative.** T3 results cannot be published while the licence is
unresolved; the deck's vintage (2025+) does not match 2024.
