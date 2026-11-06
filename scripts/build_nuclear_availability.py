# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build T0 nuclear availability from ONS `disponibilidade_usina` (PR-62).

Without it, Angra I and II run at their full 1,990 MW all year; in 2024 ONS
recorded refuelling outages (nuclear output 961 MW in November). Operational
availability (`val_dispoperacional`) is what the plants could produce after
outages, whatever they were dispatched to do, so this is an availability
input, not a backcast of output.

p_max_pu = summed operational availability of the subsystem's nuclear
plants (`id_tipousina` UTN) over the nuclear generator's p_nom.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

NUCLEAR_TYPE = "UTN"
AVAILABILITY_COLUMN = "val_dispoperacional"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    return pd.concat([inspect_csv(p, delimiter=delimiter) for p in paths], ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    to_pandera_schema(load_dictionary(dictionary_path)).validate(df)


def build_nuclear_availability(df: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """One row per (snapshot, subsystem) with a nuclear generator: p_max_pu.
    Raises above 1.0 rather than clipping: that would mean the plants here
    and the generator's p_nom disagree."""
    p_nom = capacity[capacity["carrier"] == "nuclear"].set_index("subsystem")["p_nom_mw"]
    hourly = (
        df[df["id_tipousina"] == NUCLEAR_TYPE]
        .pipe(map_subsystems)
        .groupby(["subsystem", "din_instante"], as_index=False)[AVAILABILITY_COLUMN]
        .sum()
        .rename(columns={"din_instante": "snapshot"})
    )
    missing = set(hourly["subsystem"]) - set(p_nom.index)
    if missing:
        raise ValueError(
            f"nuclear availability for subsystem(s) with no nuclear generator: {sorted(missing)}"
        )
    hourly["p_max_pu"] = hourly[AVAILABILITY_COLUMN] / hourly["subsystem"].map(p_nom)
    if (hourly["p_max_pu"] > 1.0 + 1e-9).any():
        raise ValueError("nuclear availability exceeds p_nom - plant population mismatch")
    return (
        hourly.assign(carrier="nuclear")[["snapshot", "subsystem", "carrier", "p_max_pu"]]
        .sort_values(["subsystem", "snapshot"])
        .reset_index(drop=True)
    )


def main() -> None:
    snake = globals()["snakemake"]
    df = load_raw([Path(p) for p in snake.input.raw])
    validate_against_dictionary(df, Path(snake.input.dictionary))
    out = build_nuclear_availability(df, pd.read_csv(snake.input.capacity))
    Path(snake.output[0]).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(snake.output[0], index=False)


if __name__ == "__main__":
    main()
