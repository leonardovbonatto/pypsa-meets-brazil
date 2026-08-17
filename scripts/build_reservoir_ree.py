# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the tidy REE-level reservoir storage (EAR) series (ADR-0008,
SDDP epic stage 2), the REE counterpart of build_reservoir.py's
subsystem-level series (ADR-0005 stage 1e, PR-30).

Same shape as build_reservoir.py, keyed on REE instead of subsystem, with
a `subsystem` column attached via PR-35's real reservoir-registry mapping.

Clips BOTH directions of a real, checked boundary quirk (see the data
dictionary's notes): a small fraction of rows have verified storage
either below 0 or above ear_max_ree, concentrated in the REEs with the
smallest absolute capacity (BELO MONTE, MADEIRA, MANAUS-AMAPA) - the same
absolute measurement noise that is negligible for a huge reservoir is a
much larger relative swing for a small one. PR-30's subsystem-level
connector only needed the over-capacity clip; this one needs both.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema

REPORTING_GAPS = {
    # (ree, missing-day-count): confirmed real, not investigated further
    # per-day, but tied to a genuine event - see the data dictionary's
    # notes. ITAIPU's EAR reporting stops entirely on this same date
    # (2019-10-13), strongly suggesting a real ONS system/methodology
    # change around then, not two unrelated coincidences. A future
    # re-fetch introducing a NEW, different gap still prints a warning -
    # this only silences the one already investigated.
    "TELES PIRES": [pd.Timedelta("13 days")],
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
    return df.assign(date=pd.to_datetime(df["ear_data"]))


def attach_subsystem(df: pd.DataFrame, ree_map: pd.DataFrame) -> pd.DataFrame:
    """Join the real REE-to-subsystem mapping (PR-35), raising on any REE
    this dataset has that the registry doesn't know about."""
    unmapped = set(df["nom_ree"]) - set(ree_map["ree"])
    if unmapped:
        raise ValueError(f"REE(s) with no subsystem mapping: {sorted(unmapped)}")
    return df.merge(ree_map, left_on="nom_ree", right_on="ree", how="left")


def build_tidy_reservoir(df: pd.DataFrame, ree_map: pd.DataFrame) -> pd.DataFrame:
    tidy = (
        attach_subsystem(df, ree_map)
        .pipe(parse_dates)
        .rename(
            columns={
                "ear_max_ree": "ear_max_mwmes",
                "ear_verif_ree_mwmes": "ear_verif_mwmes",
                "ear_verif_ree_percentual": "ear_verif_pct",
            }
        )[["date", "ree", "subsystem", "ear_max_mwmes", "ear_verif_mwmes", "ear_verif_pct"]]
        .sort_values(["date", "ree"])
        .reset_index(drop=True)
    )

    # Deliberately NOT a "every REE shares the same date count" check -
    # real data shows genuine per-REE coverage differences (some REEs
    # didn't exist as tracked units for the full window; ITAIPU's EAR
    # reporting stops in 2019 - see the data dictionary's notes). Each
    # REE's own series is checked for internal gaps, but a KNOWN, already
    # investigated one (REPORTING_GAPS) prints a warning instead of
    # raising - a genuinely new, uninvestigated gap still raises.
    for ree, dates in tidy.groupby("ree")["date"]:
        deltas = [d for d in dates.diff().dropna().unique() if d != pd.Timedelta(days=1)]
        known = REPORTING_GAPS.get(ree, [])
        unexpected = [d for d in deltas if d not in known]
        if unexpected:
            raise ValueError(f"non-daily gap or duplicate in {ree}: {unexpected}")
        if deltas:
            print(
                f"NOTE: {ree} has a known, investigated reporting gap ({deltas}) - "
                "see docs/data-dictionary/ons/ear_ree.yaml's notes.",
                file=sys.stderr,
            )

    # Both directions clipped, not raised - a real, checked, explained
    # quirk (data dictionary notes), concentrated in the REEs with the
    # smallest absolute capacity. Failing the whole build over a small,
    # explicable boundary issue would be worse than bounding it.
    below_zero = tidy["ear_verif_mwmes"] < 0
    tidy.loc[below_zero, "ear_verif_mwmes"] = 0.0
    tidy.loc[below_zero, "ear_verif_pct"] = 0.0

    above_max = tidy["ear_verif_mwmes"] > tidy["ear_max_mwmes"]
    tidy.loc[above_max, "ear_verif_mwmes"] = tidy.loc[above_max, "ear_max_mwmes"]
    tidy.loc[above_max, "ear_verif_pct"] = 100.0

    return tidy


def latest_capacity(tidy: pd.DataFrame) -> pd.DataFrame:
    """Current reservoir capacity per REE - the MOST RECENT date's
    ear_max_mwmes for that REE specifically, not a single global latest
    date (ITAIPU's series ends in 2019, well before the others')."""
    idx = tidy.groupby("ree")["date"].idxmax()
    return (
        tidy.loc[idx, ["ree", "subsystem", "ear_max_mwmes"]]
        .sort_values("ree")
        .reset_index(drop=True)
    )


def write_csv(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    ree_map = pd.read_csv(snake.input.ree_map)
    tidy = build_tidy_reservoir(df, ree_map)

    write_csv(tidy, Path(snake.output.history))
    write_csv(latest_capacity(tidy), Path(snake.output.capacity))


if __name__ == "__main__":
    main()
