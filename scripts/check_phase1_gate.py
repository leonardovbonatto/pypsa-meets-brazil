# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
The roadmap's Phase 1 gate (ADR-0020): does the solved T0 model reproduce
ONS's 2024 energy balance and interchange within about 5%?

**Pass criterion, fixed in ADR-0020 before this ran:**

1. national mean generation of each SCORED_SOURCES is within
   GENERATION_TOLERANCE of ONS's `geracao_usina`;
2. each boundary's mean signed flow is within INTERCHANGE_TOLERANCE of its
   capacity (links_t0 p_nom) of ONS's `intercambio_nacional`.

Hydro and rooftop solar (MMGD) are backcasts of the same observations
(ADR-0007, PR-19): reported, not scored.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _ons import map_subsystems

GENERATION_TOLERANCE = 0.05
INTERCHANGE_TOLERANCE = 0.05
SCORED_SOURCES = ["wind", "solar", "nuclear", "thermal"]
REPORTED_SOURCES = ["hydro", "solar_mmgd"]

MMGD_MODALITY = "Pequenas Usinas (MMGD)"
ONS_SOURCE = {
    "EOLIELÉTRICA": "wind",
    "FOTOVOLTAICA": "solar",
    "NUCLEAR": "nuclear",
    "TÉRMICA": "thermal",
    "HIDROELÉTRICA": "hydro",
}
FLOW_COLUMN = "val_intercambiomwmed"


def observed_generation(raw: pd.DataFrame) -> pd.DataFrame:
    """(subsystem, source) -> mean MW over the hours present. `raw` is the
    concatenated hourly `geracao_usina` rows; MMGD solar becomes its own
    source, `solar_mmgd`, as in the model."""
    df = map_subsystems(raw)
    source = df["nom_tipousina"].map(ONS_SOURCE)
    unknown = sorted(set(df.loc[source.isna(), "nom_tipousina"]))
    if unknown:
        raise ValueError(f"unmapped ONS plant type(s): {unknown}")
    mmgd = df["cod_modalidadeoperacao"].eq(MMGD_MODALITY) & source.eq("solar")
    source = source.where(~mmgd, "solar_mmgd")
    n_hours = df["din_instante"].nunique()
    return (
        df.assign(source=source)
        .groupby(["subsystem", "source"], as_index=False)["val_geracao"]
        .sum()
        .assign(observed_mw=lambda d: d["val_geracao"] / n_hours)
        .drop(columns="val_geracao")
    )


SMALL_SUFFIX = "_small"


def model_generation(n: pypsa.Network) -> pd.DataFrame:
    """(subsystem, source) -> mean MW dispatched, weighted by snapshot hours.
    Small TIPO III plants (`<source>_small`, PR-60) count under their source,
    as ONS counts them; `model_small_mw` shows that backcast part."""
    weights = n.snapshot_weightings.generators
    energy = n.generators_t.p.mul(weights, axis=0).sum()
    g = n.generators.loc[energy.index]
    keep = g["carrier"] != "load_shedding"
    carrier = g["carrier"]
    work = pd.DataFrame(
        {
            "subsystem": g["bus"],
            "source": carrier.str.removesuffix(SMALL_SUFFIX),
            "e": energy,
            "e_small": energy.where(carrier.str.endswith(SMALL_SUFFIX), 0.0),
        }
    )[keep]
    table = work.groupby(["subsystem", "source"], as_index=False)[["e", "e_small"]].sum()
    table["model_mw"] = table.pop("e") / weights.sum()
    table["model_small_mw"] = table.pop("e_small") / weights.sum()
    return table


def observed_interchange(raw: pd.DataFrame) -> pd.DataFrame:
    """(bus0, bus1) -> hourly signed flow, MW, positive bus0 -> bus1."""
    df = map_subsystems(raw, column="id_subsistema_origem").rename(columns={"subsystem": "bus0"})
    df = map_subsystems(df, column="id_subsistema_destino").rename(columns={"subsystem": "bus1"})
    return df.assign(snapshot=pd.to_datetime(df["din_instante"]))[
        ["snapshot", "bus0", "bus1", FLOW_COLUMN]
    ].rename(columns={FLOW_COLUMN: "observed_mw"})


