# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 inter-subsystem transfer-capacity table from ONS Intercambio
Nacional.

Per ADR-0006, T0 represents transmission as a transport model (PyPSA
`Link`s with a capacity limit), not real power flow - the topology and the
capacity proxy both come from this dataset, not assumption. Topology is
whichever `(origem, destino)` boundaries actually carry data; capacity is
the largest absolute flow observed on that boundary, a documented
lower-bound proxy for the true rating, not the rating itself.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

FLOW_COLUMN = "val_intercambiomwmed"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def build_link_capacity(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """
    One row per real boundary: `(bus0, bus1, p_nom_mw)`.

    `val_intercambiomwmed` is signed (positive = origem -> destino that
    hour, negative = the reverse) - the capacity proxy takes the max of the
    *absolute* value, not the max of the signed value, or it would
    understate whichever direction is less common.
    """
    mapped = map_subsystems(df, column="id_subsistema_origem").rename(columns={"subsystem": "bus0"})
    mapped = map_subsystems(mapped, column="id_subsistema_destino").rename(
        columns={"subsystem": "bus1"}
    )

    tidy = (
        mapped.assign(abs_flow=mapped[FLOW_COLUMN].abs())
        .groupby(["bus0", "bus1"], as_index=False)["abs_flow"]
        .max()
        .rename(columns={"abs_flow": "p_nom_mw"})
        .sort_values(["bus0", "bus1"])
        .reset_index(drop=True)
    )

    connected = set(tidy["bus0"]) | set(tidy["bus1"])
    missing = set(subsystems) - connected
    if missing:
        raise ValueError(
            f"configured subsystem(s) have no link in the fetched data: {sorted(missing)}"
        )

    return tidy


def write_link_capacity(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_link_capacity(df, subsystems=list(snake.params.subsystems))
    write_link_capacity(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
