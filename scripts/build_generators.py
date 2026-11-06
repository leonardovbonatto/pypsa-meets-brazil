# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 generator capacity table from ONS Capacidade de Geracao.

Aggregates unit-generator-level rows down to one row per (subsystem,
technology), which is the resolution a 4-subsystem T0 model actually needs -
not per plant, not per fuel. Capacity and topology only: no marginal cost, no
availability profile. Those need CVU (thermal) and atlite/ERA5 (renewables),
both still unbuilt - see docs/handoffs/PR-08-*.md.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

# nom_tipousina, not the finer nom_combustivel: capacity/topology only cares
# about technology, not fuel. Fuel-level detail is a marginal-cost concern
# for a later PR (CVU).
TECHNOLOGY_MAP = {
    "HIDROELÉTRICA": "hydro",
    "EOLIELÉTRICA": "wind",
    "FOTOVOLTAICA": "solar",
    "TÉRMICA": "thermal",
    "NUCLEAR": "nuclear",
}

CAPACITY_COLUMN = "val_potenciaefetiva"


def load_raw(path: Path, *, delimiter: str = ";") -> pd.DataFrame:
    return inspect_csv(path, delimiter=delimiter)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def filter_active(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop decommissioned units.

    NULL/empty `dat_desativacao` means active - ONS's own stated convention
    (their data dictionary says so explicitly), not an assumption made here.
    """
    return df[df["dat_desativacao"].isna()].copy()


def map_technology(df: pd.DataFrame) -> pd.DataFrame:
    unknown = set(df["nom_tipousina"]) - set(TECHNOLOGY_MAP)
    if unknown:
        raise ValueError(f"unmapped ONS plant type(s): {sorted(unknown)}")
    return df.assign(carrier=df["nom_tipousina"].map(TECHNOLOGY_MAP))


def monthly_operating_capacity(df: pd.DataFrame, *, months: list[tuple[int, int]]) -> pd.DataFrame:
    """
    PR-59: (year, month, subsystem, carrier) -> capacity of the units
    operating at that month's end: entered operation (`dat_entradaoperacao`)
    on or before it, and not deactivated by then. The registry is a current
    snapshot; without this, plants that entered operation after the modelled
    year count as if they had run in it (2024 solar: 63.5% of the registry).
    """
    work = df.pipe(map_subsystems).pipe(map_technology)
    entry = pd.to_datetime(work["dat_entradaoperacao"], errors="coerce")
    off = pd.to_datetime(work["dat_desativacao"], errors="coerce")
    if entry.isna().any():
        raise ValueError(f"{int(entry.isna().sum())} unit(s) have no entry-into-operation date")
    rows = []
    for year, month in months:
        end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        operating = work[(entry <= end) & (off.isna() | (off > end))]
        totals = operating.groupby(["subsystem", "carrier"], as_index=False)[CAPACITY_COLUMN].sum()
        rows.append(totals.assign(year=year, month=month))
    return pd.concat(rows, ignore_index=True).rename(columns={CAPACITY_COLUMN: "p_nom_mw"})[
        ["year", "month", "subsystem", "carrier", "p_nom_mw"]
    ]


def commissioning_share(monthly: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """(year, month, subsystem, carrier) -> operating capacity over p_nom."""
    merged = monthly.merge(capacity, on=["subsystem", "carrier"], suffixes=("", "_max"))
    return merged.assign(share=merged["p_nom_mw"] / merged["p_nom_mw_max"])[
        ["year", "month", "subsystem", "carrier", "share"]
    ]


def build_generator_capacity(
    df: pd.DataFrame, *, subsystems: list[str], months: list[tuple[int, int]] | None = None
) -> pd.DataFrame:
    """
    Aggregate to one row per (subsystem, technology): summed installed
    capacity, MW. `map_subsystems()` drops PY (Itaipu 50 Hz - not part of
    Brazil's SIN, see scripts/_ons.py) before this ever sees a row of it.

    With `months`, capacity is the largest month-end operating capacity over
    them (PR-59); without, every unit active in the registry today.
    """
    if months:
        tidy = (
            monthly_operating_capacity(df, months=months)
            .groupby(["subsystem", "carrier"], as_index=False)["p_nom_mw"]
            .max()
        )
    else:
        tidy = (
            df.pipe(filter_active)
            .pipe(map_subsystems)
            .pipe(map_technology)
            .groupby(["subsystem", "carrier"], as_index=False)[CAPACITY_COLUMN]
            .sum()
            .rename(columns={CAPACITY_COLUMN: "p_nom_mw"})
        )
    tidy = tidy.sort_values(["subsystem", "carrier"]).reset_index(drop=True)

    missing = set(subsystems) - set(tidy["subsystem"])
    if missing:
        raise ValueError(f"configured subsystem(s) absent from fetched data: {sorted(missing)}")

    return tidy[tidy["subsystem"].isin(subsystems)].reset_index(drop=True)


def write_generator_capacity(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    df = load_raw(Path(snake.input.raw))
    validate_against_dictionary(df, Path(snake.input.dictionary))

    months = [tuple(m) for m in snake.params.months]
    tidy = build_generator_capacity(df, subsystems=list(snake.params.subsystems), months=months)
    write_generator_capacity(tidy, Path(snake.output.capacity))
    share = commissioning_share(monthly_operating_capacity(df, months=months), tidy)
    write_generator_capacity(share, Path(snake.output.commissioning))


if __name__ == "__main__":
    main()
