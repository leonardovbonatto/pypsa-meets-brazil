# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the tidy historical reservoir storage (EAR) series from ONS Energia
Armazenada per subsystem (ADR-0005, SDDP epic stage 1e).

Turns one CSV per year, subsystem-coded and date-stamped, into a single
tidy frame indexed by (date, subsystem) with max/verified storage. Same
shape as build_inflow.py (PR-27), same daily-not-hourly structural
difference from every hourly ONS connector in this project.

`ear_max_mwmes` is real reservoir CAPACITY - the number a hydro-thermal
SDDP policy needs and this connector exists specifically to avoid having
to fabricate (see the data dictionary's notes and docs/handoffs/PR-30-*.md).
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

VALUE_COLUMNS = {
    "ear_max_subsistema": "ear_max_mwmes",
    "ear_verif_subsistema_mwmes": "ear_verif_mwmes",
    "ear_verif_subsistema_percentual": "ear_verif_pct",
}


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """`ear_data` is a plain calendar date, same convention as ena_subsistema (PR-27)."""
    return df.assign(date=pd.to_datetime(df["ear_data"]))


def build_tidy_reservoir(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    tidy = (
        df.pipe(map_subsystems)
        .pipe(parse_dates)
        .rename(columns=VALUE_COLUMNS)[["date", "subsystem", *VALUE_COLUMNS.values()]]
        .sort_values(["date", "subsystem"])
        .reset_index(drop=True)
    )

    missing = set(subsystems) - set(tidy["subsystem"])
    if missing:
        raise ValueError(f"configured subsystem(s) absent from fetched data: {sorted(missing)}")
    tidy = tidy[tidy["subsystem"].isin(subsystems)].reset_index(drop=True)

    counts = tidy.groupby("subsystem")["date"].nunique()
    if counts.nunique() != 1:
        raise ValueError(f"subsystems do not share the same date count: {counts.to_dict()}")

    for subsystem, dates in tidy.groupby("subsystem")["date"]:
        deltas = dates.diff().dropna().unique()
        bad = [d for d in deltas if d != pd.Timedelta(days=1)]
        if bad:
            raise ValueError(f"non-daily gap or duplicate in {subsystem}: {bad}")

    # A real, checked quirk, not silently accepted: 99 of 37,988 real rows
    # (0.26%) have verified storage marginally above max capacity - all in
    # subsystem N, overwhelmingly year 2000, at most 3.66% over (mean
    # 1.6%). ONS's own dataset description says this data "is subject to a
    # recurring consistency process and may be updated after publication" -
    # ear_max_subsistema in an old row was very likely never retroactively
    # revised after a later recalibration. Clipped, not raised, following
    # this project's own precedent (fator_capacidade's >1.0 rows, PR-14):
    # storage exceeding its own capacity is nonsensical for any downstream
    # model to consume, and rejecting the whole 26-year build over a
    # small, explicable, early-record measurement quirk would be worse
    # than clipping it.
    overage = tidy["ear_verif_mwmes"] > tidy["ear_max_mwmes"]
    if overage.any():
        tidy.loc[overage, "ear_verif_mwmes"] = tidy.loc[overage, "ear_max_mwmes"]
        tidy.loc[overage, "ear_verif_pct"] = 100.0

    return tidy


def latest_capacity(tidy: pd.DataFrame) -> pd.DataFrame:
    """
    Current reservoir capacity per subsystem - the MOST RECENT date's
    `ear_max_mwmes`, not an average across the historical record.

    Real capacity grows over time as new reservoirs are built (see the
    data dictionary's notes: SE grew from ~157,701 to ~204,615 MWmes over
    2000-2025); averaging would understate present-day capacity for a
    forward-looking policy.
    """
    latest_date = tidy["date"].max()
    return (
        tidy[tidy["date"] == latest_date][["subsystem", "ear_max_mwmes"]]
        .sort_values("subsystem")
        .reset_index(drop=True)
    )


def write_tidy_reservoir(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_tidy_reservoir(df, subsystems=list(snake.params.subsystems))
    write_tidy_reservoir(tidy, Path(snake.output.history))
    write_tidy_reservoir(latest_capacity(tidy), Path(snake.output.capacity))


if __name__ == "__main__":
    main()
