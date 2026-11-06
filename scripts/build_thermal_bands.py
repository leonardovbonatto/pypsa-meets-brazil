# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
Build T0 thermal cost bands from joined plants (ADR-0021).

A plant is joined when it is a UTE in `disponibilidade_usina` (hourly
operational availability, keyed by `ceg`) and has a 2024 CVU through the
bridge `geracao_termica_despacho` provides (`cod_usinaplanejamento` ->
`ceg`). Joined plants are grouped per subsystem into CVU bands; everything
else stays in the residual `{s} thermal` generator.

Outputs:
- bands: one row per band generator (name, subsystem, marginal_cost,
  p_nom_mw, n_plants);
- band availability: hourly p_max_pu per band;
- band floor: monthly floor MW per band (sum of its plants' ADR-0016 floor);
- residual: per subsystem, the residual's p_nom and monthly floor.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ons import map_subsystems

BAND_EDGES = [150.0, 300.0, 500.0, 800.0]
THERMAL_TYPE = "UTE"
TOTAL = "val_verifgeracao"
PRICE_DRIVEN = "val_verifordemdemeritoacimadainflex"


def plant_cvu(cvu: pd.DataFrame, bridge: pd.DataFrame, *, year: int) -> pd.Series:
    """ceg -> mean CVU over the year's weeks and the plant's planning codes."""
    by_code = cvu[cvu["ano_referencia"] == year].groupby("cod_usinaplanejamento")["val_cvu"].mean()
    joined = bridge.assign(cvu=bridge["cod_usinaplanejamento"].map(by_code)).dropna(subset=["cvu"])
    return joined.groupby("ceg")["cvu"].mean()


def dispatch_bridge(despacho: pd.DataFrame) -> pd.DataFrame:
    """Unique (cod_usinaplanejamento, ceg) pairs."""
    return despacho[["cod_usinaplanejamento", "ceg"]].drop_duplicates().reset_index(drop=True)


def plant_floor(despacho: pd.DataFrame) -> pd.DataFrame:
    """(ceg, month) -> mean floor MW: verified minus merit order above
    inflexibility, ADR-0016's definition, per plant."""
    work = despacho.assign(
        month=pd.to_datetime(despacho["din_instante"]).dt.month,
        floor_mw=despacho[TOTAL] - despacho[PRICE_DRIVEN],
    )
    hours = work.groupby("month")["din_instante"].nunique()
    total = work.groupby(["ceg", "month"])["floor_mw"].sum().reset_index()
    total["floor_mw"] = total["floor_mw"] / total["month"].map(hours)
    return total


def build_bands(
    availability: pd.DataFrame, cvu_by_ceg: pd.Series, floor_by_plant: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(bands, hourly band p_max_pu, monthly band floor) from the joined plants.
    `availability` is the UTE rows of disponibilidade_usina."""
    ute = map_subsystems(availability[availability["id_tipousina"] == THERMAL_TYPE])
    ute = ute[ute["ceg"].isin(cvu_by_ceg.index)]
    plants = ute.groupby("ceg").agg(
        subsystem=("subsystem", "first"), installed=("val_potenciainstalada", "max")
    )
    plants["cvu"] = cvu_by_ceg.reindex(plants.index)
    plants["band"] = np.digitize(plants["cvu"], BAND_EDGES) + 1
    plants["name"] = plants["subsystem"] + " thermal_b" + plants["band"].astype(str)

    bands = (
        plants.assign(weighted=plants["cvu"] * plants["installed"])
        .groupby(["name", "subsystem"], as_index=False)
        .agg(p_nom_mw=("installed", "sum"), weighted=("weighted", "sum"), n_plants=("cvu", "size"))
    )
    bands["marginal_cost"] = bands.pop("weighted") / bands["p_nom_mw"]

    hourly = (
        ute.assign(name=ute["ceg"].map(plants["name"]))
        .groupby(["name", "din_instante"], as_index=False)["val_dispoperacional"]
        .sum()
    )
    hourly["p_max_pu"] = hourly["val_dispoperacional"] / hourly["name"].map(
        bands.set_index("name")["p_nom_mw"]
    )
    if (hourly["p_max_pu"] > 1.0 + 1e-9).any():
        raise ValueError("band availability exceeds installed capacity")
    band_availability = hourly.rename(columns={"din_instante": "snapshot"})[
        ["snapshot", "name", "p_max_pu"]
    ]

    floor = floor_by_plant[floor_by_plant["ceg"].isin(plants.index)]
    band_floor = (
        floor.assign(name=floor["ceg"].map(plants["name"]))
        .groupby(["month", "name"], as_index=False)["floor_mw"]
        .sum()
    )
    band_floor["floor_mw"] = band_floor["floor_mw"].clip(lower=0.0)
    return bands, band_availability, band_floor


def residual(
    generators: pd.DataFrame,
    bands: pd.DataFrame,
    subsystem_floor: pd.DataFrame,
    band_floor: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(residual capacity per subsystem, residual monthly floor per subsystem)."""
    registry = generators[generators["carrier"] == "thermal"].set_index("subsystem")["p_nom_mw"]
    in_bands = bands.groupby("subsystem")["p_nom_mw"].sum().reindex(registry.index, fill_value=0.0)
    capacity = (registry - in_bands).clip(lower=0.0).rename("p_nom_mw").reset_index()
    by_subsystem = band_floor.assign(subsystem=band_floor["name"].str.split(" ").str[0])
    carried = by_subsystem.groupby(["month", "subsystem"])["floor_mw"].sum()
    rest = subsystem_floor.set_index(["month", "subsystem"])["floor_mw"]
    floor = (
        (rest - carried.reindex(rest.index, fill_value=0.0))
        .clip(lower=0.0)
        .rename("floor_mw")
        .reset_index()
    )
    return capacity, floor


def main() -> None:
    snake = globals()["snakemake"]
    year = int(snake.params.year)
    despacho = pd.concat(
        [
            pd.read_csv(
                p,
                sep=";",
                usecols=["din_instante", "cod_usinaplanejamento", "ceg", TOTAL, PRICE_DRIVEN],
            )
            for p in snake.input.despacho
        ],
        ignore_index=True,
    )
    availability = pd.concat(
        [
            pd.read_csv(
                p,
                sep=";",
                usecols=[
                    "id_subsistema",
                    "id_tipousina",
                    "ceg",
                    "din_instante",
                    "val_potenciainstalada",
                    "val_dispoperacional",
                ],
            )
            for p in snake.input.availability
        ],
        ignore_index=True,
    )
    cvu = pd.concat([pd.read_csv(p, sep=";") for p in snake.input.cvu], ignore_index=True)
    bands, band_availability, band_floor = build_bands(
        availability, plant_cvu(cvu, dispatch_bridge(despacho), year=year), plant_floor(despacho)
    )
    capacity, floor = residual(
        pd.read_csv(snake.input.generators), bands, pd.read_csv(snake.input.floor), band_floor
    )
    out = Path(snake.output.bands)
    out.parent.mkdir(parents=True, exist_ok=True)
    bands.to_csv(out, index=False)
    band_availability.to_csv(snake.output.band_availability, index=False)
    band_floor.to_csv(snake.output.band_floor, index=False)
    capacity.to_csv(snake.output.residual_capacity, index=False)
    floor.to_csv(snake.output.residual_floor, index=False)


if __name__ == "__main__":
    main()
