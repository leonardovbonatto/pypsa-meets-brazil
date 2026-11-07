<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-74 — EPE nodal network loader, local only (ADR-0026)

Phase 5 starts. `scripts/epe_network.py` (`rule epe_network`, not in
`all`) reads 8 files of EPE's BaseDadosGT at the pinned commit from
`~/epe_local/raw` and writes tidy buses, lines, transformers and HVDC
links plus a report under git-ignored `resources/epe/`. Committed: code,
tests on synthetic text, and `resources/_provenance/epe/basedadosgt_network.json`
(file hashes). Nothing derived from EPE's data is committed.

## Measured

| | |
|---|---|
| buses / lines / transformers / HVDC lines | 13,188 / 10,836 / 7,365 / 16 |
| buses with a state | 99.98% (name 81.7%, then transformer and line neighbours); 100% at 230 kV and up |
| buses with coordinates (`gcbus`) | 44.8% |
| buses with a subsystem | 99.2%; unmapped: DC buses (66), Itaipu 50 Hz (12), 4 tiny systems |
| median line reactance | 138 kV 3.3 ohm, 230 kV 14.7, 500 kV 30.4, 765 kV 23.6: % on 100 MVA confirmed |
| lines without rating (99999) | 1,159 |
| `Existing` flag | 10,557 = 0, 279 = 1 (sample: G.ARAN, P.DUTR, BESPER in MA): 1 looks like planned |

HVDC (MW per pole): Itaipu F.IG 4 x 1,566; Madeira 4 x 1,575 + two
400 MW back-to-back; Belo Monte XINGU/XIN02 4 x 2,000; G.ARAN 2 x 2,500
(probably the planned Graca Aranha link).

## Gotchas

- State propagation needs lines as well as transformers: 106 high-voltage
  series-capacitor buses (`...CAP500`) touch no transformer.
- Line lengths are all zero; reactance carries the electrical length.

## Next PR needs

- Confirm the `Existing` flag against EPE's other files, then
  `build_network_t3`: PyPSA Lines (x, r in ohm from % on 100 MVA),
  Transformers, HVDC as Links; connectivity and islands checked.
