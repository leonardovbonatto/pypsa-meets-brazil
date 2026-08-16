# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the tidy historical inflow (ENA) series from ONS Energia Natural
Afluente per subsystem (ADR-0005, SDDP epic stage 1).

Turns one CSV per year, subsystem-coded and date-stamped, into a single
tidy frame indexed by (date, subsystem) with all four published ENA
figures (gross/storable, MWmed/% of long-term average) - the input
PAR(p) fitting (a later PR) needs. Deliberately keeps all four value
columns rather than picking one now: which figure PAR(p) actually fits on
is that PR's decision, not this connector's.

Daily, not hourly - the one real structural difference from every other
ONS connector in this project (see docs/data-dictionary/ons/ena_subsistema.yaml).
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

VALUE_COLUMNS = {
    "ena_bruta_regiao_mwmed": "ena_bruta_mwmed",
    "ena_bruta_regiao_percentualmlt": "ena_bruta_pct_mlt",
    "ena_armazenavel_regiao_mwmed": "ena_armazenavel_mwmed",
    "ena_armazenavel_regiao_percentualmlt": "ena_armazenavel_pct_mlt",
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
    """`ena_data` is a plain calendar date (no time-of-day component) - see the
    data dictionary's note on ONS not stating a timezone for this field."""
    return df.assign(date=pd.to_datetime(df["ena_data"]))


def build_tidy_inflow(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
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

    storable_exceeds_gross = tidy["ena_armazenavel_mwmed"] > tidy["ena_bruta_mwmed"]
    if storable_exceeds_gross.any():
        raise ValueError(
            f"storable ENA exceeds gross ENA in {storable_exceeds_gross.sum()} row(s) - "
            "storable nets out spill, so it must never be larger"
        )

    return tidy


def write_tidy_inflow(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    tidy = build_tidy_inflow(df, subsystems=list(snake.params.subsystems))
    write_tidy_inflow(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
