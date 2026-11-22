# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
The T3 nodal network's structure from EPE's tidy tables (ADR-0026): AC
buses, lines, transformers and HVDC links. No loads or generators yet.

- Elements with `Existing` = 1 are out: they enter by dated modification
  between 2030 and 2040 (`mcirc.dat`, checked PR-75).
- Impedances are % on 100 MVA. A line's x in ohm is x_pct / 100 * kV^2 /
  100 at bus0's voltage.
- Transformers become Lines with x referred to bus0's voltage the same way:
  in PyPSA's linear power flow a line's per-unit x is x_ohm / v_nom(bus0)^2,
  which gives back x_pct / 100 on 100 MVA. A PyPSA Transformer would take
  its s_nom as both base and limit, and EPE gives no transformer rating.
  Transformer lines get no thermal limit.
- Lines without a rating (99999 in EPE) get no thermal limit, and are counted.
- HVDC links connect the AC buses of their converters, bidirectional at
  their pole rating.
- DC buses and buses with no subsystem (Itaipu's 50 Hz side, tiny systems)
  are left out, with every branch touching them.

EPE data stays local: input and output under git-ignored resources/epe/.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
from pathlib import Path

import pandas as pd
import pypsa

BASE_MVA = 100.0
UNLIMITED_MVA = 1.0e6


def ohm(pct: pd.Series, kv: pd.Series) -> pd.Series:
    """% on 100 MVA at `kv` -> ohm."""
    return pct / 100.0 * kv**2 / BASE_MVA


def build_t3(
    buses: pd.DataFrame, lines: pd.DataFrame, transformers: pd.DataFrame, hvdc: pd.DataFrame
) -> tuple[pypsa.Network, dict]:
    keep = buses[buses["subsystem"].notna()].copy()
    keep["name"] = keep["bus"].astype(str)
    kv = keep.set_index("bus")["v_nom_kv"]
    n = pypsa.Network()
    n.add("Carrier", ["AC", "DC"])
    n.add(
        "Bus",
        keep["name"].tolist(),
        v_nom=keep["v_nom_kv"].to_numpy(),
        carrier="AC",
        x=keep["lon"].to_numpy(),
        y=keep["lat"].to_numpy(),
    )
    n.buses["state"] = keep["state"].to_numpy()
    n.buses["subsystem"] = keep["subsystem"].to_numpy()

    def inside(df):
        return df["bus0"].isin(kv.index) & df["bus1"].isin(kv.index)

    live_lines = lines[(lines["existing_flag"] == 0) & inside(lines)]
    live_tr = transformers[(transformers["existing_flag"] == 0) & inside(transformers)]
    rated = live_lines["s_nom_mva"].notna()
    n.add(
        "Line",
        ("L" + live_lines["line"].astype(str)).tolist(),
        bus0=live_lines["bus0"].astype(str).to_numpy(),
        bus1=live_lines["bus1"].astype(str).to_numpy(),
        x=ohm(live_lines["x_pct"], live_lines["bus0"].map(kv)).to_numpy(),
        r=ohm(live_lines["r_pct"], live_lines["bus0"].map(kv)).to_numpy(),
        s_nom=live_lines["s_nom_mva"].fillna(UNLIMITED_MVA).to_numpy(),
        carrier="AC",
    )
    n.add(
        "Line",
        ("T" + live_tr["transformer"].astype(str)).tolist(),
        bus0=live_tr["bus0"].astype(str).to_numpy(),
        bus1=live_tr["bus1"].astype(str).to_numpy(),
        x=ohm(live_tr["x_pct"], live_tr["bus0"].map(kv)).to_numpy(),
        r=ohm(live_tr["r_pct"], live_tr["bus0"].map(kv)).to_numpy(),
        s_nom=UNLIMITED_MVA,
        carrier="AC",
    )
    n.lines["kind"] = ["line"] * len(live_lines) + ["transformer"] * len(live_tr)
    live_dc = hvdc[(hvdc["existing_flag"] == 0) & inside(hvdc)]
    n.add(
        "Link",
        ("HVDC" + live_dc["hvdc"].astype(str)).tolist(),
        bus0=live_dc["bus0"].astype(str).to_numpy(),
        bus1=live_dc["bus1"].astype(str).to_numpy(),
        p_nom=live_dc["p_nom_mw"].to_numpy(),
        p_min_pu=-1.0,
        carrier="DC",
    )
    n.links["link_name"] = live_dc["link_name"].to_numpy()
    n.determine_network_topology()
    sizes = n.buses.groupby("sub_network").size().sort_values(ascending=False)
    report = {
        "buses": len(n.buses),
        "lines": int((n.lines["kind"] == "line").sum()),
        "transformers": int((n.lines["kind"] == "transformer").sum()),
        "hvdc_links": len(n.links),
        "dropped_future_lines": int((lines["existing_flag"] == 1).sum()),
        "dropped_future_transformers": int((transformers["existing_flag"] == 1).sum()),
        "lines_without_rating": int((~rated).sum()),
        "ac_islands": len(sizes),
        "largest_island_buses": int(sizes.iloc[0]),
        "buses_outside_largest_island": int(sizes.iloc[1:].sum()),
        "island_sizes_top10": [int(v) for v in sizes.head(10)],
        "zero_or_negative_x_lines": int((n.lines["x"] <= 0).sum()),
    }
    return n, report


def main() -> None:
    snake = globals()["snakemake"]
    n, report = build_t3(
        pd.read_csv(snake.input.buses),
        pd.read_csv(snake.input.lines),
        pd.read_csv(snake.input.transformers),
        pd.read_csv(snake.input.hvdc),
    )
    Path(snake.output.network).parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(snake.output.network))
    Path(snake.output.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()


def main_component(n: pypsa.Network) -> pd.Index:
    """Buses connected to the largest group through lines AND HVDC links.
    PR-77: Itaipu's 50 Hz side and the Madeira collector are AC islands that
    reach the grid only over HVDC; PyPSA's AC sub-networks treat them as
    separate, and dropping them dropped Itaipu's and Madeira's HVDC."""
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(n.buses.index)
    g.add_edges_from(zip(n.lines["bus0"], n.lines["bus1"], strict=True))
    g.add_edges_from(zip(n.links["bus0"], n.links["bus1"], strict=True))
    return pd.Index(sorted(max(nx.connected_components(g), key=len)))
