# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
The T1 benchmark (ADR-0022 decision 5), fixed in that ADR before T1 ran:

1. national generation by source of the solved T1 network is within
   T0_TOLERANCE of the solved T0 network's (T1 is T0 split across states,
   so a larger gap means the split lost or invented energy);
2. inter-subsystem flows, summed over the T1 links that cross each T0
   boundary, scored with ADR-0020's interchange criterion: mean signed flow
   within 5% of the boundary's T0 capacity of ONS's.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
import sys
from pathlib import Path

import pandas as pd
import pypsa

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_phase1_gate import (
    GENERATION_TOLERANCE,
    INTERCHANGE_TOLERANCE,
    SCORED_SOURCES,
    _correlation,
    model_generation,
    observed_generation,
    observed_interchange,
)

T0_TOLERANCE = 0.01


def national(n: pypsa.Network) -> pd.Series:
    """source -> national mean MW, load shedding excluded."""
    return model_generation(n).groupby("source")["model_mw"].sum()


def boundary_flows(
    n: pypsa.Network, subsystem_of: pd.Series, boundaries: pd.DataFrame
) -> pd.DataFrame:
    """snapshot x boundary: net flow bus0 -> bus1 of each T0 boundary, summed
    over the links AND lines crossing it (PR-77: the clustered T1 has AC
    lines between subsystems), measured at the sending end (p0)."""
    out = {}
    for _, b in boundaries.iterrows():
        total = pd.Series(0.0, index=n.snapshots)
        for static, p0 in ((n.links, n.links_t.p0), (n.lines, n.lines_t.p0)):
            if static.empty:
                continue
            s0 = static["bus0"].map(subsystem_of)
            s1 = static["bus1"].map(subsystem_of)
            forward = static.index[(s0 == b["bus0"]) & (s1 == b["bus1"])]
            backward = static.index[(s0 == b["bus1"]) & (s1 == b["bus0"])]
            total = total + p0.reindex(columns=forward, fill_value=0.0).sum(axis=1)
            total = total - p0.reindex(columns=backward, fill_value=0.0).sum(axis=1)
        out[f"{b['bus0']}-{b['bus1']}"] = total
    return pd.DataFrame(out)


def t1_report(
    t1: pypsa.Network,
    t0: pypsa.Network,
    subsystem_of: pd.Series,
    observed: pd.DataFrame,
    boundaries: pd.DataFrame,
) -> dict:
    a, b = national(t1), national(t0)
    sources = sorted(set(a.index) | set(b.index))
    generation = {
        s: {
            "t1_mw": float(a.get(s, 0.0)),
            "t0_mw": float(b.get(s, 0.0)),
            "ratio": float(a.get(s, 0.0) / b[s]) if b.get(s, 0.0) else None,
        }
        for s in sources
    }
    for v in generation.values():
        v["passed"] = v["ratio"] is not None and abs(v["ratio"] - 1.0) <= T0_TOLERANCE
    flows = boundary_flows(t1, subsystem_of, boundaries)
    rows = []
    for _, bnd in boundaries.iterrows():
        key = f"{bnd['bus0']}-{bnd['bus1']}"
        obs = (
            observed[(observed["bus0"] == bnd["bus0"]) & (observed["bus1"] == bnd["bus1"])]
            .groupby("snapshot")["observed_mw"]
            .mean()
            .reindex(flows.index)
        )
        both = pd.concat({"model": flows[key], "obs": obs}, axis=1).dropna()
        error = abs(flows[key].mean() - obs.mean()) / float(bnd["p_nom_mw"])
        rows.append(
            {
                "boundary": key,
                "t1_mean_mw": float(flows[key].mean()),
                "observed_mean_mw": float(obs.mean()),
                "error_share_of_capacity": float(error),
                "hourly_correlation": _correlation(both["model"], both["obs"]),
                "passed": bool(error <= INTERCHANGE_TOLERANCE),
            }
        )
    generation_pass = all(v["passed"] for v in generation.values())
    interchange_pass = all(r["passed"] for r in rows)
    return {
        "passed": bool(generation_pass and interchange_pass),
        "generation_matches_t0": bool(generation_pass),
        "interchange_passed": bool(interchange_pass),
        "criteria": {
            "t0_tolerance": T0_TOLERANCE,
            "interchange_tolerance_share_of_capacity": INTERCHANGE_TOLERANCE,
        },
        "generation": generation,
        "interchange": rows,
    }


def versus_ons(t1: pypsa.Network, raw_generation: pd.DataFrame) -> dict:
    """PR-71, POST HOC: ADR-0020's generation check applied to T1 against
    ONS. Written after T1's numbers were seen (PR-70), so it is reported
    next to the pre-registered verdict and never decides it."""
    model = national(t1)
    observed = observed_generation(raw_generation).groupby("source")["observed_mw"].sum()
    out = {}
    for s in SCORED_SOURCES:
        ratio = float(model.get(s, 0.0) / observed[s])
        out[s] = {
            "t1_mw": float(model.get(s, 0.0)),
            "observed_mw": float(observed[s]),
            "ratio": ratio,
            "within_adr0020_tolerance": bool(abs(ratio - 1.0) <= GENERATION_TOLERANCE),
        }
    return {"post_hoc": True, "generation_vs_ons": out}


def main() -> None:
    snake = globals()["snakemake"]
    nodes = pd.read_csv(snake.input.nodes)
    observed = observed_interchange(
        pd.concat([pd.read_csv(p, sep=";") for p in snake.input.interchange], ignore_index=True)
    )
    report = t1_report(
        pypsa.Network(str(snake.input.t1)),
        pypsa.Network(str(snake.input.t0)),
        nodes.set_index("node")["subsystem"],
        observed,
        pd.read_csv(snake.input.links_t0),
    )
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
    report["post_hoc"] = versus_ons(pypsa.Network(str(snake.input.t1)), raw)
    Path(snake.output.report).parent.mkdir(parents=True, exist_ok=True)
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
