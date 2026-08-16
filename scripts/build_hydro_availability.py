# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build the T0 hydro availability profile from ONS observed generation.

THIS IS A BACKCAST, NOT AN OPTIMISATION (ADR-0007). It tells the model what
hydro actually did, rather than letting the model decide what hydro should
do. Hydro dispatch therefore becomes a model *input*, and any price
comparison against observed CMO is partly circular. Read ADR-0007 before
presenting any number that depends on this.

Kept separate from `build_availability.py` (wind/solar) on purpose: this
source needs a modalidade filter that dataset does not, and the two are
expected to diverge further when real water values replace this.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _inspect import inspect_csv, load_dictionary, to_pandera_schema
from _ons import map_subsystems

# This dataset's spelling, which follows capacidade_geracao rather than
# fator_capacidade's "Eólica"/"Solar" (see the data dictionary).
HYDRO_TYPE = "HIDROELÉTRICA"

# `geracao_usina` covers ALL plants; `capacidade_geracao` - the source of the
# p_nom denominator - covers only ONS-dispatched TIPO I/II units. Without
# this filter the numerator spans more plants than the denominator and the
# ratio exceeds 1.0 for subsystem S (1.021 in January 2024, verified). Filter
# rather than clip: clipping would hide a real population mismatch behind a
# plausible-looking number. See docs/handoffs/PR-17-*.md.
#
# "Conjunto de Usinas" is included because those ARE Tipo II-C plants, whose
# capacity is in capacidade_geracao (its largest modalidade, 3404 of 4656
# active rows) - geracao_usina simply reports them under the aggregation's
# name instead. Excluding them would drop real generation from the numerator
# while leaving its capacity in the denominator. Small for hydro (S +0.8%,
# SE_CO +0.5%, since only 59 of 819 hydro plants are Tipo II-C) but dominant
# for wind/solar, so getting it right here also prevents the same mistake
# being copied to a future non-hydro use.
MATCHING_MODALIDADES = {
    "TIPO I",
    "TIPO II-A",
    "TIPO II-B",
    "TIPO II-C",
    "Conjunto de Usinas",
}

GENERATION_COLUMN = "val_geracao"


def load_raw(paths: list[Path], *, delimiter: str = ";") -> pd.DataFrame:
    frames = [inspect_csv(p, delimiter=delimiter) for p in paths]
    return pd.concat(frames, ignore_index=True)


def validate_against_dictionary(df: pd.DataFrame, dictionary_path: Path) -> None:
    """Fail here, at the boundary, rather than downstream with a silently wrong number."""
    dictionary = load_dictionary(dictionary_path)
    schema = to_pandera_schema(dictionary)
    schema.validate(df)


def filter_hydro(df: pd.DataFrame) -> pd.DataFrame:
    """Hydro rows only, restricted to the modalidades `capacidade_geracao` also covers."""
    return df[
        (df["nom_tipousina"] == HYDRO_TYPE)
        & (df["cod_modalidadeoperacao"].isin(MATCHING_MODALIDADES))
    ].copy()


def build_hydro_availability(df: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (snapshot, subsystem): observed hydro generation divided by
    that subsystem's installed hydro capacity, as `p_max_pu`.

    `capacity` is `generators_t0.csv`. Raises if the ratio exceeds 1.0 for
    any subsystem rather than clipping - by construction the modalidade
    filter should prevent it, so a value above 1 means the population
    assumption has broken and needs re-checking, not silent correction.
    """
    hydro_capacity = capacity[capacity["carrier"] == "hydro"].set_index("subsystem")["p_nom_mw"]

    hourly = (
        filter_hydro(df)
        .pipe(map_subsystems)
        .groupby(["subsystem", "din_instante"], as_index=False)[GENERATION_COLUMN]
        .sum()
        .rename(columns={"din_instante": "snapshot", GENERATION_COLUMN: "generation_mw"})
    )

    missing = set(hourly["subsystem"]) - set(hydro_capacity.index)
    if missing:
        raise ValueError(f"subsystem(s) with hydro generation but no capacity: {sorted(missing)}")

    hourly["p_max_pu"] = hourly["generation_mw"] / hourly["subsystem"].map(hydro_capacity)

    over = hourly[hourly["p_max_pu"] > 1.0]
    if not over.empty:
        worst = over.loc[over["p_max_pu"].idxmax()]
        raise ValueError(
            "observed hydro generation exceeds installed capacity "
            f"({worst['subsystem']} at {worst['snapshot']}: p_max_pu="
            f"{worst['p_max_pu']:.4f}). The modalidade filter should prevent "
            "this - re-check the population match against capacidade_geracao "
            "rather than clipping (see ADR-0007 and PR-17's handoff)."
        )

    return (
        hourly.assign(carrier="hydro")[["snapshot", "subsystem", "carrier", "p_max_pu"]]
        .sort_values(["subsystem", "snapshot"])
        .reset_index(drop=True)
    )


def write_hydro_availability(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    snake = globals()["snakemake"]

    raw_paths = [Path(p) for p in snake.input.raw]
    df = load_raw(raw_paths)
    validate_against_dictionary(df, Path(snake.input.dictionary))

    capacity = pd.read_csv(snake.input.capacity)
    tidy = build_hydro_availability(df, capacity)
    write_hydro_availability(tidy, Path(snake.output[0]))


if __name__ == "__main__":
    main()
