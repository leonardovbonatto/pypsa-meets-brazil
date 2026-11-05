<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-53 — EPE interchange loader, local only (plan steps 2-3)

**Landed:**

- `scripts/epe_interc.py` — parses `interc.dat` and `minterc004.dat` from a
  local BaseDadosGT copy and cross-checks them against `links_t0.csv`.
- `rules/build.smk::epe_interc`, not part of `all`; `config.epe` holds the
  local folder (`~/epe_local/raw`), repository URL and pinned commit
  `5168bba0`.
- `resources/_provenance/epe/basedadosgt_interc.json` — URL, commit, SHA-256
  of both files. **The only committed artefact derived from EPE.**
- `test/test_epe_interc.py` — 5 tests on synthetic text in EPE's layout.

## Findings

| T0 boundary | T0 p_nom (MW) | EPE bus0→bus1 | EPE bus1→bus0 |
|---|---|---|---|
| NE-SE_CO | 8,311 | 8,500 | 6,000 |
| N-NE, N-SE_CO, SE_CO-S | — | not one-to-one | — |

- NE→SE agrees within 2%. **SE→NE is 6,000 MW in EPE**, so T0's symmetric
  limit (and ADR-0012's) overstates that direction by 39%.
- The North enters through fictitious nodes (IMPERATRIZ, XINGU) and SE-S is
  `99999`, i.e. constrained elsewhere; mapping those needs EPE's other
  constraint files.
- `minterc004.dat` has 881 monthly, per-load-block overrides from 2025; NE→SE
  ranges 8,200-14,004 MW. A planning deck for future years, not a 2024 record.

## Gotchas

- Numbers are right-aligned and spill left past their header markers; only
  the leading text fields (which contain spaces) are cut by column.
- `*` in the block column applies to every load block; parsed as `<NA>`.
- Files are Latin-1.

## Next PR needs

- Directional limits in T0 and SDDP (`p_min_pu` per link), sourced from ONS
  if possible so the published inputs stay ONS-derived.
- EPE's group constraints for SE-S and the North, once the format is known.
