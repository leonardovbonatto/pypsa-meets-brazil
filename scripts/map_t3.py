# SPDX-FileCopyrightText: 2026 pypsa-meets-brazil contributors
# SPDX-License-Identifier: MIT
"""
An interactive map of the T3 nodal network (ADR-0026) as one local HTML
file. EPE-derived, so it is written under git-ignored resources/epe/ and
never published (ADR-0026 decision 1).

Coordinates come from EPE's `gcbus.dat` (45% of buses). Buses sharing a
transformer sit in the same substation, so a bus without coordinates takes
its transformer neighbour's, repeated until stable. Lines are drawn when
both ends have coordinates; the legend reports how many could not be.
"""

# NOTE: no `from __future__ import annotations` - see write_manifest.py.

import json
from pathlib import Path

import pandas as pd
import pypsa

VOLTAGE_CLASSES = [
    (700, "765 kV"),
    (480, "500-525 kV"),
    (400, "440 kV"),
    (300, "345 kV"),
    (200, "230 kV"),
    (0, "138 kV and below"),
]
COLOURS = {
    "765 kV": "#7b2cbf",
    "500-525 kV": "#d62828",
    "440 kV": "#f77f00",
    "345 kV": "#2a9d8f",
    "230 kV": "#457b9d",
    "138 kV and below": "#a8b2bd",
}


def voltage_class(kv: float) -> str:
    return next(label for floor, label in VOLTAGE_CLASSES if kv >= floor)


def fill_coordinates(n: pypsa.Network) -> pd.DataFrame:
    """bus -> (lat, lon), spreading known coordinates across transformers."""
    xy = n.buses[["y", "x"]].rename(columns={"y": "lat", "x": "lon"})
    # PyPSA stores a missing coordinate as 0: (0, 0) is off Africa, not Brazil.
    xy = xy.mask((xy["lat"] == 0) & (xy["lon"] == 0))
    tr = n.lines[n.lines["kind"] == "transformer"][["bus0", "bus1"]]
    while True:
        known = xy.dropna()
        a = tr[tr["bus1"].isin(known.index) & ~tr["bus0"].isin(known.index)]
        b = tr[tr["bus0"].isin(known.index) & ~tr["bus1"].isin(known.index)]
        fill = pd.concat(
            [
                known.loc[a["bus1"]].set_axis(a["bus0"].to_numpy()),
                known.loc[b["bus0"]].set_axis(b["bus1"].to_numpy()),
            ]
        )
        fill = fill[~fill.index.duplicated()]
        if fill.empty:
            return xy
        xy.loc[fill.index] = fill.to_numpy()


def approximate_coordinates(
    n: pypsa.Network, xy: pd.DataFrame, rounds: int = 50
) -> tuple[pd.DataFrame, pd.Index]:
    """Buses still without coordinates go to the mean of their placed
    neighbours across any branch or HVDC link, repeated. These positions
    are drawn as approximate. Returns (coordinates, approximate buses)."""
    edges = pd.concat([n.lines[["bus0", "bus1"]], n.links[["bus0", "bus1"]]])
    both = pd.concat([edges, edges.rename(columns={"bus0": "bus1", "bus1": "bus0"})])
    approx = []
    for _ in range(rounds):
        missing = xy.index[xy["lat"].isna()]
        if missing.empty:
            break
        e = both[both["bus0"].isin(missing) & both["bus1"].isin(xy.dropna().index)]
        if e.empty:
            break
        mean = xy.loc[e["bus1"]].set_axis(e["bus0"].to_numpy()).groupby(level=0).mean()
        xy.loc[mean.index] = mean.to_numpy()
        approx.extend(mean.index)
    return xy, pd.Index(approx)


