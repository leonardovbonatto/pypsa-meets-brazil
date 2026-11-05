# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Monthly thermal floor per subsystem: what ONS ran for reasons other than
price in 2024 (ADR-0016).

Without it, SDDP with net load (ADR-0013) dispatches almost no thermal and
costs R$0.47bn a year, while 2024 actually ran about 6.6 GW of thermal, 64% of
it by declared inflexibility (measured in the data dictionary). Inflexible,
electrical-reason and other out-of-merit generation runs whatever the price,
so it is an input; only merit-order generation above it is left to the model.

    floor = val_verifgeracao - val_verifordemdemeritoacimadainflex

summed over plants per hour, then averaged per calendar month. The result is
capped at the subsystem's thermal capacity in T0 so the floor can always be met.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

TOTAL = "val_verifgeracao"
PRICE_DRIVEN = "val_verifordemdemeritoacimadainflex"
INFLEXIBLE = "val_verifinflexibilidade"
COLUMNS = ["din_instante", "id_subsistema", TOTAL, PRICE_DRIVEN, INFLEXIBLE]


def load_raw(paths: list[Path]) -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=";") for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    to_pandera_schema(load_dictionary(dictionary_path)).validate(df)


def monthly_floor(df: pd.DataFrame) -> pd.DataFrame:
    """(month, subsystem) -> mean MW of the floor, of total verified thermal and
    of declared inflexibility."""
    work = map_subsystems(df[COLUMNS], column="id_subsistema")
    work = work.assign(
        snapshot=pd.to_datetime(work["din_instante"]),
        floor_mw=work[TOTAL] - work[PRICE_DRIVEN],
    )
    hourly = work.groupby(["snapshot", "subsystem"], as_index=False)[
        ["floor_mw", TOTAL, INFLEXIBLE]
    ].sum()
    hourly["month"] = hourly["snapshot"].dt.month
    return (
        hourly.groupby(["month", "subsystem"], as_index=False)[["floor_mw", TOTAL, INFLEXIBLE]]
        .mean()
        .rename(columns={TOTAL: "verified_thermal_mw", INFLEXIBLE: "inflexible_mw"})
        .sort_values(["month", "subsystem"])
        .reset_index(drop=True)
    )


def cap_at_capacity(floor: pd.DataFrame, generators: pd.DataFrame) -> pd.DataFrame:
    """Cap floor_mw at T0's thermal p_nom, recording how much was cut."""
    capacity = generators[generators["carrier"] == "thermal"].set_index("subsystem")["p_nom_mw"]
    missing = set(floor["subsystem"]) - set(capacity.index)
    if missing:
        raise ValueError(f"no T0 thermal capacity for {sorted(missing)}")
    cap = floor["subsystem"].map(capacity)
    return floor.assign(
        floor_capped_mw=(floor["floor_mw"] - cap).clip(lower=0.0),
        floor_mw=floor["floor_mw"].clip(upper=cap),
    )


def main() -> None:
    snake = globals()["snakemake"]
    df = load_raw([Path(p) for p in snake.input.raw])
    validate_against_dictionary(df, Path(snake.input.dictionary))
    floor = cap_at_capacity(monthly_floor(df), pd.read_csv(snake.input.generators))
    Path(snake.output[0]).parent.mkdir(parents=True, exist_ok=True)
    floor.to_csv(snake.output[0], index=False)


if __name__ == "__main__":
    main()
