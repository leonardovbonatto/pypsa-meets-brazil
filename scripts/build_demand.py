# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 tidy demand series from ONS Curva de Carga.

Turns one CSV per year, subsystem-coded and string-timestamped, into a single
tidy frame indexed by (snapshot, subsystem) with load in MW - the shape a
PyPSA `n.loads_t.p_set` build step can pivot directly. Two judgement calls
live here rather than upstream: mapping ONS subsystem codes onto the config's
subsystem labels, and choosing a naive (timezone-unaware) timestamp so it
matches PyPSA's snapshot convention. See docs/handoffs/PR-05-*.md for why.
"""

# NOTE: no `from __future__ import annotations` - Snakemake's injected preamble
# would push it out of first position and raise SyntaxError. See write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import SUBSYSTEM_MAP, map_subsystems  # noqa: F401 (re-exported for callers/tests)

LOAD_COLUMN = "val_cargaenergiahomwmed"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    `din_instante` arrives as a string in Brasilia local time (UTC-3, no DST
    from 2019 on). Parsed tz-naive on purpose: PyPSA snapshots are naive, and
    attaching a timezone here would only need stripping again downstream.
    """
    return df.assign(snapshot=pd.to_datetime(df["din_instante"]))


def build_tidy_demand(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    tidy = (
        df.pipe(map_subsystems)
        .pipe(parse_timestamps)
        .rename(columns={LOAD_COLUMN: "load_mw"})[["snapshot", "subsystem", "load_mw"]]
        .sort_values(["snapshot", "subsystem"])
        .reset_index(drop=True)
    )

    missing = set(subsystems) - set(tidy["subsystem"])
    if missing:
        raise ValueError(f"configured subsystem(s) absent from fetched data: {sorted(missing)}")
    tidy = tidy[tidy["subsystem"].isin(subsystems)].reset_index(drop=True)

    counts = tidy.groupby("subsystem")["snapshot"].nunique()
    if counts.nunique() != 1:
        raise ValueError(f"subsystems do not share the same snapshot count: {counts.to_dict()}")

    for subsystem, snapshots in tidy.groupby("subsystem")["snapshot"]:
        deltas = snapshots.diff().dropna().unique()
        bad = [d for d in deltas if d != pd.Timedelta(hours=1)]
        if bad:
            raise ValueError(f"non-hourly gap or duplicate in {subsystem}: {bad}")

    return tidy


def write_tidy_demand(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_tidy_demand(df, subsystems=list(snake.params.subsystems))
    write_tidy_demand(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
