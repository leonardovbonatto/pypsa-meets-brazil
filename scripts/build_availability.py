# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 wind/solar availability profile from ONS Fator de Capacidade.

One hourly `p_max_pu` value per (subsystem, technology) that has real data -
the aggregate fleet capacity factor, not a naive mean of the per-plant-group
ratio (see `build_availability()` for why those differ). Hydro is
deliberately untouched: this dataset is wind/solar only, and hydro's real
constraint is water availability (PRIMER Sec 4), not a weather-derived
capacity factor. `SE_CO wind` has no data in this dataset at all (PR-14
handoff) and is left for `attach_availability()` to handle explicitly.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

# This dataset's own technology spelling ("Eólica"/"Solar") is different
# from capacidade_geracao's ("EOLIÉTRICA"/"FOTOVOLTAICA", PR-07) - a
# separate map, not a reuse of build_generators.TECHNOLOGY_MAP, is
# deliberate here, not an oversight.
TECHNOLOGY_MAP = {"Eólica": "wind", "Solar": "solar"}

GENERATION_COLUMN = "val_geracaoverificada"
CAPACITY_COLUMN = "val_capacidadeinstalada"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def map_technology(df: pd.DataFrame) -> pd.DataFrame:
    unknown = set(df["nom_tipousina"]) - set(TECHNOLOGY_MAP)
    if unknown:
        raise ValueError(f"unmapped plant type(s): {sorted(unknown)}")
    return df.assign(carrier=df["nom_tipousina"].map(TECHNOLOGY_MAP))


def build_availability(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (snapshot, subsystem, carrier): the capacity-weighted mean
    capacity factor across every plant-group in that group.

    Computed as sum(generation) / sum(capacity) rather than averaging the
    per-row val_fatorcapacidade directly - algebraically the same as a
    capacity-weighted mean (each row's factor is generation/capacity, so
    weighting by capacity and summing recovers total generation over total
    capacity), but doing it this way means a 5 MW plant-group never gets
    the same vote as a 500 MW one, and there is no risk of it silently
    degrading into an unweighted mean during a future refactor.

    Clipped to [0, 1]: a small fraction of real rows report a factor
    fractionally above 1.0 (measurement noise at the nameplate boundary,
    see the data dictionary), and PyPSA's p_max_pu > 1 would let a
    generator exceed its own p_nom.
    """
    mapped = map_subsystems(df).pipe(map_technology)

    grouped = mapped.groupby(["subsystem", "carrier", "din_instante"], as_index=False).agg(
        generation=(GENERATION_COLUMN, "sum"),
        capacity=(CAPACITY_COLUMN, "sum"),
    )
    grouped["p_max_pu"] = (grouped["generation"] / grouped["capacity"]).clip(lower=0.0, upper=1.0)

    return (
        grouped.rename(columns={"din_instante": "snapshot"})[
            ["snapshot", "subsystem", "carrier", "p_max_pu"]
        ]
        .sort_values(["subsystem", "carrier", "snapshot"])
        .reset_index(drop=True)
    )


def write_availability(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_availability(df)
    write_availability(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
