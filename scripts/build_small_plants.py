# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build T0 small-plant (TIPO III) capacity and availability.

ONS's observed generation (`geracao_usina`) includes plants that
`capacidade_geracao`, the capacity registry, does not: modalities
"Pequenas Usinas (Tipo III)" and "TIPO III". In 2024 they produced about
2.7 GW of hydro, 1.7 GW of thermal, 0.4 GW of wind and 0.1 GW of solar
(PR-59). They are not centrally dispatched, so the model cannot decide
their output.

BACKCAST, as hydro and MMGD (ADR-0007, scripts/build_mmgd.py): p_nom is the
peak observed output per (subsystem, source), p_max_pu the observed hourly
output over it, and build_network makes them must-run (p_min_pu = p_max_pu).
Carriers are `<source>_small`, kept apart from the dispatched fleet.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

SMALL_MODALIDADES = {"Pequenas Usinas (Tipo III)", "TIPO III"}
SOURCE = {
    "HIDROELÉTRICA": "hydro",
    "TÉRMICA": "thermal",
    "EOLIELÉTRICA": "wind",
    "FOTOVOLTAICA": "solar",
    "NUCLEAR": "nuclear",
}
SUFFIX = "_small"
GENERATION_COLUMN = "val_geracao"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    return pd.concat([inspect_csv(p, delimiter=delimiter) for p in paths], ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    to_pandera_schema(load_dictionary(dictionary_path)).validate(df)


def hourly_small(df: pd.DataFrame) -> pd.DataFrame:
    """Total small-plant output per (subsystem, carrier, hour)."""
    small = df[df["cod_modalidadeoperacao"].isin(SMALL_MODALIDADES)]
    source = small["nom_tipousina"].map(SOURCE)
    if source.isna().any():
        raise ValueError(
            f"unmapped plant type(s): {sorted(set(small.loc[source.isna(), 'nom_tipousina']))}"
        )
    totals = (
        small.assign(carrier=source + SUFFIX)
        .pipe(map_subsystems)
        .groupby(["subsystem", "carrier", "din_instante"])[GENERATION_COLUMN]
        .sum()
    )
    # Every (subsystem, carrier) gets every hour in the data: an hour with no
    # row for it produced nothing, and the network needs a gap-free series.
    hours = sorted(df["din_instante"].unique())
    pairs = totals.index.droplevel("din_instante").unique()
    full = pd.MultiIndex.from_tuples(
        [(s, c, h) for s, c in pairs for h in hours], names=totals.index.names
    )
    return (
        totals.reindex(full, fill_value=0.0)
        .reset_index()
        .rename(columns={"din_instante": "snapshot", GENERATION_COLUMN: "generation_mw"})
    )


def build_small_capacity(hourly: pd.DataFrame) -> pd.DataFrame:
    """One row per (subsystem, carrier) with positive output: p_nom = peak observed."""
    peak = hourly.groupby(["subsystem", "carrier"], as_index=False)["generation_mw"].max()
    return (
        peak[peak["generation_mw"] > 0]
        .rename(columns={"generation_mw": "p_nom_mw"})
        .sort_values(["subsystem", "carrier"])
        .reset_index(drop=True)
    )


def build_small_availability(hourly: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """Hourly p_max_pu = observed output / peak, clipped at 0 from below
    (ONS reports small negative values for auxiliary consumption)."""
    work = hourly.merge(capacity, on=["subsystem", "carrier"])
    work["p_max_pu"] = (work["generation_mw"] / work["p_nom_mw"]).clip(lower=0.0)
    if (work["p_max_pu"] > 1.0 + 1e-9).any():
        raise ValueError("small-plant p_max_pu above 1 - the peak denominator is wrong")
    return (
        work[["snapshot", "subsystem", "carrier", "p_max_pu"]]
        .sort_values(["subsystem", "carrier", "snapshot"])
        .reset_index(drop=True)
    )


def main() -> None:
    snake = globals()["snakemake"]
    df = load_raw([Path(p) for p in snake.input.raw])
    validate_against_dictionary(df, Path(snake.input.dictionary))
    hourly = hourly_small(df)
    capacity = build_small_capacity(hourly)
    availability = build_small_availability(hourly, capacity)
    Path(snake.output.capacity).parent.mkdir(parents=True, exist_ok=True)
    capacity.to_csv(snake.output.capacity, index=False)
    availability.to_csv(snake.output.availability, index=False)


if __name__ == "__main__":
    main()
