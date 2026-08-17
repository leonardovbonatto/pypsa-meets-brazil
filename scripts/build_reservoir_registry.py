# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the tidy reservoir registry and REE-to-subsystem mapping from ONS's
per-reservoir physical registry (ADR-0008, SDDP epic stage 2).

This resolves ADR-0008's named open question with real data instead of
domain-name inference: `id_subsistema` and `nom_ree` sit on the same row
for every one of 162 real reservoirs, giving a clean, checkable 1:1
mapping - not assumed, verified by `build_ree_subsystem_map()` raising if
any REE ever maps to more than one subsystem.

Kept as two separate outputs rather than one: `build_tidy_registry()`'s
full table (real physical characteristics - volume, elevation,
productivity - useful for a future per-plant individualization stage,
see the data dictionary's notes on this dataset possibly substituting for
`hidr.dat`) and `build_ree_subsystem_map()`'s minimal mapping (all
`ena_ree`/`ear_ree` actually need). Every consumer of the mapping
shouldn't have to re-derive it from the full registry.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems


def load_raw(path: Path, *, delimiter: str = ";") -> pd.DataFrame:
    return inspect_csv(path, delimiter=delimiter)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def build_tidy_registry(df: pd.DataFrame) -> pd.DataFrame:
    """One row per reservoir, subsystem mapped through the same
    _ons.map_subsystems() every other connector uses, all real physical
    fields kept as published."""
    return (
        map_subsystems(df)
        .sort_values(["subsystem", "nom_ree", "nom_reservatorio"])
        .reset_index(drop=True)
    )


def build_ree_subsystem_map(tidy_registry: pd.DataFrame) -> pd.DataFrame:
    """
    One row per REE: (ree, subsystem). Raises if any REE maps to more
    than one subsystem - a real invariant, checked rather than assumed,
    not just documented as true in the data dictionary's notes.
    """
    pairs = tidy_registry[["nom_ree", "subsystem"]].drop_duplicates()
    ambiguous = pairs.groupby("nom_ree")["subsystem"].nunique()
    bad = ambiguous[ambiguous > 1]
    if not bad.empty:
        raise ValueError(f"REE(s) mapping to more than one subsystem: {sorted(bad.index)}")

    return pairs.rename(columns={"nom_ree": "ree"}).sort_values("ree").reset_index(drop=True)


def write_csv(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    df = load_raw(Path(snake.input.raw))
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_tidy_registry(df)
    ree_map = build_ree_subsystem_map(tidy)

    write_csv(tidy, Path(snake.output.registry))
    write_csv(ree_map, Path(snake.output.ree_map))


if __name__ == "__main__":
    main()
