<!--
SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# PR-50 — Net load in the SDDP subproblem (ADR-0013)

**Landed:** `monthly_renewables` and `network_renewables` in
`scripts/prepare_sddp_inputs.py` (monthly mean available MW of wind, solar,
rooftop solar and nuclear, read from the built T0 network);
`add_renewables` with free curtailment in both Julia models; 3 tests.

## Result (inflow-state model, serial, 4000 iterations, transmission on)

| | transmission only | + net load |
|---|---|---|
| cost on PAR(1) paths | R$55.97bn | **R$0.47bn** |
| load shed | 21 MW-months | 0 |
| acceptance test | ties | **passes** (S 0.0287 dry vs 0.00068 wet) |
| grid backwards / tied | — | 2.4% / 68% |

Renewables and nuclear average about 25 GW (NE 15.3 GW); NE's monthly net
load is negative from May to December.

**R$0.47bn is not believable**: hydro covered everything and thermal barely
ran, while 2024 ran 6.6 GW of thermal. ADR-0013 named the risk. The missing
piece was thermal that runs whatever the price, added in PR-54 (ADR-0016).

## Gotchas

- `network_renewables` reads `resources/networks/t0.nc`, so the SDDP inputs
  now depend on the T0 build.
- Curtailment is free; NE curtails or exports its negative net load.

## Next PR needs

- The thermal floor (PR-54), then coupling (PR-51) and the backtest (PR-52).
