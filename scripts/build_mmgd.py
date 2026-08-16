# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build T0 MMGD (distributed generation) capacity and availability.

MMGD - micro e minigeracao distribuida, overwhelmingly rooftop PV - is
absent from `capacidade_geracao`, which covers only ONS-dispatched units.
PR-18's ballpark check showed that gap costing ~4.9 GW of spurious thermal
dispatch, against ~5.1 GW of real MMGD output. This closes it.

BACKCAST, same principle as hydro (ADR-0007): both the capacity and the
hourly profile come from ONS *observed* generation, so MMGD output is a
model input, not a model result.

Two modelling choices worth knowing, neither inferable from the data:

  1. `p_nom` is the largest hourly MMGD output observed in the period, per
     subsystem. That is NOT installed capacity - real installed MMGD is
     substantially higher, since a distributed fleet spread over a
     continent never peaks simultaneously. It is the smallest capacity
     consistent with the observed generation, which is the honest choice
     when the true figure is not in this dataset. ANEEL's MMGD registry
     has real installed capacity if a later PR wants it.

  2. Carrier is `solar_mmgd`, kept distinct from `solar`. Utility-scale
     and behind-the-meter PV differ in siting, profile and who dispatches
     them; collapsing them would hide that and make comparison against
     ONS's own breakdown harder.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

MMGD_MODALIDADE = "Pequenas Usinas (MMGD)"
MMGD_CARRIER = "solar_mmgd"
GENERATION_COLUMN = "val_geracao"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def filter_mmgd(df: pd.DataFrame) -> pd.DataFrame:
    """MMGD rows only. Observed to be entirely photovoltaic, but not assumed here."""
    return df[df["cod_modalidadeoperacao"] == MMGD_MODALIDADE].copy()


def hourly_mmgd(df: pd.DataFrame) -> pd.DataFrame:
    """Total MMGD output per (subsystem, hour)."""
    return (
        filter_mmgd(df)
        .pipe(map_subsystems)
        .groupby(["subsystem", "din_instante"], as_index=False)[GENERATION_COLUMN]
        .sum()
        .rename(columns={"din_instante": "snapshot", GENERATION_COLUMN: "generation_mw"})
    )


def build_mmgd_capacity(df: pd.DataFrame) -> pd.DataFrame:
    """One row per subsystem: `p_nom` = peak observed output (see module docstring)."""
    hourly = hourly_mmgd(df)
    return (
        hourly.groupby("subsystem", as_index=False)["generation_mw"]
        .max()
        .rename(columns={"generation_mw": "p_nom_mw"})
        .assign(carrier=MMGD_CARRIER)[["subsystem", "carrier", "p_nom_mw"]]
        .sort_values("subsystem")
        .reset_index(drop=True)
    )


def build_mmgd_availability(df: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """
    Hourly `p_max_pu` = observed output / peak observed output.

    Bounded by [0, 1] by construction, since the denominator is the series'
    own maximum - so unlike the hydro backcast there is no population
    mismatch to guard against. Asserted rather than assumed.
    """
    hourly = hourly_mmgd(df)
    peak = capacity.set_index("subsystem")["p_nom_mw"]

    hourly["p_max_pu"] = hourly["generation_mw"] / hourly["subsystem"].map(peak)

    if not hourly["p_max_pu"].between(0.0, 1.0).all():
        raise ValueError("MMGD p_max_pu outside [0, 1] - the peak denominator is wrong")

    return (
        hourly.assign(carrier=MMGD_CARRIER)[["snapshot", "subsystem", "carrier", "p_max_pu"]]
        .sort_values(["subsystem", "snapshot"])
        .reset_index(drop=True)
    )


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    capacity = build_mmgd_capacity(df)
    availability = build_mmgd_availability(df, capacity)

    Path(snake.output.capacity).parent.mkdir(parents=True, exist_ok=True)
    capacity.to_csv(snake.output.capacity, index=False)
    availability.to_csv(snake.output.availability, index=False)


if __name__ == "__main__":
    main()
