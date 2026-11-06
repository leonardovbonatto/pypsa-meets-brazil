# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build T0 international exports as load (PR-64).

ONS's load series (`curva_carga`) is Brazilian consumption; generation also
served exports through the border frequency converters. In 2024 observed
generation exceeded T0 demand by about 0.4 GW, and net exports were 162 MW
of it (Argentina +186, Uruguay -24). Without them the model meets less
load than ONS's generation served.

Each country's hourly verified interchange (positive = export) becomes load
at the subsystem its converters sit in; net imports are negative load.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema

# Garabi (Argentina) and Rivera / Melo (Uruguay) are in Rio Grande do Sul;
# Acaray (Paraguay) connects in Parana. All in subsystem S except Paraguay,
# whose 2024 flow is zero throughout.
BORDER_SUBSYSTEM = {"ARGENTINA": "S", "URUGUAI": "S", "PARAGUAI": "S"}
FLOW_COLUMN = "val_intercambiomwmed"


def load_raw(paths: list[Path]) -> pd.DataFrame:
    return pd.concat([inspect_csv(p, delimiter=";") for p in paths], ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    to_pandera_schema(load_dictionary(dictionary_path)).validate(df)


def build_exports(df: pd.DataFrame) -> pd.DataFrame:
    """(snapshot, subsystem) -> net export MW, summed over countries."""
    unknown = sorted(set(df["nom_paisdestino"]) - set(BORDER_SUBSYSTEM))
    if unknown:
        raise ValueError(f"no border subsystem for country(ies): {unknown}")
    return (
        df.assign(subsystem=df["nom_paisdestino"].map(BORDER_SUBSYSTEM))
        .groupby(["din_instante", "subsystem"], as_index=False)[FLOW_COLUMN]
        .sum()
        .rename(columns={"din_instante": "snapshot", FLOW_COLUMN: "p_set_mw"})
        .sort_values(["subsystem", "snapshot"])
        .reset_index(drop=True)
    )


def main() -> None:
    snake = globals()["snakemake"]
    df = load_raw([Path(p) for p in snake.input.raw])
    validate_against_dictionary(df, Path(snake.input.dictionary))
    out = Path(snake.output[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    build_exports(df).to_csv(out, index=False)


if __name__ == "__main__":
    main()
