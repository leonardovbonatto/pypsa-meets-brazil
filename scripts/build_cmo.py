# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build tidy marginal operating cost (CMO) series from ONS: weekly from DECOMP
(2005 onward) and monthly from DESSEM's half-hourly values (2020 onward).

CMO is the backtest target for the SDDP policy (roadmap Phase 7 gate). It is
ONS's own model output, the price-like quantity the official chain produces,
not a market price.

Three real findings shape this file (see docs/handoffs/PR-47-*.md):

- The weekly `din_instante` is always a Friday, and it is the END of the
  operating week (Saturday to Friday). The dictionary says only "reference
  date". Measured on 2024: weekly values match half-hourly means over the
  seven days ending on that date better than the seven starting on it
  (correlation 0.920 vs 0.895).
- The half-hourly files miss WHOLE days, 1 to 16 a year, always for every
  subsystem at once. Monthly values therefore carry their own coverage, and
  a partial-day gap or subsystems that disagree raise, because that would be
  a new kind of gap nobody has looked at.
- Values are kept as published, including negative CMO (NE in 2022 and
  2024, small) and one half-hour of R$54,729.62/MWh in N on 2020-10-10.
  Monthly output carries the median beside the mean so one such slot
  cannot pass for a month's level unnoticed.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

WEEKLY_COLUMNS = {
    "val_cmomediasemanal": "cmo_mean",
    "val_cmoleve": "cmo_light",
    "val_cmomedia": "cmo_medium",
    "val_cmopesada": "cmo_heavy",
}
SLOTS_PER_DAY = 48


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    schema = to_pandera_schema(load_dictionary(dictionary_path))
    schema.validate(df)


def _keep_configured(tidy: pd.DataFrame, subsystems: list[str]) -> pd.DataFrame:
    missing = set(subsystems) - set(tidy["subsystem"])
    if missing:
        raise ValueError(f"configured subsystem(s) absent from fetched data: {sorted(missing)}")
    return tidy[tidy["subsystem"].isin(subsystems)].reset_index(drop=True)


def build_weekly(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """(week_end, subsystem) -> CMO in R$/MWh, mean and per load block."""
    week_end = pd.to_datetime(df["din_instante"])
    tidy = (
        df.assign(week_end=week_end, week_start=week_end - pd.Timedelta(days=6))
        .pipe(map_subsystems)
        .rename(columns=WEEKLY_COLUMNS)[
            ["week_start", "week_end", "subsystem", *WEEKLY_COLUMNS.values()]
        ]
        .sort_values(["week_end", "subsystem"])
        .reset_index(drop=True)
    )
    tidy = _keep_configured(tidy, subsystems)

    weekdays = set(tidy["week_end"].dt.day_name())
    if weekdays != {"Friday"}:
        raise ValueError(f"operating weeks must end on a Friday, found {sorted(weekdays)}")

    weeks = tidy.groupby("subsystem")["week_end"].apply(frozenset)
    if weeks.nunique() != 1:
        raise ValueError("subsystems do not share the same operating weeks")
    for subsystem, ends in tidy.groupby("subsystem")["week_end"]:
        spacing = set(ends.diff().dropna())
        if spacing - {pd.Timedelta(days=7)}:
            raise ValueError(f"gap or duplicate week in {subsystem}: {sorted(spacing)}")
    return tidy


def build_monthly(df: pd.DataFrame, *, subsystems: list[str]) -> pd.DataFrame:
    """(month, subsystem) -> mean and median half-hourly CMO with coverage."""
    tidy = df.assign(instant=pd.to_datetime(df["din_instante"])).pipe(map_subsystems)
    tidy = _keep_configured(tidy, subsystems)
    tidy = tidy.assign(day=tidy["instant"].dt.normalize(), month=tidy["instant"].dt.to_period("M"))

    duplicates = tidy.duplicated(["subsystem", "instant"])
    if duplicates.any():
        raise ValueError(f"{int(duplicates.sum())} duplicate half-hours")

    slots = tidy.groupby(["subsystem", "day"]).size()
    partial = slots[slots != SLOTS_PER_DAY]
    if not partial.empty:
        raise ValueError(f"partial days, expected whole days only: {partial.head().to_dict()}")
    days = tidy.groupby("subsystem")["day"].apply(frozenset)
    if days.nunique() != 1:
        raise ValueError("subsystems are missing different days")

    monthly = (
        tidy.groupby(["month", "subsystem"])["val_cmo"]
        .agg(cmo_mean="mean", cmo_median="median", slots="size")
        .reset_index()
    )
    expected = monthly["month"].apply(lambda m: m.days_in_month * SLOTS_PER_DAY)
    monthly["coverage"] = monthly["slots"] / expected
    monthly["month"] = monthly["month"].astype(str)
    return monthly.sort_values(["month", "subsystem"]).reset_index(drop=True)


def write_csv(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]
    subsystems = list(snake.params.subsystems)

    weekly_raw = load_raw([Path(p) for p in snake.input.weekly])
    validate_against_dictionary(weekly_raw, Path(snake.input.weekly_dictionary))
    write_csv(build_weekly(weekly_raw, subsystems=subsystems), Path(snake.output.weekly))

    half_hourly_raw = load_raw([Path(p) for p in snake.input.half_hourly])
    validate_against_dictionary(half_hourly_raw, Path(snake.input.half_hourly_dictionary))
    write_csv(build_monthly(half_hourly_raw, subsystems=subsystems), Path(snake.output.monthly))


if __name__ == "__main__":
    main()