def map_data(n: pypsa.Network) -> dict:
    xy, approx = approximate_coordinates(n, fill_coordinates(n))
    buses = n.buses.join(xy)
    lines = n.lines[n.lines["kind"] == "line"].copy()
    lines["kv"] = lines["bus0"].map(n.buses["v_nom"])
    ok = lines["bus0"].map(xy["lat"]).notna() & lines["bus1"].map(xy["lat"]).notna()
    drawn = lines[ok]
    segments = {}
    for label, group in drawn.groupby(drawn["kv"].map(voltage_class)):
        segments[label] = [
            [
                [round(xy.at[r.bus0, "lat"], 4), round(xy.at[r.bus0, "lon"], 4)],
                [round(xy.at[r.bus1, "lat"], 4), round(xy.at[r.bus1, "lon"], 4)],
                f"{r.Index} {int(r.kv)} kV, {'no rating' if r.s_nom >= 1e5 else f'{r.s_nom:.0f} MVA'}"
                + (" (position approximate)" if (r.bus0 in approx or r.bus1 in approx) else ""),
                int(r.bus0 in approx or r.bus1 in approx),
            ]
            for r in group.itertuples()
        ]
    hvdc = []
    for _, link in n.links.iterrows():
        if pd.notna(xy.at[link.bus0, "lat"]) and pd.notna(xy.at[link.bus1, "lat"]):
            hvdc.append(
                [
                    [round(xy.at[link.bus0, "lat"], 4), round(xy.at[link.bus0, "lon"], 4)],
                    [round(xy.at[link.bus1, "lat"], 4), round(xy.at[link.bus1, "lon"], 4)],
                    f"{link.link_name}: {link.p_nom:.0f} MW",
                ]
            )
    hv = buses[(buses["v_nom"] >= 230) & (buses["v_nom"] < 900) & buses["lat"].notna()]
    points = [
        [
            round(r.lat, 4),
            round(r.lon, 4),
            f"{r.Index} ({r.state}, {r.subsystem}, {r.v_nom:.0f} kV)",
            r.subsystem,
        ]
        for r in hv.itertuples()
    ]
    return {
        "segments": segments,
        "hvdc": hvdc,
        "points": points,
        "stats": {
            "buses": len(buses),
            "buses_with_coordinates_raw": int(((n.buses["y"] != 0) | (n.buses["x"] != 0)).sum()),
            "buses_with_coordinates_filled": int(buses["lat"].notna().sum()) - len(approx),
            "buses_placed_approximately": len(approx),
            "lines": len(lines),
            "lines_drawn": int(ok.sum()),
            "hvdc_drawn": len(hvdc),
            "hvdc": len(n.links),
        },
    }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>T3 Network Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root { --bg:#ffffff; --fg:#1d2433; --muted:#5b6575; --panel:#ffffffee; --border:#d5dae1; }
@media (prefers-color-scheme: dark) { :root { --bg:#12161d; --fg:#e6e9ee; --muted:#9aa3b2; --panel:#1b2129ee; --border:#2e3642; } }
html, body { margin:0; height:100%; background:var(--bg); color:var(--fg); font:14px/1.4 system-ui, sans-serif; }
#map { position:absolute; inset:0; }
.panel { position:absolute; z-index:1000; top:12px; right:12px; max-width:300px; background:var(--panel);
  border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
.panel h1 { font-size:15px; margin:0 0 6px; } .panel p { margin:4px 0; color:var(--muted); font-size:12px; }
.key { display:flex; align-items:center; gap:8px; margin:3px 0; font-size:12px; cursor:pointer; user-select:none; }
.key i { display:inline-block; width:22px; height:4px; border-radius:2px; }
.key.off { opacity:.35; }
@media (max-width:600px) { .panel { left:12px; right:12px; max-width:none; } }
</style></head><body>
<div id="map"></div>
<div class="panel"><h1>T3 network (EPE base, local)</h1>
<p id="stats"></p><div id="keys"></div>
<p>Click a line class to hide or show it. Buses: 230 kV and up, coloured by subsystem.</p></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = __DATA__;
const COLOURS = __COLOURS__;
const SUB = {N:"#e9c46a", NE:"#f4a261", SE_CO:"#264653", S:"#2a9d8f"};
const map = L.map("map", {preferCanvas:true}).setView([-14, -52], 4);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {attribution:"&copy; OpenStreetMap, &copy; CARTO", maxZoom:12}).addTo(map);
const layers = {};
const order = ["138 kV and below","230 kV","345 kV","440 kV","500-525 kV","765 kV"];
for (const label of order) {
  const segs = DATA.segments[label] || [];
  const w = label === "765 kV" ? 3 : label === "500-525 kV" ? 2.2 : label === "138 kV and below" ? 0.6 : 1.4;
  layers[label] = L.layerGroup(segs.map(s => L.polyline([s[0], s[1]], {color:COLOURS[label], weight:w, opacity: s[3] ? .45 : .9, dashArray: s[3] ? "3 4" : null}).bindTooltip(s[2]))).addTo(map);
}
layers["HVDC"] = L.layerGroup(DATA.hvdc.map(s => L.polyline([s[0], s[1]], {color:"#000", weight:3, dashArray:"6 5"}).bindTooltip(s[2]))).addTo(map);
layers["Buses"] = L.layerGroup(DATA.points.map(p => L.circleMarker([p[0], p[1]], {radius:2.5, weight:0, fillOpacity:.9, fillColor:SUB[p[3]] || "#888"}).bindTooltip(p[2]))).addTo(map);
const keys = document.getElementById("keys");
for (const label of [...order].reverse().concat(["HVDC", "Buses"])) {
  const n = label === "HVDC" ? DATA.hvdc.length : label === "Buses" ? DATA.points.length : (DATA.segments[label] || []).length;
  const div = document.createElement("div"); div.className = "key";
  const colour = label === "HVDC" ? "#000" : label === "Buses" ? "#264653" : COLOURS[label];
  div.innerHTML = `<i style="background:${colour}"></i>${label} (${n})`;
  div.onclick = () => { if (map.hasLayer(layers[label])) { map.removeLayer(layers[label]); div.classList.add("off"); } else { map.addLayer(layers[label]); div.classList.remove("off"); } };
  keys.appendChild(div);
}
const s = DATA.stats;
document.getElementById("stats").textContent = `${s.lines_drawn} of ${s.lines} lines drawn. Buses: ${s.buses_with_coordinates_raw} with EPE coordinates, ${s.buses_with_coordinates_filled - s.buses_with_coordinates_raw} more through their transformers, ${s.buses_placed_approximately} approximate (mean of neighbours; their lines dashed and faint), ${s.buses - s.buses_with_coordinates_filled - s.buses_placed_approximately} not placed. HVDC ${s.hvdc_drawn} of ${s.hvdc}.`;
</script></body></html>
"""


def main() -> None:
    snake = globals()["snakemake"]
    data = map_data(pypsa.Network(str(snake.input.network)))
    html = PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace(
        "__COLOURS__", json.dumps(COLOURS)
    )
    Path(snake.output.html).write_text(html, encoding="utf-8")
    Path(snake.output.stats).write_text(json.dumps(data["stats"], indent=2) + "\n")


if __name__ == "__main__":
    main()