def _correlation(a: pd.Series, b: pd.Series) -> float:
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def interchange_table(
    n: pypsa.Network, observed: pd.DataFrame, links: pd.DataFrame
) -> pd.DataFrame:
    """One row per boundary: mean signed flow (model, ONS), capacity, hourly
    correlation and mean absolute flow."""
    rows = []
    for _, link in links.iterrows():
        name = n.links.index[(n.links["bus0"] == link["bus0"]) & (n.links["bus1"] == link["bus1"])]
        if len(name) != 1:
            raise ValueError(f"expected one link {link['bus0']}-{link['bus1']}, found {len(name)}")
        model = n.links_t.p0[name[0]]
        obs = (
            observed[(observed["bus0"] == link["bus0"]) & (observed["bus1"] == link["bus1"])]
            .groupby("snapshot")["observed_mw"]
            .mean()
            .reindex(model.index)
        )
        both = pd.concat({"model": model, "obs": obs}, axis=1).dropna()
        rows.append(
            {
                "boundary": f"{link['bus0']}-{link['bus1']}",
                "p_nom_mw": float(link["p_nom_mw"]),
                "model_mean_mw": float(model.mean()),
                "observed_mean_mw": float(obs.mean()),
                "model_mean_abs_mw": float(model.abs().mean()),
                "observed_mean_abs_mw": float(obs.abs().mean()),
                "hourly_correlation": _correlation(both["model"], both["obs"]),
                "hours_compared": len(both),
            }
        )
    table = pd.DataFrame(rows)
    table["error_share_of_capacity"] = (
        table["model_mean_mw"] - table["observed_mean_mw"]
    ).abs() / table["p_nom_mw"]
    table["passed"] = table["error_share_of_capacity"] <= INTERCHANGE_TOLERANCE
    return table


def generation_table(model: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    """(subsystem, source) rows with both means, plus national rows
    (subsystem "SIN")."""
    table = model.merge(observed, on=["subsystem", "source"], how="outer").fillna(0.0)
    national = table.groupby("source", as_index=False)[
        ["model_mw", "model_small_mw", "observed_mw"]
    ].sum()
    table = pd.concat([table, national.assign(subsystem="SIN")], ignore_index=True)
    table["ratio"] = table["model_mw"] / table["observed_mw"].replace(0.0, np.nan)
    return table


def gate_report(generation: pd.DataFrame, interchange: pd.DataFrame) -> dict:
    national = generation[generation["subsystem"] == "SIN"].set_index("source")
    missing = set(SCORED_SOURCES) - set(national.index)
    if missing:
        raise ValueError(f"no national generation for {sorted(missing)}")
    sources = {}
    for s in SCORED_SOURCES + [x for x in REPORTED_SOURCES if x in national.index]:
        ratio = float(national.at[s, "ratio"])
        sources[s] = {
            "model_mw": float(national.at[s, "model_mw"]),
            "model_small_backcast_mw": float(
                national.get("model_small_mw", pd.Series(0.0, index=national.index)).get(s, 0.0)
            ),
            "observed_mw": float(national.at[s, "observed_mw"]),
            "ratio": ratio,
            "scored": s in SCORED_SOURCES,
            "passed": bool(abs(ratio - 1.0) <= GENERATION_TOLERANCE)
            if s in SCORED_SOURCES
            else None,
        }
    generation_pass = all(v["passed"] for v in sources.values() if v["scored"])
    interchange_pass = bool(interchange["passed"].all())
    return {
        "passed": bool(generation_pass and interchange_pass),
        "generation_passed": bool(generation_pass),
        "interchange_passed": interchange_pass,
        "criteria": {
            "generation_tolerance": GENERATION_TOLERANCE,
            "interchange_tolerance_share_of_capacity": INTERCHANGE_TOLERANCE,
            "scored_sources": SCORED_SOURCES,
        },
        "national_generation": sources,
        "interchange": interchange.to_dict(orient="records"),
    }


def main() -> None:
    snake = globals()["snakemake"]
    n = pypsa.Network(str(snake.input.network))
    columns = [
        "din_instante",
        "id_subsistema",
        "nom_tipousina",
        "cod_modalidadeoperacao",
        "val_geracao",
    ]
    raw = pd.concat(
        [pd.read_csv(p, sep=";", usecols=columns) for p in snake.input.generation],
        ignore_index=True,
    )
    generation = generation_table(model_generation(n), observed_generation(raw))
    interchange = interchange_table(
        n,
        observed_interchange(
            pd.concat([pd.read_csv(p, sep=";") for p in snake.input.interchange], ignore_index=True)
        ),
        pd.read_csv(snake.input.links),
    )
    report = gate_report(generation, interchange)

    Path(snake.output.generation).parent.mkdir(parents=True, exist_ok=True)
    generation.to_csv(snake.output.generation, index=False)
    interchange.to_csv(snake.output.interchange, index=False)
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
