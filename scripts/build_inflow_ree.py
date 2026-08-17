# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the tidy REE-level historical inflow (ENA) series (ADR-0008,
SDDP epic stage 2), the REE counterpart of build_inflow.py's
subsystem-level series (ADR-0005 stage 1b, PR-27).

Same shape as build_inflow.py, keyed on REE instead of subsystem, with a
`subsystem` column attached via PR-35's real reservoir-registry mapping
(`resources/ree_subsystem_map.csv`) - not the domain-name inference
ADR-0008 expected to need.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema

VALUE_COLUMNS = {
    "ena_bruta_ree_mwmed": "ena_bruta_mwmed",
    "ena_bruta_ree_percentualmlt": "ena_bruta_pct_mlt",
    "ena_armazenavel_ree_mwmed": "ena_armazenavel_mwmed",
    "ena_armazenavel_ree_percentualmlt": "ena_armazenavel_pct_mlt",
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
    """`ena_data` is a plain calendar date, same convention as ena_subsistema (PR-27)."""
    return df.assign(date=pd.to_datetime(df["ena_data"]))


def attach_subsystem(df: pd.DataFrame, ree_map: pd.DataFrame) -> pd.DataFrame:
    """
    Join the real REE-to-subsystem mapping (PR-35), raising on any REE
    this dataset has that the registry doesn't know about - a population
    mismatch would otherwise silently drop rows via an inner join.
    """
    unmapped = set(df["nom_reservatorioee"]) - set(ree_map["ree"])
    if unmapped:
        raise ValueError(f"REE(s) with no subsystem mapping: {sorted(unmapped)}")
    return df.merge(ree_map, left_on="nom_reservatorioee", right_on="ree", how="left")


def build_tidy_inflow(df: pd.DataFrame, ree_map: pd.DataFrame) -> pd.DataFrame:
    tidy = (
        attach_subsystem(df, ree_map)
        .pipe(parse_dates)
        .rename(columns=VALUE_COLUMNS)[["date", "ree", "subsystem", *VALUE_COLUMNS.values()]]
        .sort_values(["date", "ree"])
        .reset_index(drop=True)
    )

    # Deliberately NOT a "every REE shares the same date count" check like
    # build_inflow.py's subsystem-level equivalent: real data shows 3 REEs
    # (IGUACU, MANAUS-AMAPA, PARANAPANEMA) only exist as separately-tracked
    # units from 2017-12-30 onward - a genuine REE-structure revision, not
    # a data gap (see the data dictionary's notes). Each REE's own series
    # must still be gap-free within its own actual coverage window.
    for ree, dates in tidy.groupby("ree")["date"]:
        deltas = dates.diff().dropna().unique()
        bad = [d for d in deltas if d != pd.Timedelta(days=1)]
        if bad:
            raise ValueError(f"non-daily gap or duplicate in {ree}: {bad}")

    # Clipped, not raised - a real, checked pattern with TWO distinct
    # causes (data dictionary notes), unlike ena_subsistema's equivalent
    # check (PR-27), which never triggered: most REEs show ~1e-14
    # differences (floating-point noise around spill=0, not a real data
    # issue), but PARANA shows a real, substantial, unexplained pattern
    # (mean +7%, max +40%) - both clipped the same way since storable
    # cannot physically exceed gross by definition either way, but
    # recorded distinctly rather than treated as one phenomenon.
    storable_exceeds_gross = tidy["ena_armazenavel_mwmed"] > tidy["ena_bruta_mwmed"]
    tidy.loc[storable_exceeds_gross, "ena_armazenavel_mwmed"] = tidy.loc[
        storable_exceeds_gross, "ena_bruta_mwmed"
    ]

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

    ree_map = pd.read_csv(snake.input.ree_map)
    tidy = build_tidy_inflow(df, ree_map)
    write_tidy_inflow(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
