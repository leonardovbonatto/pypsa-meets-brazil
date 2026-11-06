# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Wind and solar availability before curtailment (PR-70).

`fator_capacidade`, the source of T0's wind and solar p_max_pu, comes from
verified output, which is net of ONS's constrained-off. In 2024 that was
large (wind NE 10.4% of potential, solar NE 17.7% from April). ONS's
constrained-off detail gives, per plant and half hour, verified output, an
estimated output from wind speed or irradiance, and whether output was
restricted. The unrealised output is the estimate above verified in
restricted periods only (ONS's own GNR idea), which keeps the estimator's
bias out of unrestricted hours.

factor(hour, subsystem, carrier) = (verified + unrealised) / verified,
at least 1; 1 where there is no data (solar before April 2024).
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ons import map_subsystems

COLUMNS = [
    "id_subsistema",
    "din_instante",
    "val_geracaoestimada",
    "val_geracaoverificada",
    "flg_geracaorestrita",
]
CARRIER = {"EOLICA": "wind", "FOTOVOLTAICA": "solar"}


def hourly_factor(raw: pd.DataFrame, carrier: str) -> pd.DataFrame:
    """(snapshot, subsystem) -> uncurtailment factor for one carrier."""
    df = map_subsystems(raw)
    unrealised = (df["val_geracaoestimada"] - df["val_geracaoverificada"]).clip(lower=0.0)
    df = df.assign(
        snapshot=pd.to_datetime(df["din_instante"]).dt.floor("h"),
        unrealised=unrealised.where(df["flg_geracaorestrita"] == 1, 0.0).fillna(0.0),
        verified=df["val_geracaoverificada"].clip(lower=0.0).fillna(0.0),
    )
    total = df.groupby(["snapshot", "subsystem"], as_index=False)[["verified", "unrealised"]].sum()
    factor = (total["verified"] + total["unrealised"]) / total["verified"].where(
        total["verified"] > 0
    )
    return total.assign(carrier=carrier, factor=factor.fillna(1.0).clip(lower=1.0))[
        ["snapshot", "subsystem", "carrier", "factor"]
    ]


def main() -> None:
    snake = globals()["snakemake"]
    parts = []
    for kind, paths in (("EOLICA", snake.input.wind), ("FOTOVOLTAICA", snake.input.solar)):
        raw = pd.concat(
            [pd.read_csv(p, sep=";", usecols=COLUMNS) for p in paths], ignore_index=True
        )
        parts.append(hourly_factor(raw, CARRIER[kind]))
    out = Path(snake.output[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(parts, ignore_index=True).to_csv(out, index=False)


if __name__ == "__main__":
    main()
